"""
Consumidor de eventos Kafka para ATOMIC_TASK_PROPOSED.
"""

import json
import asyncio
import traceback
from uuid import UUID, uuid4
from aiokafka import AIOKafkaConsumer
from ms_ob02.config.settings import settings
from ms_ob02.kafka.schemas import AtomicTaskProposedEvent


def _clean_json_raw(raw: str) -> str:
    """Limpia fences de markdown de una cadena JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    return raw.strip()


async def _publish_fault(
    event: AtomicTaskProposedEvent,
    reason: str,
    detail: str,
    plan_id: UUID | None = None,
    device_ids: list[UUID] | None = None,
    attempts_made: int = 0,
) -> None:
    """Publica un evento ATOMIC_TASK_FAULT."""
    from ms_ob02.kafka.producer import kafka_producer
    from ms_ob02.kafka.schemas import AtomicTaskFaultEvent

    fault_event = AtomicTaskFaultEvent(
        atomic_task_id=str(event.atomic_task_id),
        logical_task_id=str(event.logical_task_id),
        policy_id=str(event.policy_id),
        intent_id=str(event.intent_id),
        vendor=event.vendor,
        platform=event.platform,
        format=event.format,
        plan_id=plan_id,
        device_ids=device_ids,
        error_reason=reason,
        attempts_made=attempts_made,
        last_validation_result="INVALID",
    )
    await kafka_producer.send_atomic_task_fault(fault_event)
    print(f"ATOMIC_TASK_FAULT publicado ({reason}): {detail}")


async def _process_plan(event: AtomicTaskProposedEvent, plan) -> bool:
    """
    Procesa una cohorte de dispositivos con sus reintentos.

    Args:
        event: Evento original.
        plan: Plan de ejecución de la cohorte.

    Returns:
        True si la cohorte se completó correctamente.
    """
    from ms_ob02.crews.content_crew.crew import run_command_crew
    from ms_ob02.db.database import save_command_result
    from ms_ob02.execution.decision_engine import build_execution_profile
    from ms_ob02.kafka.producer import kafka_producer
    from ms_ob02.kafka.schemas import CommandSentEvent

    max_retries = 3
    command_id = uuid4()          # 1 command_id por plan, reutilizado en los intentos
    profile = build_execution_profile(plan)

    for attempt in range(max_retries):
        try:
            print(
                f"Intento {attempt + 1}/{max_retries} "
                f"para plan {plan.plan_id} (formato {plan.artifact_format.value})..."
            )

            result = await run_command_crew(
                atomic_task_json=event.atomic_task_json,
                vendor=event.vendor,
                platform=event.platform,
                format=plan.artifact_format.value,
                attempt_count=attempt + 1,
                command_id=str(command_id),
                execution_profile=profile,
            )

            raw = result.raw
            if isinstance(raw, str):
                raw = _clean_json_raw(raw)

            result_data = json.loads(raw)

            if result_data.get("validation_result") != "PASS":
                print(
                    f"INVALID en plan {plan.plan_id}. "
                    f"Reintento {attempt + 2}/{max_retries}..."
                )
                continue

            # ---------------------------------------------------------
            # El validador es la única fuente de verdad: devuelve
            # selected_version y selected_payload en el mismo JSON.
            # ---------------------------------------------------------
            selected_version = result_data.get("selected_version") or 1
            payload = result_data.get("selected_payload") or ""

            if not payload:
                print(
                    f"[crew] validador PASS pero sin selected_payload. "
                    f"Claves disponibles: {list(result_data.keys())}",
                    flush=True,
                )
                continue

            # Validación defensiva: el payload debe ser XML bien formado
            # (solo cuando el formato es netconf_xml)
            if plan.artifact_format.value == "netconf_xml":
                import xml.etree.ElementTree as ET
                try:
                    ET.fromstring(payload)
                except ET.ParseError as e:
                    print(
                        f"[crew] selected_payload no es XML válido: {e}. "
                        f"Primeros 200 chars: {payload[:200]}",
                        flush=True,
                    )
                    continue

            # Guardar 1 sola vez, con el attempt_count del intento exitoso
            await save_command_result(
                command_id=command_id,
                atomic_task_id=event.atomic_task_id,
                logical_task_id=event.logical_task_id,
                policy_id=event.policy_id,
                intent_id=event.intent_id,
                execution_plan_id=plan.plan_id,
                vendor=event.vendor,
                platform=event.platform,
                format=plan.artifact_format.value,
                command_payload=payload,
                status="SENT",
                attempt_count=attempt + 1,
            )

            # 1 COMMAND_SENT por plan exitoso
            await kafka_producer.send_command_sent(CommandSentEvent(
                command_id=str(command_id),
                atomic_task_id=str(event.atomic_task_id),
                logical_task_id=str(event.logical_task_id),
                policy_id=str(event.policy_id),
                intent_id=str(event.intent_id),
                vendor=event.vendor,
                platform=event.platform,
                format=plan.artifact_format.value,
                command_payload=payload,
                plan_id=plan.plan_id,
                artifact_format=plan.artifact_format.value,
                protocol=plan.protocol.value,
                executor=plan.executor.value,
                device_ids=plan.device_ids,
                validation_result=result_data["validation_result"],
                selected_version=selected_version,
                equivalence_score=result_data.get("equivalence_score", 0.0),
                rollback_steps=event.atomic_task_json.get("rollback_steps"),
            ))
            print(f"COMMAND_SENT publicado para command_id: {command_id}")
            return True

        except json.JSONDecodeError as e:
            print(f"Error parseando JSON en intento {attempt + 1}: {e}", flush=True)
        except Exception as e:
            print(
                f"Error en intento {attempt + 1}: {type(e).__name__}: {e}",
                flush=True,
            )
            traceback.print_exc()

    # La cohorte falló tras todos los intentos
    await _publish_fault(
        event,
        reason="GENERATION_FAILED",
        detail=f"plan {plan.plan_id} fallo tras {max_retries} intentos",
        plan_id=plan.plan_id,
        device_ids=plan.device_ids,
        attempts_made=max_retries,
    )
    return False


async def process_event(event: AtomicTaskProposedEvent):
    """
    Decide el plan de ejecución y procesa cada cohorte de dispositivos.

    Args:
        event: Evento ATOMIC_TASK_PROPOSED validado con Pydantic.

    Returns:
        Lista de resultados, uno por plan (None si la cohorte falló).
    """
    from ms_ob02.db.database import save_execution_plan
    from ms_ob02.execution.decision_engine import decide
    from ms_ob02.execution.decision_models import ExecutionPlanUnavailableError

    # ① Decidir el plan de ejecución
    try:
        plans = await decide(event)
    except ExecutionPlanUnavailableError as e:
        print(f"PLAN NO DISPONIBLE: {e.reason}")
        await _publish_fault(
            event,
            reason="EXECUTION_PLAN_UNAVAILABLE",
            detail=e.reason,
        )
        return []

    print(f"Planes generados: {len(plans)}")
    for plan in plans:
        print(
            f"  - plan {plan.plan_id}: formato={plan.artifact_format.value} "
            f"protocolo={plan.protocol.value} ejecutor={plan.executor.value} "
            f"dispositivos={len(plan.device_ids)}"
        )

    # ② Persistir los planes
    for plan in plans:
        await save_execution_plan(plan, event.atomic_task_id)

    # ③ Procesar cada cohorte
    results = []
    for plan in plans:
        results.append(await _process_plan(event, plan))

    return results


async def consume_atomic_tasks():
    """
    Consumidor que escucha el topic de tareas atómicas propuestas.
    Valida los eventos recibidos usando Pydantic.
    """
    from ms_ob02.kafka.producer import kafka_producer

    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_ATOMIC_TASK_PROPOSED,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        client_id=settings.KAFKA_CLIENT_ID,
        enable_auto_commit=False,
        # El crew de CrewAI puede tardar varios minutos. Con los defaults
        # de Kafka (max_poll_interval_ms=300000), el consumer es expulsado
        # del grupo y el mensaje se reentrega, generando un plan y un crew
        # duplicados. 30 minutos cubren holgadamente los 3 reintentos.
        max_poll_interval_ms=1_800_000,   # 30 minutos
        session_timeout_ms=60_000,        # 1 minuto
        heartbeat_interval_ms=10_000,     # 10 segundos
    )

    await kafka_producer.start()

    await consumer.start()
    print(f"Consumidor iniciado en topic: {settings.KAFKA_TOPIC_ATOMIC_TASK_PROPOSED}")

    try:
        async for msg in consumer:
            try:
                message_data = json.loads(msg.value.decode("utf-8"))
                event = AtomicTaskProposedEvent(**message_data)

                print(f"Evento válido recibido: {event.atomic_task_id}")
                print(f"Vendor: {event.vendor}")
                print(f"Platform: {event.platform}")
                print(f"Format: {event.format}")

                await process_event(event)

                await consumer.commit()

            except Exception as e:
                print(f"Error procesando mensaje: {type(e).__name__}: {e}")
                traceback.print_exc()

    finally:
        await consumer.stop()
        await kafka_producer.stop()
        print("Consumidor detenido")


def run_consumer():
    """Punto de entrada para ejecutar el consumidor."""
    asyncio.run(consume_atomic_tasks())


if __name__ == "__main__":
    run_consumer()