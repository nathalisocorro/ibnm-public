"""Coordinador del ciclo de vida de tareas lógicas."""

from uuid import UUID, uuid4

from ms_pb02.config.settings import settings
from ms_pb02.db.database import (
    append_registry,
    create_logical_task,
    find_task_context,
    get_logical_task_try,
    save_validation_layers,
    update_logical_task,
)
from ms_pb02.flows.main_flow import LogicalTaskFlow, LogicalTaskFlowState
from ms_pb02.kafka.producer import kafka_producer
from ms_pb02.kafka.schemas import (
    LogicalTaskFaultEvent,
    LogicalTaskProposedEvent,
    PolicyFaultEvent,
    PolicyProposedEvent,
)

async def _publish_policy_fault(
    *,
    policy_id: UUID,
    intent_id: UUID,
    task_id: UUID,
    try_number: int,
    reason: str,
) -> None:
    await kafka_producer.send_policy_fault(
        PolicyFaultEvent(
            event_id=uuid4(),
            policy_id=policy_id,
            intent_id=intent_id,
            task_id=task_id,
            try_number=min(try_number, settings.MAX_REGENERATION_TRIES),
            reason=reason,
        )
    )

async def process_policy(
    event: PolicyProposedEvent,
    *,
    existing_task_id: UUID | None = None,
    logical_try: int = 1,
) -> None:
    """Genera como máximo tres versiones para una tarea lógica.
     logical_try es el contador propio de MS-PB02,
    independiente del ``try_number`` del evento POLICY_PROPOSED (que pertenece
    al bloque de planificación superior y aquí no se usa).
    """
    if existing_task_id is None:
        task_id = await create_logical_task(event.policy_id, event.intent_id)
    else:
        task_id = existing_task_id

    await append_registry(
        task_id,
        "PROPOSED",
        {
            "policy_id": str(event.policy_id),
            "intent_id": str(event.intent_id),
            "logical_try": logical_try,
        },
    )
    last_reason = "No se generó una tarea válida."

    for version in range(1, settings.MAX_GENERATION_VERSIONS + 1):
        await update_logical_task(task_id, status="PROPOSED", version=version)
        try:
            state = LogicalTaskFlowState(
                task_id=str(task_id),
                policy_id=str(event.policy_id),
                intent_id=str(event.intent_id),
                policy_json=event.policy_json,
                version=version,
            )
            flow = LogicalTaskFlow()
            result = await flow.kickoff_async(inputs=state.model_dump())
            if not isinstance(result, dict):
                raise ValueError("El Flow no devolvió un resultado estructurado.")

            layers = result["validation_layers"]
            await save_validation_layers(task_id, layers)
            snapshot = {"version": version, "logical_try": logical_try, **result}

            if result["validation_result"] != "VALIDATED":
                last_reason = "La validación de cinco capas no fue satisfactoria."
                await append_registry(task_id, "FAILED", {**snapshot, "reason": last_reason})
                continue

            task_json = result["logical_task_json"]
            description = result["task_description"] or "Tarea lógica generada"
            await update_logical_task(
                task_id,
                status="VALIDATED",
                task_json=task_json,
                task_description=description[:500],
            )
            await append_registry(task_id, "VALIDATED", snapshot)
            await kafka_producer.send_logical_task_proposed(
                LogicalTaskProposedEvent(
                    event_id=uuid4(),
                    task_id=task_id,
                    policy_id=event.policy_id,
                    intent_id=event.intent_id,
                    user_id=event.user_id,
                    priority_level=event.priority_level,
                    scope_level=event.scope_level,
                    version=version,
                    try_number=logical_try,   # <-- Option A: try propio de MS-PB02
                    task_description=description,
                    task_json=task_json,
                    validation_layers=layers,
                )
            )
            await update_logical_task(task_id, status="SENT")
            await append_registry(
                task_id, "SENT",
                {"version": version, "logical_try": logical_try, "task_json": task_json},
            )
            return
        except Exception as exc:
            last_reason = f"Versión {version}: {type(exc).__name__}: {exc}"
            await append_registry(task_id, "FAILED", {"version": version, "reason": last_reason})

    await update_logical_task(task_id, status="FAILED")
    await append_registry(task_id, "FAILED", {"reason": last_reason})
    await _publish_policy_fault(
        policy_id=event.policy_id,
        intent_id=event.intent_id,
        task_id=task_id,
        try_number=logical_try,
        reason=last_reason,
    )

async def process_logical_task_fault(event: LogicalTaskFaultEvent) -> None:
    """Regenera la tarea lógica usando el contador 'try' propio de MS-PB02.

    Option A: ``event.try_number`` pertenece a MS-OB01 y se ignora aquí.
    MS-PB02 consulta su propio contador en ``logical_tasks.try``.
    """
    context = await find_task_context(event.logical_task_id)
    if context is None:
        raise ValueError(f"No existe logical_task {event.logical_task_id}.")

    current_try = await get_logical_task_try(event.logical_task_id)

    if current_try >= settings.MAX_REGENERATION_TRIES:
        await update_logical_task(event.logical_task_id, status="CANCELLED")
        await _publish_policy_fault(
            policy_id=context["policy_id"],
            intent_id=context["intent_id"],
            task_id=event.logical_task_id,
            try_number=current_try,
            reason="LOGICAL_TASK_FAULT agotó los reintentos de MS-PB02.",
        )
        return

    next_try = await increment_logical_task_try(event.logical_task_id)

    # Reutilizamos el mismo task_id (Option A: el contador vive en su fila).
    # El payload del POLICY_PROPOSED que fabricamos aquí es sólo un carrier:
    # su try_number no se usa; el try efectivo es `next_try`.
    policy_event = PolicyProposedEvent(
        policy_id=context["policy_id"],
        intent_id=context["intent_id"],
        policy_json=context["policy_json"],
        try_number=1,
    )
    await process_policy(
        policy_event,
        existing_task_id=event.logical_task_id,
        logical_try=next_try,
    )