"""
Modelos Pydantic para validación de eventos Kafka.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


# =====================================================
# Enums
# =====================================================

class Criticality(str, Enum):
    """Nivel de criticidad de la tarea."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExecutorPreference(str, Enum):
    """Preferencia del orquestador sobre el ejecutor."""
    AUTO = "AUTO"
    NETMIKO = "NETMIKO"
    NCCLIENT = "NCCLIENT"
    HTTPX = "HTTPX"
    ANSIBLE_RUNNER = "ANSIBLE_RUNNER"
    NAPALM = "NAPALM"



# =====================================================
# Modelos auxiliares
# =====================================================

class RequiredCapabilities(BaseModel):
    """Capacidades requeridas del dispositivo."""
    supports_qos: bool = False
    supports_netconf: bool = False
    supports_restconf: bool = False
    supports_ansible: bool = False
    supports_rollback: bool = False


class AtomicTaskJson(BaseModel):
    """Estructura del atomic_task_json."""
    vendor: str
    platform: str
    device_targets: List[str]
    steps: List[Dict[str, Any]]
    rollback_steps: List[Dict[str, Any]]


# =====================================================
# Modelo principal del evento
# =====================================================

class AtomicTaskProposedEvent(BaseModel):
    """Evento ATOMIC_TASK_PROPOSED recibido por Kafka."""

    # ---------- Trazabilidad ----------
    atomic_task_id: UUID
    logical_task_id: UUID
    policy_id: UUID
    intent_id: UUID

    # ---------- Datos del dispositivo objetivo ----------
    vendor: str = Field(description="Fabricante: cisco, huawei, juniper...")
    platform: str = Field(description="Plataforma: IOS-XE, VRP, JunOS...")
    os_version: Optional[str] = Field(
        default=None,
        description="Versión de OS: 17.18.4, V200R023C00..."
    )
    device_targets: List[str] = Field(
        description="Lista de hostnames o device_id de los dispositivos objetivo, EJ: Router core 01"
    )

    # ---------- Preferencias del motor de decisión ----------
    executor_preference: ExecutorPreference = Field(
        default=ExecutorPreference.AUTO,
        description="Preferencia del orquestador sobre el ejecutor"
    )

    format: str = Field(
        description="Formato del comando: cli, netconf_xml, restconf_json, ansible_yaml"
    )

    format_preference: Optional[str] = Field(
        default=None,
        description="Formato alternativo permitido si el primario no es viable"
    )

    # ---------- Restricciones y requisitos ----------
    required_capabilities: Optional[RequiredCapabilities] = None

    criticality: Criticality = Field(
        default=Criticality.MEDIUM,
        description="Cuan critica es la tarea: low si es solo una consulta, "
                    "Medium para configuracion menor, high para configuracion "
                    "que requiera rollback y critical para configuracion multidispositivo"
    )

    # ---------- Tarea atómica completa ----------
    atomic_task_json: Dict[str, Any] = Field(
        description="Contenido completo de la tarea atómica: steps, rollback_steps"
    )

    # ---------- Control de reintentos ----------
    version: int = Field(default=1, ge=1, le=3)
    attempt_count: int = Field(default=1, ge=1, le=3)
    max_attempts: int = Field(default=3, ge=1, le=5)

    # ---------- Metadatos ----------
    generated_by: str = Field(default="AGENT_AI6")
    metadata: Optional[Dict[str, Any]] = None


class CommandExecutionCompletedEvent(BaseModel):
    """Evento COMMAND_EXECUTION_COMPLETED: comando ejecutado con éxito."""
    command_id: UUID
    atomic_task_id: UUID
    logical_task_id: UUID
    plan_id: Optional[UUID] = None
    device_id: UUID
    hostname: str
    attempt_number: int
    ack_status: str = "SUCCESS"
    response: Optional[str] = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_by: str = "AGENT_AI6"


class CommandExecutionFailedEvent(BaseModel):
    """Evento COMMAND_EXECUTION_FAILED: la ejecución del comando falló."""
    command_id: UUID
    atomic_task_id: UUID
    logical_task_id: UUID
    plan_id: Optional[UUID] = None
    device_id: UUID
    hostname: str
    attempt_number: int
    ack_status: str = "ERROR"
    error: Optional[str] = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_by: str = "AGENT_AI6"


class CommandSentEvent(BaseModel):
    """Evento COMMAND_SENT publicado en Kafka."""

    # ---------- Trazabilidad ----------
    command_id: UUID
    atomic_task_id: UUID
    logical_task_id: UUID
    policy_id: UUID
    intent_id: UUID

    # ---------- Datos del comando ----------
    vendor: str
    platform: str
    format: str
    command_payload: str  # Solo el comando seleccionado

    # ---------- Plan de ejecución ----------
    plan_id: Optional[UUID] = None
    artifact_format: Optional[str] = None
    protocol: Optional[str] = None
    executor: Optional[str] = None
    device_ids: Optional[List[UUID]] = None

    # ---------- Validación ----------
    validation_result: str  # "PASS"
    selected_version: int
    equivalence_score: float

    # ---------- Rollback ----------
    rollback_steps: Optional[List[Dict[str, Any]]] = None  # Puede ser null en consultas

    # ---------- Metadatos ----------
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "AGENT_AI6"


class AtomicTaskFaultEvent(BaseModel):
    """Evento ATOMIC_TASK_FAULT publicado en Kafka cuando se agotan los reintentos."""

    # ---------- Trazabilidad ----------
    atomic_task_id: UUID
    logical_task_id: UUID
    policy_id: UUID
    intent_id: UUID

    # ---------- Datos del comando ----------
    vendor: str
    platform: str
    format: str

    # ---------- Plan de ejecución ----------
    plan_id: Optional[UUID] = None
    device_ids: Optional[List[UUID]] = None

    # ---------- Error ----------
    error_reason: str  # "MAX_RETRIES_EXCEEDED" | "EXECUTION_PLAN_UNAVAILABLE"
    attempts_made: int  # Número de intentos realizados
    last_validation_result: str  # "INVALID"

    # ---------- Metadatos ----------
    fault_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "AGENT_AI6"
