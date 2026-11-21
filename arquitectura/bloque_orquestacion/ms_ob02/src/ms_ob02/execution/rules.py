"""
Motor de reglas determinista para decisión de ejecución.

Funciones puras que:
1. Filtran candidatos por capacidades del dispositivo
2. Seleccionan protocolo y ejecutor según el formato
3. Determinan estrategia de rollback

No usa LLM. Toda decisión es auditable vía decision_trace.
"""

from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    Protocol,
    Executor,
    RollbackStrategy,
    OperationKind,
    DeviceScope,
    TaskCharacteristics,
)
from ms_ob02.kafka.schemas import AtomicTaskProposedEvent


# =====================================================
# MAPEO DETERMINISTA: formato → protocolo + ejecutor + rollback
# =====================================================

_FORMAT_MAP: dict[ArtifactFormat, dict] = {
    ArtifactFormat.CLI: {
        "protocol": Protocol.SSH_CLI,
        "executor": Executor.NETMIKO,
        "rollback": RollbackStrategy.COMPENSATION_COMMANDS,
    },
    ArtifactFormat.NETCONF_XML: {
        "protocol": Protocol.NETCONF,
        "executor": Executor.NCCLIENT,
        "rollback": RollbackStrategy.CONFIRMED_COMMIT,
    },
    ArtifactFormat.RESTCONF_JSON: {
        "protocol": Protocol.RESTCONF,
        "executor": Executor.HTTPX,
        "rollback": RollbackStrategy.CONFIG_BACKUP,
    },
    ArtifactFormat.ANSIBLE_YAML: {
        "protocol": Protocol.VARIABLE,
        "executor": Executor.ANSIBLE_RUNNER,
        "rollback": RollbackStrategy.ANSIBLE_BLOCK_RESCUE,
    },
}


# =====================================================
# FILTROS OBLIGATORIOS
# =====================================================

def filter_by_capability(
    device_capabilities: dict,
    required_format: ArtifactFormat,
) -> str | None:
    """
    Verifica si el dispositivo soporta el formato solicitado.

    Args:
        device_capabilities: Capacidades del dispositivo desde BD.
        required_format: Formato requerido por el evento.

    Returns:
        None si el dispositivo es válido, o string con motivo de rechazo.
    """
    caps = device_capabilities

    if not caps.get("active", False):
        return "dispositivo inactivo"

    # Verificar soporte del formato
    if required_format == ArtifactFormat.CLI:
        if not caps.get("cli", False):
            return "cli no soportado"
        if not caps.get("ssh", False):
            return "ssh no soportado"

    elif required_format == ArtifactFormat.NETCONF_XML:
        if not caps.get("netconf", False):
            return "netconf no soportado"
        if not caps.get("candidate_config", False):
            return "candidate_config no soportado"

    elif required_format == ArtifactFormat.RESTCONF_JSON:
        if not caps.get("restconf", False):
            return "restconf no soportado"

    elif required_format == ArtifactFormat.ANSIBLE_YAML:
        if not caps.get("ansible", False):
            return "ansible no soportado"

    return None


# =====================================================
# SELECCIÓN DE PROTOCOLO + EJECUTOR + ROLLBACK
# =====================================================

def select_protocol_executor(
    artifact_format: ArtifactFormat,
    device_capabilities: dict,
    executor_preference: str = "AUTO",
) -> tuple[Protocol, Executor, RollbackStrategy]:
    """
    Selecciona protocolo, ejecutor y rollback según el formato.

    Args:
        artifact_format: Formato del artefacto.
        device_capabilities: Capacidades del dispositivo.
        executor_preference: Preferencia del orquestador.

    Returns:
        Tupla (protocol, executor, rollback_strategy).
    """
    config = _FORMAT_MAP[artifact_format]

    protocol = config["protocol"]
    executor = config["executor"]
    rollback = config["rollback"]

    # Si hay preferencia de ejecutor y es compatible, usarla
    if executor_preference and executor_preference != "AUTO":
        # Verificar compatibilidad
        compatible_executors = _get_compatible_executors(protocol, artifact_format)
        if executor_preference in compatible_executors:
            executor = Executor(executor_preference)

    # Verificar que el dispositivo soporta el rollback requerido
    if rollback == RollbackStrategy.CONFIRMED_COMMIT:
        if not device_capabilities.get("confirmed_commit", False):
            rollback = RollbackStrategy.UNSUPPORTED
    elif rollback == RollbackStrategy.CANDIDATE_DISCARD:
        if not device_capabilities.get("candidate_config", False):
            rollback = RollbackStrategy.UNSUPPORTED

    return protocol, executor, rollback


def _get_compatible_executors(
    protocol: Protocol,
    artifact_format: ArtifactFormat,
) -> list[str]:
    """Devuelve ejecutores compatibles con un formato/protocolo."""
    compatible = {
        ArtifactFormat.CLI: [Executor.NETMIKO, Executor.NAPALM],
        ArtifactFormat.NETCONF_XML: [Executor.NCCLIENT, Executor.NAPALM],
        ArtifactFormat.RESTCONF_JSON: [Executor.HTTPX],
        ArtifactFormat.ANSIBLE_YAML: [Executor.ANSIBLE_RUNNER],
    }
    return [e.value for e in compatible.get(artifact_format, [])]


# =====================================================
# DERIVAR CARACTERÍSTICAS DE LA TAREA
# =====================================================

# Patrones de operación → OperationKind.
# El orden importa: se evalúan de arriba hacia abajo y gana la primera
# coincidencia. Las operaciones de rollback y seguridad tienen prioridad
# sobre configuración y topología.
_OPERATION_KIND_PATTERNS: list[tuple[OperationKind, tuple[str, ...]]] = [
    (
        OperationKind.ROLLBACK,
        ("undo_", "no_", "remove_", "delete_", "rollback"),
    ),
    (
        OperationKind.SECURITY,
        ("acl", "user_", "privilege", "password", "aaa", "firewall", "key"),
    ),
    (
        OperationKind.SOFTWARE,
        ("software", "firmware", "image", "upgrade", "boot", "install"),
    ),
    (
        OperationKind.TOPOLOGY,
        ("bgp", "ospf", "isis", "interface_create", "routing", "vrf", "peer", "neighbor"),
    ),
    (
        OperationKind.READ,
        ("show", "get", "read", "display", "monitor", "verify", "check"),
    ),
    (
        OperationKind.CONFIGURATION,
        ("create", "config", "assign", "enable", "apply", "set_", "activate"),
    ),
]


def _classify_operation(operation: str) -> OperationKind:
    """
    Clasifica una operación individual según su nombre.

    Args:
        operation: Nombre de la operación (ej. "vlan_create", "no_vlan").

    Returns:
        OperationKind correspondiente.
    """
    normalized = operation.strip().lower()

    for kind, patterns in _OPERATION_KIND_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            return kind

    return OperationKind.CONFIGURATION


def derive_task_characteristics(event: AtomicTaskProposedEvent) -> TaskCharacteristics:
    """
    Deriva las características de la tarea desde el evento.

    Args:
        event: Evento ATOMIC_TASK_PROPOSED validado.

    Returns:
        TaskCharacteristics.
    """
    # Mapear criticality → risk_level
    criticality_map = {
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "CRITICAL": "critical",
    }
    risk_level = criticality_map.get(event.criticality.value, "medium")

    # Clasificar la tarea a partir de las operaciones de cada step
    atomic_task = event.atomic_task_json or {}
    steps = atomic_task.get("steps", []) or []

    if not steps:
        operation_kind = OperationKind.READ
    else:
        kinds = {
            _classify_operation(str(step.get("operation", "")))
            for step in steps
            if isinstance(step, dict)
        }
        # Precedencia: la más restrictiva gana
        for candidate in (
            OperationKind.SECURITY,
            OperationKind.SOFTWARE,
            OperationKind.ROLLBACK,
            OperationKind.TOPOLOGY,
            OperationKind.CONFIGURATION,
            OperationKind.READ,
        ):
            if candidate in kinds:
                operation_kind = candidate
                break
        else:
            operation_kind = OperationKind.CONFIGURATION

    # Derivar reversibilidad
    rollback_steps = atomic_task.get("rollback_steps") or []
    reversible = bool(rollback_steps)

    # Derivar device_scope
    targets = event.device_targets or []
    device_scope = DeviceScope.MULTIPLE if len(targets) > 1 else DeviceScope.SINGLE

    return TaskCharacteristics(
        operation_kind=operation_kind,
        risk_level=risk_level,
        reversible=reversible,
        requires_atomicity=reversible,
        requires_rollback=reversible,
        device_scope=device_scope,
        requires_confirmation=(risk_level == "critical"),
    )


# =====================================================
# ROLLBACK POR DEFECTO
# =====================================================

def determine_rollback_strategy(
    artifact_format: ArtifactFormat,
    device_capabilities: dict,
) -> RollbackStrategy:
    """
    Determina la estrategia de rollback según formato y capacidades.

    Args:
        artifact_format: Formato del artefacto.
        device_capabilities: Capacidades del dispositivo.

    Returns:
        RollbackStrategy.
    """
    if artifact_format == ArtifactFormat.NETCONF_XML:
        if device_capabilities.get("confirmed_commit", False):
            return RollbackStrategy.CONFIRMED_COMMIT
        if device_capabilities.get("candidate_config", False):
            return RollbackStrategy.CANDIDATE_DISCARD
        return RollbackStrategy.UNSUPPORTED

    elif artifact_format == ArtifactFormat.CLI:
        if device_capabilities.get("config_backup", False):
            return RollbackStrategy.CONFIG_BACKUP
        return RollbackStrategy.COMPENSATION_COMMANDS

    elif artifact_format == ArtifactFormat.ANSIBLE_YAML:
        if device_capabilities.get("ansible_block_rescue", False):
            return RollbackStrategy.ANSIBLE_BLOCK_RESCUE
        return RollbackStrategy.UNSUPPORTED

    elif artifact_format == ArtifactFormat.RESTCONF_JSON:
        if device_capabilities.get("config_backup", False):
            return RollbackStrategy.CONFIG_BACKUP
        return RollbackStrategy.UNSUPPORTED

    return RollbackStrategy.UNSUPPORTED
