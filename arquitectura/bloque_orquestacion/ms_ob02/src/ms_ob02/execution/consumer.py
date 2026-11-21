"""
Consumidor de ejecución.

Recibe eventos COMMAND_SENT y aplica el comando en los dispositivos
objetivo usando el adaptador que corresponde al formato del plan.
"""

import json
import asyncio

from aiokafka import AIOKafkaConsumer

from ms_ob02.config.settings import settings
from ms_ob02.execution.base import DeviceTarget, ExecutionStatus
from ms_ob02.execution.registry import get_adapter
from ms_ob02.kafka.schemas import CommandSentEvent


# Limita las ejecuciones simultáneas para no saturar el pool de conexiones.
_execution_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_EXECUTIONS)


def _map_command_status(execution_status: ExecutionStatus) -> str:
    """
    Traduce el resultado de ejecución al status del comando.

    Args:
        execution_status: Resultado de la ejecución.

    Returns:
        Status del comando (ACK_OK, ACK_ERROR, TIMEOUT).
    """
    if execution_status == ExecutionStatus.SUCCESS:
        return "ACK_OK"
    if execution_status == ExecutionStatus.TIMEOUT:
        return "TIMEOUT"
    return "ACK_ERROR"


async def process_command_sent(event: CommandSentEvent) -> None:
    """
    Aplica el comando en cada dispositivo del plan.

    Args:
        event: Evento COMMAND_SENT validado.
    """
    from ms_ob02.db.database import (
        count_command_executions,
        get_execution_devices,
        get_execution_plan,
        get_successful_execution,
        save_command_execution,
        update_command_status,
    )
    from ms_ob02.execution.decision_models import ExecutionPlanUnavailableError
    from ms_ob02.kafka.producer import kafka_producer
    from ms_ob02.kafka.schemas import (
        CommandExecutionCompletedEvent,
        CommandExecutionFailedEvent,
    )

    # ① Plan desde la BD: es la fuente de verdad
    plan = await get_execution_plan(event.plan_id)
    if plan is None:
        raise ExecutionPlanUnavailableError(
            f"no se encontró el plan de ejecución {event.plan_id}",
            [],
        )

    # ② Adaptador correspondiente al formato del plan
    adapter = get_adapter(plan)

    # ③ Dispositivos objetivo
    devices = await get_execution_devices(plan.device_ids)
    if not devices:
        raise ExecutionPlanUnavailableError(
            f"el plan {plan.plan_id} no tiene dispositivos resolubles",
            [],
        )

    for device_data in devices:
        device = DeviceTarget(**device_data)

        # Idempotencia: no repetir una ejecución ya exitosa
        if await get_successful_execution(event.command_id, device.device_id):
            print(
                f"Comando {event.command_id} ya ejecutado con éxito en "
                f"{device.hostname}, se omite"
            )
            continue

        # Validar compatibilidad antes de tocar el dispositivo
        await adapter.validate(plan, device)

        # ④ Ejecutar con límite de concurrencia
        async with _execution_semaphore:
            result = await adapter.apply(plan, event.command_payload, device)

        # ⑤ Persistir el resultado
        attempt_number = await count_command_executions(event.command_id) + 1
        await save_command_execution(
            command_id=event.command_id,
            attempt_number=attempt_number,
            ack_status=result.status.value,
            device_id=device.device_id,
            error_message=result.error,
            response_payload=result.response,
        )
        await update_command_status(
            event.command_id,
            _map_command_status(result.status),
        )

        # ⑥ Publicar el resultado de la ejecución
        if result.status == ExecutionStatus.SUCCESS:
            await kafka_producer.send_command_execution_completed(
                CommandExecutionCompletedEvent(
                    command_id=event.command_id,
                    atomic_task_id=event.atomic_task_id,
                    logical_task_id=event.logical_task_id,
                    plan_id=plan.plan_id,
                    device_id=device.device_id,
                    hostname=device.hostname,
                    attempt_number=attempt_number,
                    ack_status=result.status.value,
                    response=result.response,
                )
            )
            print(
                f"COMMAND_EXECUTION_COMPLETED publicado: "
                f"command_id={event.command_id} device={device.hostname}"
            )
        else:
            await kafka_producer.send_command_execution_failed(
                CommandExecutionFailedEvent(
                    command_id=event.command_id,
                    atomic_task_id=event.atomic_task_id,
                    logical_task_id=event.logical_task_id,
                    plan_id=plan.plan_id,
                    device_id=device.device_id,
                    hostname=device.hostname,
                    attempt_number=attempt_number,
                    ack_status=result.status.value,
                    error=result.error,
                )
            )
            print(
                f"COMMAND_EXECUTION_FAILED publicado: "
                f"command_id={event.command_id} device={device.hostname} "
                f"error={result.error}"
            )


async def consume_command_sent():
    """
    Consumidor del topic COMMAND_SENT.

    Aplica los comandos generados en los dispositivos objetivo.
    """
    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_COMMAND_SENT,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_EXECUTOR_GROUP_ID,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        client_id=settings.KAFKA_CLIENT_ID,
        enable_auto_commit=False,
        # Aunque la ejecución en el dispositivo es rápida (segundos),
        # mantenemos los mismos timeouts que el consumer de generación
        # para evitar expulsiones si el adaptador se cuelga en un timeout
        # de Netmiko/ncclient de 60s.
        max_poll_interval_ms=1_800_000,   # 30 minutos
        session_timeout_ms=60_000,        # 1 minuto
        heartbeat_interval_ms=10_000,     # 10 segundos
    )

    await consumer.start()
    print(
        f"Consumidor de ejecución iniciado en topic: "
        f"{settings.KAFKA_TOPIC_COMMAND_SENT}"
    )

    try:
        async for msg in consumer:
            try:
                event = CommandSentEvent(**json.loads(msg.value.decode("utf-8")))
                print(
                    f"Ejecutando comando {event.command_id} "
                    f"(formato {event.format})"
                )
                await process_command_sent(event)
                await consumer.commit()

            except Exception as e:
                print(f"Error ejecutando comando: {type(e).__name__}: {e}")
                # El fallo ya se registró en command_executions y se publicó
                # COMMAND_EXECUTION_FAILED dentro de process_command_sent.
                # Confirmamos el offset para evitar la reentrega infinita
                # del mismo mensaje (ver AGENTS.md §13, pendiente retry).
                await consumer.commit()
    finally:
        await consumer.stop()
        print("Consumidor de ejecución detenido")