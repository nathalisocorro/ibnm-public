"""
Modelos del motor de decisión de ejecución.

Define los enums y estructuras para representar:
- Formato del artefacto (qué se genera)
- Protocolo de transporte ( cómo se comunica)
- Ejecutor (qué componente implementa la comunicación)
- Estrategia de rollback (cómo se revierte)
- Características de la tarea (contexto para decidir)
- ExecutionPlan (resultado del motor)
"""

from pydantic import BaseModel, Field
from enum import Enum
from uuid import UUID, uuid4


# =====================================================
# ENUMS
# =====================================================

class ArtifactFormat(str, Enum):
    """Formato del artefacto a generar."""
    CLI = "cli"
    NETCONF_XML = "netconf_xml"
    RESTCONF_JSON = "restconf_json"
    ANSIBLE_YAML = "ansible_yaml"


class Protocol(str, Enum):
    """Protocolo de transporte."""
    SSH_CLI = "ssh_cli"
    NETCONF = "netconf"
    RESTCONF = "restconf"
    VARIABLE = "variable"       # ansible_yaml / python_script pueden usar cualquier transporte


class Executor(str, Enum):
    """Ejecutor que implementa la comunicación."""
    NETMIKO = "netmiko"
    NCCLIENT = "ncclient"
    HTTPX = "httpx"
    ANSIBLE_RUNNER = "ansible_runner"
    NAPALM = "napalm"


class RollbackStrategy(str, Enum):
    """Estrategia de rollback."""
    CONFIRMED_COMMIT = "confirmed-commit"
    CANDIDATE_DISCARD = "candidate-discard"
    CONFIG_BACKUP = "config-backup"
    COMPENSATION_COMMANDS = "compensation-commands"
    ANSIBLE_BLOCK_RESCUE = "ansible-block-rescue"
    UNSUPPORTED = "unsupported"


class OperationKind(str, Enum):
    """Tipo de operación."""
    READ = "read"
    CONFIGURATION = "configuration"
    SECURITY = "security"
    TOPOLOGY = "topology"
    SOFTWARE = "software"
    ROLLBACK = "rollback"


class DeviceScope(str, Enum):
    """Alcance de dispositivos."""
    SINGLE = "single"
    MULTIPLE = "multiple"


class Capability(str, Enum):
    """Capacidades que puede tener un dispositivo de red."""
    # Transporte
    CLI = "cli"
    SSH = "ssh"
    NETCONF = "netconf"
    RESTCONF = "restconf"

    # Orquestación
    ANSIBLE = "ansible"

    # Configuración transaccional
    CANDIDATE_CONFIG = "candidate_config"
    CONFIRMED_COMMIT = "confirmed_commit"

    # Rollback
    ROLLBACK = "rollback"
    CONFIG_BACKUP = "config_backup"
    ANSIBLE_BLOCK_RESCUE = "ansible_block_rescue"

    # Módulos
    YANG_MODULE = "yang_module"
    ANSIBLE_MODULE = "ansible_module"
    RESTCONF_OPERATION = "restconf_operation"


# =====================================================
# MODELOS
# =====================================================

class TaskCharacteristics(BaseModel):
    """Características de la tarea para decidir ejecución."""
    operation_kind: OperationKind
    risk_level: str  # low | medium | high | critical
    reversible: bool
    requires_atomicity: bool
    requires_rollback: bool
    device_scope: DeviceScope
    requires_confirmation: bool


class ExecutionPlan(BaseModel):
    """Plan de ejecución generado por el motor de decisión."""
    plan_id: UUID = Field(default_factory=uuid4)
    device_ids: list[UUID]
    artifact_format: ArtifactFormat
    protocol: Protocol
    executor: Executor
    rollback_strategy: RollbackStrategy
    requires_approval: bool
    fallback_used: bool
    inventory_version: int = 1
    decision_trace: list[str] = Field(default_factory=list)


# =====================================================
# EXCEPCIONES
# =====================================================

class ExecutionPlanUnavailableError(Exception):
    """
    El motor no pudo construir un plan de ejecución viable.

    Se lanza cuando:
    - Algún dispositivo objetivo no existe en el inventario.
    - Ningún dispositivo soporta el formato requerido ni su alternativa.
    - El plan resultante viola las invariantes del validador.
    """

    def __init__(self, reason: str, trace: list[str] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.trace = trace or []
