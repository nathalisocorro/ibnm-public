"""Gestor MS-O01 del ciclo de vida de tareas atomicas."""

from uuid import UUID, uuid4

from ms_ob01.config.settings import settings
from ms_ob01.crews.atomic_task_crew import generate_atomic_task, validate_atomic_task
from ms_ob01.db.database import (
    append_registry,
    create_atomic_task,
    get_logical_task_json,
    get_atomic_task_attempt_count,
    increment_atomic_task_try,
    update_atomic_task,
)
from ms_ob01.kafka.producer import kafka_producer
from ms_ob01.ssot.client import get_device_context
from ms_ob01.kafka.schemas import (
    AtomicTaskProposedEvent,
    AtomicTaskFaultEvent,
    LogicalTaskFaultEvent,
    LogicalTaskProposedEvent,
)

from ms_ob01.kafka.schemas import CommandFormat

_FORMAT_VALUES = {f.value for f in CommandFormat}


def _logical_device_targets(logical_task: dict) -> list[str]:
    """Obtiene objetivos expl\u00edcitos; no infiere dispositivos desde texto libre."""
    targets = logical_task.get("device_targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("La tarea l\u00f3gica debe incluir device_targets no vac\u00edo.")
    if any(not isinstance(target, str) or not target.strip() for target in targets):
        raise ValueError("device_targets contiene un identificador inv\u00e1lido.")
    return [target.strip() for target in targets]


async def _load_ssot_context(logical_task: dict) -> tuple[dict, list[dict]]:
    """Carga datos autoritativos y rechaza objetivos heterog\u00e9neos."""
    contexts = [await get_device_context(target) for target in _logical_device_targets(logical_task)]
    devices = [context["device"] for context in contexts]
    fingerprints = {
        (
            str(device["vendor"]).strip().lower(),
            str(device["platform"]).strip().lower(),
            str(device["os_version"]).strip().lower(),
        )
        for device in devices
    }
    if len(fingerprints) != 1:
        raise ValueError(
            "Una tarea at\u00f3mica no puede agrupar dispositivos con "
            "vendor, platform u os_version diferentes."
        )
    metadata = {
        "vendor": str(devices[0]["vendor"]).strip(),
        "platform": str(devices[0]["platform"]).strip(),
        "os_version": str(devices[0]["os_version"]).strip(),
        "device_targets": [str(device["resource_id"]).strip() for device in devices],
    }
    return metadata, contexts


def _apply_ssot_metadata(generation: dict, metadata: dict) -> None:
    """Impide que metadata generada por el LLM prevalezca sobre el SSoT."""
    atomic_task_json = generation.get("atomic_task_json")
    if not isinstance(atomic_task_json, dict):
        raise ValueError("La generaci\u00f3n no devolvi\u00f3 atomic_task_json v\u00e1lido.")
    atomic_task_json.update(metadata)


def _atomic_payload(result: dict) -> tuple[dict, str, dict]:
    """Valida y normaliza la estructura de una tarea atómica generada."""

    if not isinstance(result, dict):
        raise ValueError("La generación no devolvió un objeto JSON.")

    atomic_task_json = result.get("atomic_task_json")
    if not isinstance(atomic_task_json, dict):
        raise ValueError("La generación no devolvió atomic_task_json válido.")

    description = str(result.get("task_description") or "").strip()
    if not description:
        raise ValueError("La tarea atómica no contiene task_description.")

    capabilities = result.get("required_capabilities") or {}
    if not isinstance(capabilities, dict):
        raise ValueError("required_capabilities debe ser un objeto JSON.")

    # Los datos de fabricante, plataforma y sistema operativo deben
    # proceder del inventario/SSoT, nunca de una inferencia del agente.
    required_metadata = ("vendor", "platform", "os_version")
    for field in required_metadata:
        value = atomic_task_json.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Falta metadata obligatoria del dispositivo: {field}."
            )

        normalized = value.strip().lower()
        if normalized in {"generic", "unknown", "n/a", "none", "null"}:
            raise ValueError(
                f"Metadata no válida para {field}: {value!r}. "
                "Debe proceder del inventario real del dispositivo."
            )

        atomic_task_json[field] = value.strip()

    device_targets = atomic_task_json.get("device_targets")
    if (
        not isinstance(device_targets, list)
        or not device_targets
        or any(not isinstance(device, str) or not device.strip()
               for device in device_targets)
    ):
        raise ValueError(
            "device_targets debe ser una lista no vacía de dispositivos identificados."
        )

    atomic_task_json["device_targets"] = [
        device.strip() for device in device_targets
    ]

    steps = atomic_task_json.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("La tarea atómica debe contener al menos un step.")

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"El step {index} debe ser un objeto JSON.")
        if not str(step.get("operation") or "").strip():
            raise ValueError(f"El step {index} no contiene operation.")

    rollback_steps = atomic_task_json.get("rollback_steps", [])
    if not isinstance(rollback_steps, list):
        raise ValueError("rollback_steps debe ser una lista.")
    atomic_task_json["rollback_steps"] = rollback_steps

    # Criticality
    raw_crit = result.get("criticality")
    if raw_crit is None:
        raise ValueError("La generación no devolvió criticality.")

    crit = str(raw_crit).upper()
    allowed_criticalities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    if crit not in allowed_criticalities:
        raise ValueError(f"criticality inválido: {raw_crit!r}")

    result["criticality"] = crit

    # Formato principal
    raw_fmt = result.get("format")
    if raw_fmt is None:
        raise ValueError("La generación no devolvió format.")

    try:
        fmt = CommandFormat(str(raw_fmt).lower())
    except ValueError as exc:
        raise ValueError(f"format inválido: {raw_fmt!r}") from exc

    result["format"] = fmt.value

    # Formato alternativo opcional
    raw_alt = result.get("format_preference")
    if raw_alt is None or str(raw_alt).strip().lower() in {
        "", "none", "null"
    }:
        result["format_preference"] = None
    else:
        try:
            alt = CommandFormat(str(raw_alt).lower())
        except ValueError as exc:
            raise ValueError(
                f"format_preference inválido: {raw_alt!r}"
            ) from exc

        if alt == fmt:
            raise ValueError(
                "format_preference debe ser distinto de format."
            )

        result["format_preference"] = alt.value

    return atomic_task_json, description, capabilities

def _enforce_preferred_formats(logical_task: dict, generation: dict) -> None:
    """Comprueba que format y format_preference respetan lo que pidio el usuario."""
    preferred = logical_task.get("preferred_formats")
    if preferred is None:
        single = logical_task.get("preferred_format")
        preferred = [single] if single else []
    if not preferred:
        return

    allowed = {CommandFormat(str(p).lower()) for p in preferred if p}
    emitted = {CommandFormat(generation["format"])}
    if generation.get("format_preference"):
        emitted.add(CommandFormat(generation["format_preference"]))

    if not emitted <= allowed:
        raise ValueError(
            f"la crew emitio formatos {sorted(f.value for f in emitted)} "
            f"no solicitados en preferred_formats "
            f"{sorted(f.value for f in allowed)}"
        )

async def _publish_fault(event: LogicalTaskProposedEvent, atomic_task_id: UUID, reason: str) -> None:
    await kafka_producer.send_fault(
        LogicalTaskFaultEvent(
            event_id=uuid4(),
            atomic_task_id=atomic_task_id,
            logical_task_id=event.task_id,
            policy_id=event.policy_id,
            intent_id=event.intent_id,
            try_number=event.try_number,
            reason=reason,
        )
    )


async def process_logical_task(event: LogicalTaskProposedEvent) -> None:
    """Genera, valida y publica una tarea atomica en un maximo de tres versiones."""
    atomic_task_id = await create_atomic_task(event)
    await append_registry(
        atomic_task_id,
        "PROPOSED",
        {"logical_task_id": str(event.task_id), "policy_id": str(event.policy_id)},
    )
    last_reason = "No se genero una tarea atomica valida."
    try:
        metadata, ssot_context = await _load_ssot_context(event.task_json)
    except ValueError as exc:
        last_reason = str(exc)
        await update_atomic_task(atomic_task_id, status="FAILED")
        await append_registry(atomic_task_id, "FAILED", {"reason": last_reason})
        await _publish_fault(event, atomic_task_id, last_reason)
        return

    for version in range(1, settings.MAX_GENERATION_VERSIONS + 1):
        try:
            generation = await generate_atomic_task(
                logical_task=event.task_json,
                device_inventory=metadata,
                device_configurations=ssot_context,
                version=version,
            )
            _apply_ssot_metadata(generation, metadata)
            atomic_json, description, capabilities = _atomic_payload(generation)
            _enforce_preferred_formats(event.task_json, generation)
            validation = await validate_atomic_task(
                logical_task=event.task_json,
                atomic_task=generation,
                validation_context={"ssot": ssot_context, "metadata": metadata},
            )
            result = validation.get("validation_result", validation.get("status"))
            if result not in {"PASS", "VALIDATED"}:
                last_reason = str(validation.get("failure_detail") or "La tarea atomica no paso la validacion.")
                await append_registry(atomic_task_id, "FAILED", {"version": version, "reason": last_reason})
                continue

            await update_atomic_task(
                atomic_task_id,
                status="VALIDATED",
                task_json=atomic_json,
                task_description=description[:500],
                required_capabilities=capabilities,
                version=version,
            )
            await append_registry(
                atomic_task_id,
                "VALIDATED",
                {"version": version, "atomic_task_json": atomic_json},
            )
            await kafka_producer.send(
                AtomicTaskProposedEvent(
                    event_id=uuid4(),
                    atomic_task_id=atomic_task_id,
                    logical_task_id=event.task_id,
                    policy_id=event.policy_id,
                    intent_id=event.intent_id,
                    task_description=description,
                    atomic_task_json=atomic_json,
                    vendor=str(atomic_json["vendor"]),
                    platform=str(atomic_json["platform"]),
                    os_version=str(atomic_json["os_version"]),
                    device_targets=list(atomic_json["device_targets"]),
                    executor_preference=str(generation.get("executor_preference", "AUTO")),
                    format=str(generation["format"]),
                    format_preference=(
                        str(generation["format_preference"])
                        if generation.get("format_preference") else None
                    ),
                    criticality=str(generation.get("criticality", "MEDIUM")),
                    required_capabilities=capabilities,
                    version=version,
                    try_number=1,
                )
            )
            await update_atomic_task(atomic_task_id, status="SENT", version=version)
            await append_registry(
                atomic_task_id,
                "SENT",
                {"version": version, "atomic_task_json": atomic_json},
            )
            return
        except (ValueError, KeyError) as exc:
            last_reason = f"Version {version}: {type(exc).__name__}: {exc}"
            await append_registry(atomic_task_id, "FAILED", {"version": version, "reason": last_reason})

    await update_atomic_task(atomic_task_id, status="FAILED")
    await append_registry(atomic_task_id, "FAILED", {"reason": last_reason})
    await _publish_fault(event, atomic_task_id, last_reason)


async def process_atomic_task_fault(event: AtomicTaskFaultEvent) -> None:
    """Regenera la tarea atómica ante un fallo de comandos de MS-O04.

    ``try`` representa regeneraciones causadas por el bloque de comandos y
    tiene un máximo de tres. Si se agota, se propaga LOGICAL_TASK_FAULT a
    MS-P04 para que regenere la tarea lógica.
    """
    # attempts_made pertenece al ciclo de generación de comandos de MS-O04;
    # el contador de regeneraciones de MS-O01 vive en atomic_tasks.
    current_try = await get_atomic_task_attempt_count(event.atomic_task_id)
    next_try = min(current_try + 1, settings.MAX_REGENERATION_TRIES)
    reason = event.error_detail or event.error_reason
    await append_registry(
        event.atomic_task_id,
        # El registro es un historial de estados y su CHECK no admite nombres
        # de topics/eventos. Conservamos el evento original en el snapshot.
        "FAILED",
        {
            "event": "ATOMIC_TASK_FAULT",
            "try": next_try,
            "error_reason": event.error_reason,
            "error_detail": reason,
            "attempts_made": event.attempts_made,
        },
    )

    if current_try >= settings.MAX_REGENERATION_TRIES:
        await update_atomic_task(event.atomic_task_id, status="FAILED")
        await _publish_fault_from_atomic_fault(event, current_try, reason)
        return

    next_try = await increment_atomic_task_try(event.atomic_task_id)
    logical_task = await get_logical_task_json(event.logical_task_id)
    await update_atomic_task(event.atomic_task_id, status="PENDING")
    await _regenerate_atomic_task(
        event,
        logical_task=logical_task,
        try_number=next_try,
    )


async def _publish_fault_from_atomic_fault(
    event: AtomicTaskFaultEvent, try_number: int, reason: str
) -> None:
    await kafka_producer.send_fault(
        LogicalTaskFaultEvent(
            event_id=uuid4(),
            atomic_task_id=event.atomic_task_id,
            logical_task_id=event.logical_task_id,
            policy_id=event.policy_id,
            intent_id=event.intent_id,
            try_number=try_number,
            reason=reason,
        )
    )


async def _regenerate_atomic_task(
    event: AtomicTaskFaultEvent,
    *,
    logical_task: dict,
    try_number: int,
) -> None:
    """Genera versiones 1..3 conservando el atomic_task_id original."""
    last_reason = "No se genero una tarea atomica valida."
    try:
        metadata, ssot_context = await _load_ssot_context(logical_task)
    except ValueError as exc:
        last_reason = str(exc)
        await update_atomic_task(event.atomic_task_id, status="FAILED")
        await append_registry(event.atomic_task_id, "FAILED", {"reason": last_reason})
        await _publish_fault_from_atomic_fault(event, try_number, last_reason)
        return
    for version in range(1, settings.MAX_GENERATION_VERSIONS + 1):
        try:
            generation = await generate_atomic_task(
                logical_task=logical_task,
                device_inventory=metadata,
                device_configurations=ssot_context,
                version=version,
            )
            _apply_ssot_metadata(generation, metadata)
            atomic_json, description, capabilities = _atomic_payload(generation)
            _enforce_preferred_formats(logical_task, generation)
            validation = await validate_atomic_task(
                logical_task=logical_task,
                atomic_task=generation,
                validation_context={"ssot": ssot_context, "metadata": metadata},
            )
            result = validation.get("validation_result", validation.get("status"))
            if result not in {"PASS", "VALIDATED"}:
                last_reason = str(validation.get("failure_detail") or "La tarea atomica no paso la validacion.")
                await append_registry(event.atomic_task_id, "FAILED", {"version": version, "reason": last_reason})
                continue
            await update_atomic_task(
                event.atomic_task_id,
                status="VALIDATED",
                task_json=atomic_json,
                task_description=description[:500],
                required_capabilities=capabilities,
                version=version,
            )
            await append_registry(event.atomic_task_id, "VALIDATED", {"version": version, "try": try_number})
            await kafka_producer.send(
                AtomicTaskProposedEvent(
                    event_id=uuid4(),
                    atomic_task_id=event.atomic_task_id,
                    logical_task_id=event.logical_task_id,
                    policy_id=event.policy_id,
                    intent_id=event.intent_id,
                    task_description=description,
                    atomic_task_json=atomic_json,
                    vendor=str(atomic_json["vendor"]),
                    platform=str(atomic_json["platform"]),
                    os_version=str(atomic_json["os_version"]),
                    device_targets=list(atomic_json["device_targets"]),
                    executor_preference=str(generation.get("executor_preference", "AUTO")),
                    format=str(generation.get("format", "cli")),
                    format_preference=generation.get("format_preference"),
                    criticality=str(generation.get("criticality", "MEDIUM")),
                    required_capabilities=capabilities,
                    version=version,
                    try_number=try_number,
                )
            )
            await update_atomic_task(event.atomic_task_id, status="SENT", version=version)
            await append_registry(event.atomic_task_id, "SENT", {"version": version, "try": try_number})
            return
        except (ValueError, KeyError) as exc:
            last_reason = f"Version {version}: {type(exc).__name__}: {exc}"
            await append_registry(event.atomic_task_id, "FAILED", {"version": version, "reason": last_reason})

    await update_atomic_task(event.atomic_task_id, status="FAILED")
    await _publish_fault_from_atomic_fault(event, try_number, last_reason)
