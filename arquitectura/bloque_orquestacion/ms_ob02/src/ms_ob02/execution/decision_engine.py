"""
Motor de decisión de ejecución.

Genera uno o más ExecutionPlan a partir de un evento ATOMIC_TASK_PROPOSED.

El motor es determinista: no usa LLM. Toda decisión queda registrada
en el `decision_trace` del plan.

Fases (según DISENO_IMPLEMENTACION_DECISION_EJECUCION.md):
1. Validar la tarea y los dispositivos objetivo.
2. Obtener las capacidades de cada dispositivo.
3. Dividir en cohortes según el formato requerido.
4. Evaluar y seleccionar protocolo, ejecutor y rollback por cohorte.
5. Construir el plan con su decision_trace.
6. Validar las invariantes del plan.
"""

from uuid import UUID

from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    ExecutionPlan,
    ExecutionPlanUnavailableError,
    TaskCharacteristics,
)
from ms_ob02.execution.inventory import (
    DeviceInfo,
    get_device_capabilities,
    resolve_devices_by_hostname,
)
from ms_ob02.execution.plan_validator import validate_plan
from ms_ob02.execution.rules import (
    derive_task_characteristics,
    determine_rollback_strategy,
    filter_by_capability,
    select_protocol_executor,
)
from ms_ob02.kafka.schemas import AtomicTaskProposedEvent


# =====================================================
# MOTOR
# =====================================================

async def decide(event: AtomicTaskProposedEvent) -> list[ExecutionPlan]:
    """
    Genera los planes de ejecución para un evento de tarea atómica.

    Args:
        event: Evento ATOMIC_TASK_PROPOSED validado.

    Returns:
        Lista de ExecutionPlan, uno por cohorte de dispositivos.

    Raises:
        ExecutionPlanUnavailableError: si algún dispositivo no existe en el
            inventario o si no es posible construir un plan viable.
    """
    trace: list[str] = []

    # --- Fase 1: clasificar la tarea ---
    characteristics = derive_task_characteristics(event)
    trace.append(
        f"Tarea clasificada: operation_kind={characteristics.operation_kind.value}, "
        f"risk_level={characteristics.risk_level}, "
        f"reversible={characteristics.reversible}, "
        f"device_scope={characteristics.device_scope.value}"
    )

    # --- Fase 2: resolver dispositivos ---
    devices = await resolve_devices_by_hostname(event.device_targets)
    if not devices:
        raise ExecutionPlanUnavailableError(
            "ningun dispositivo objetivo existe en el inventario",
            trace,
        )

    resolved = {device.hostname for device in devices}
    missing = [name for name in event.device_targets if name not in resolved]
    if missing:
        raise ExecutionPlanUnavailableError(
            f"dispositivos no encontrados en el inventario: {', '.join(missing)}",
            trace,
        )

    trace.append(
        f"Dispositivos resueltos: {', '.join(device.hostname for device in devices)}"
    )

    # --- Fase 3: obtener capacidades ---
    device_ids = [device.device_id for device in devices]
    capabilities = await get_device_capabilities(device_ids)
    trace.append(
        f"Capacidades cargadas para {len(capabilities)} dispositivo(s)"
    )

    # --- Fase 4: determinar formatos candidatos ---
    try:
        required_format = ArtifactFormat(event.format)
    except ValueError as exc:
        raise ExecutionPlanUnavailableError(
            f"formato '{event.format}' no soportado por el motor", trace
        ) from exc

    fallback_format: ArtifactFormat | None = None
    if event.format_preference:
        try:
            fallback_format = ArtifactFormat(event.format_preference)
        except ValueError as exc:
            raise ExecutionPlanUnavailableError(
                f"formato alternativo '{event.format_preference}' no soportado por el motor",
                trace,
            ) from exc

    # --- Fase 5: armar cohortes ---
    primary, rejected = _split_by_format(
        devices, capabilities, required_format, trace
    )

    secondary: list[DeviceInfo] = []
    if rejected:
        if fallback_format is None:
            raise ExecutionPlanUnavailableError(
                f"el formato '{required_format.value}' no es viable para "
                f"{len(rejected)} dispositivo(s) y no hay formato alternativo",
                trace,
            )
        trace.append(
            f"Formato alternativo '{fallback_format.value}' evaluado para "
            f"{len(rejected)} dispositivo(s) restante(s)"
        )
        secondary, still_rejected = _split_by_format(
            rejected, capabilities, fallback_format, trace
        )
        if still_rejected:
            raise ExecutionPlanUnavailableError(
                f"ningun formato es viable para {len(still_rejected)} dispositivo(s): "
                f"{', '.join(device.hostname for device in still_rejected)}",
                trace,
            )

    # --- Fase 6: construir un plan por cohorte ---
    plans: list[ExecutionPlan] = []

    plan = _build_plan(
        devices=primary,
        characteristics=characteristics,
        artifact_format=required_format,
        capabilities=capabilities,
        executor_preference=event.executor_preference.value,
        trace=trace,
        fallback_used=False,
    )
    plans.append(plan)

    if secondary:
        fallback_plan = _build_plan(
            devices=secondary,
            characteristics=characteristics,
            artifact_format=fallback_format,
            capabilities=capabilities,
            executor_preference=event.executor_preference.value,
            trace=trace,
            fallback_used=True,
        )
        plans.append(fallback_plan)

    # --- Fase 7: validar invariantes ---
    for plan in plans:
        errors = validate_plan(
            plan,
            capabilities,
            risk_level=characteristics.risk_level,
        )
        if errors:
            raise ExecutionPlanUnavailableError(
                f"plan invalido: {'; '.join(errors)}",
                trace,
            )

    return plans


# =====================================================
# HELPERS
# =====================================================

def _split_by_format(
    devices: list[DeviceInfo],
    capabilities: dict[UUID, dict],
    artifact_format: ArtifactFormat,
    trace: list[str],
) -> tuple[list[DeviceInfo], list[DeviceInfo]]:
    """
    Separa dispositivos en viables y rechazados para un formato.

    Args:
        devices: Dispositivos a evaluar.
        capabilities: Capacidades por device_id.
        artifact_format: Formato a evaluar.
        trace: Lista de decision_trace a ampliar.

    Returns:
        Tupla (viables, rechazados).
    """
    viable: list[DeviceInfo] = []
    rejected: list[DeviceInfo] = []

    for device in devices:
        device_caps = capabilities.get(device.device_id, {})
        reason = filter_by_capability(device_caps, artifact_format)
        if reason is None:
            viable.append(device)
        else:
            rejected.append(device)
            trace.append(
                f"Dispositivo {device.hostname} descartado para "
                f"'{artifact_format.value}': {reason}"
            )

    if viable:
        trace.append(
            f"Formato '{artifact_format.value}' viable en "
            f"{len(viable)} dispositivo(s): "
            f"{', '.join(device.hostname for device in viable)}"
        )

    return viable, rejected


def _build_plan(
    devices: list[DeviceInfo],
    characteristics: TaskCharacteristics,
    artifact_format: ArtifactFormat,
    capabilities: dict[UUID, dict],
    executor_preference: str,
    trace: list[str],
    fallback_used: bool,
) -> ExecutionPlan:
    """
    Construye el ExecutionPlan de una cohorte.

    Args:
        devices: Dispositivos de la cohorte.
        characteristics: Características de la tarea.
        artifact_format: Formato de la cohorte.
        capabilities: Capacidades por device_id.
        executor_preference: Preferencia de ejecutor del orquestador.
        trace: Lista de decision_trace a ampliar.
        fallback_used: True si la cohorte usa el formato alternativo.

    Returns:
        ExecutionPlan construido.
    """
    device_ids = [device.device_id for device in devices]

    # Capacidades comunes a toda la cohorte
    common = _intersect_capabilities(device_ids, capabilities)
    trace.append(
        f"Capacidades comunes de la cohorte: "
        f"{', '.join(sorted(common)) or 'ninguna'}"
    )

    # Protocolo y ejecutor
    protocol, executor, _ = select_protocol_executor(
        artifact_format=artifact_format,
        device_capabilities=common,
        executor_preference=executor_preference,
    )
    trace.append(f"Protocolo seleccionado: {protocol.value}")
    trace.append(f"Ejecutor seleccionado: {executor.value}")

    # Estrategia de rollback
    rollback = determine_rollback_strategy(artifact_format, common)
    trace.append(f"Estrategia de rollback: {rollback.value}")

    # Aprobación
    requires_approval = _requires_approval(characteristics, rollback)
    trace.append(f"Requiere aprobación: {requires_approval}")

    if fallback_used:
        trace.append("Se aplicó formato alternativo (fallback)")

    inventory_version = max(
        (device.inventory_version for device in devices), default=1
    )

    return ExecutionPlan(
        device_ids=device_ids,
        artifact_format=artifact_format,
        protocol=protocol,
        executor=executor,
        rollback_strategy=rollback,
        requires_approval=requires_approval,
        fallback_used=fallback_used,
        inventory_version=inventory_version,
        decision_trace=list(trace),
    )


def _intersect_capabilities(
    device_ids: list[UUID],
    capabilities: dict[UUID, dict],
) -> dict:
    """
    Calcula la intersección de capacidades de una cohorte.

    La clave 'active' se excluye del cálculo.

    Args:
        device_ids: Dispositivos de la cohorte.
        capabilities: Capacidades por device_id.

    Returns:
        Dict {capability: True} con las capacidades comunes.
    """
    if not device_ids:
        return {}

    common: set[str] | None = None
    for device_id in device_ids:
        device_caps = capabilities.get(device_id, {})
        supported = {
            name
            for name, value in device_caps.items()
            if name != "active" and value
        }
        common = supported if common is None else (common & supported)

    return {capability: True for capability in (common or set())}


def _requires_approval(
    characteristics: TaskCharacteristics,
    rollback_strategy,
) -> bool:
    """
    Determina si el plan requiere aprobación humana.

    Reglas:
    - Riesgo 'critical' siempre requiere aprobación.
    - Un plan sin rollback transaccional en formato NETCONF requiere aprobación.
    """
    if characteristics.risk_level == "critical":
        return True

    if (
        characteristics.requires_rollback
        and rollback_strategy.value == "unsupported"
    ):
        return True

    return False


def build_execution_profile(plan: ExecutionPlan) -> dict:
    """
    Construye el execution_profile que consume el Crew.

    Es el contrato entre la decisión y la generación: le indica al agente
    en qué formato exacto debe producir el comando.

    Args:
        plan: Plan de ejecución.

    Returns:
        Dict con la información del perfil de ejecución.
    """
    from ms_ob02.execution.plan_validator import REQUIRED_CAPABILITIES

    return {
        "plan_id": str(plan.plan_id),
        "requested_format": plan.artifact_format.value,
        "allowed_formats": [plan.artifact_format.value],
        "protocol": plan.protocol.value,
        "executor": plan.executor.value,
        "required_capabilities": list(
            REQUIRED_CAPABILITIES.get(plan.artifact_format, ())
        ),
        "rollback_required": plan.rollback_strategy.value != "unsupported",
    }
