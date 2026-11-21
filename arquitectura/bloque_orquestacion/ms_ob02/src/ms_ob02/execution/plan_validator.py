"""
Validación de invariantes del ExecutionPlan.

Un plan es válido si:
- El ejecutor implementa el protocolo del plan.
- Todos los dispositivos soportan las capacidades requeridas por el formato.
- La estrategia de rollback es coherente con el formato y las capacidades.
- El flag de aprobación es coherente con el nivel de riesgo.
"""

from uuid import UUID

from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    ExecutionPlan,
    Executor,
    Protocol,
    RollbackStrategy,
)


# =====================================================
# TABLAS DE COHERENCIA
# =====================================================

# Capacidades que el dispositivo debe soportar para cada formato.
REQUIRED_CAPABILITIES: dict[ArtifactFormat, tuple[str, ...]] = {
    ArtifactFormat.CLI: ("cli", "ssh"),
    ArtifactFormat.NETCONF_XML: ("netconf", "candidate_config"),
    ArtifactFormat.RESTCONF_JSON: ("restconf",),
    ArtifactFormat.ANSIBLE_YAML: ("ansible",),
}

# Protocolos que cada ejecutor puede implementar.
EXECUTOR_PROTOCOLS: dict[Executor, tuple[Protocol, ...]] = {
    Executor.NETMIKO: (Protocol.SSH_CLI,),
    Executor.NCCLIENT: (Protocol.NETCONF,),
    Executor.HTTPX: (Protocol.RESTCONF,),
    Executor.ANSIBLE_RUNNER: (Protocol.VARIABLE,),
    Executor.NAPALM: (Protocol.SSH_CLI, Protocol.NETCONF),
}

# Formatos que exigen un rollback transaccional.
FORMATS_REQUIRING_TRANSACTIONAL_ROLLBACK: frozenset[ArtifactFormat] = frozenset({
    ArtifactFormat.NETCONF_XML,
})


# =====================================================
# VALIDACIÓN
# =====================================================

def is_executor_compatible_with_protocol(
    executor: Executor,
    protocol: Protocol,
) -> bool:
    """
    Verifica si un ejecutor puede implementar un protocolo.

    Args:
        executor: Ejecutor del plan.
        protocol: Protocolo del plan.

    Returns:
        True si son compatibles.
    """
    return protocol in EXECUTOR_PROTOCOLS.get(executor, ())


def validate_plan(
    plan: ExecutionPlan,
    device_capabilities: dict[UUID, dict],
    risk_level: str = "medium",
) -> list[str]:
    """
    Verifica las invariantes de un plan de ejecución.

    Args:
        plan: Plan a validar.
        device_capabilities: Capacidades por device_id.
        risk_level: Nivel de riesgo de la tarea ("low".."critical").

    Returns:
        Lista de errores. Vacía significa plan válido.
    """
    errors: list[str] = []

    # 1. El ejecutor debe implementar el protocolo
    if not is_executor_compatible_with_protocol(plan.executor, plan.protocol):
        supported = ", ".join(p.value for p in EXECUTOR_PROTOCOLS.get(plan.executor, ()))
        errors.append(
            f"el ejecutor '{plan.executor.value}' no implementa el protocolo "
            f"'{plan.protocol.value}' (protocolos soportados: {supported or 'ninguno'})"
        )

    # 2. Todos los dispositivos deben soportar las capacidades del formato
    required = REQUIRED_CAPABILITIES.get(plan.artifact_format, ())
    for device_id in plan.device_ids:
        capabilities = device_capabilities.get(device_id)
        if capabilities is None:
            errors.append(f"dispositivo {device_id} sin capacidades registradas")
            continue
        for capability in required:
            if not capabilities.get(capability, False):
                errors.append(
                    f"dispositivo {device_id} no soporta la capacidad "
                    f"'{capability}' requerida por '{plan.artifact_format.value}'"
                )

    # 3. La estrategia de rollback debe ser coherente con el formato
    if plan.artifact_format in FORMATS_REQUIRING_TRANSACTIONAL_ROLLBACK:
        if plan.rollback_strategy not in (
            RollbackStrategy.CONFIRMED_COMMIT,
            RollbackStrategy.CANDIDATE_DISCARD,
        ):
            errors.append(
                f"el formato '{plan.artifact_format.value}' requiere rollback "
                f"transaccional, pero la estrategia es "
                f"'{plan.rollback_strategy.value}'"
            )

    # 4. Los planes con rollback transaccional requieren capacidades extra
    if plan.rollback_strategy == RollbackStrategy.CONFIRMED_COMMIT:
        for device_id in plan.device_ids:
            capabilities = device_capabilities.get(device_id) or {}
            if not capabilities.get("confirmed_commit", False):
                errors.append(
                    f"dispositivo {device_id} no soporta 'confirmed_commit' "
                    f"requerido por la estrategia de rollback"
                )

    # 5. El flag de aprobación debe ser coherente con el riesgo
    if risk_level == "critical" and not plan.requires_approval:
        errors.append("las tareas de riesgo 'critical' requieren aprobación")

    return errors
