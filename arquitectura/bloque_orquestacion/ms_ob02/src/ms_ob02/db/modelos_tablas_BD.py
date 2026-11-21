"""
Modelos SQLModel para la base de datos de ms_ob02.
Organizados por nivel de dependencia (FK).
"""

from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import Column, Text, Enum as SA_Enum
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from pgvector.sqlalchemy import Vector

from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    Capability,
    Executor,
    Protocol,
    RollbackStrategy,
)


# =====================================================
# ENUMS (Python)
# =====================================================

class IntentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VALIDATION = "PENDING_VALIDATION"
    SENT = "SENT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class ScopeLevel(str, Enum):
    ELEMENT = "ELEMENT"
    SUBNETWORK = "SUBNETWORK"
    NETWORK = "NETWORK"


class PolicyStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    SENT = "SENT"
    FAILED = "FAILED"


class LogicalTaskStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    SENT = "SENT"
    FAILED = "FAILED"


class DeviceType(str, Enum):
    ROUTER = "ROUTER"
    SWITCH = "SWITCH"
    FIREWALL = "FIREWALL"
    ACCESS_POINT = "ACCESS_POINT"
    IOT_GATEWAY = "IOT_GATEWAY"
    VIRTUAL_NF = "VIRTUAL_NF"
    SERVER = "SERVER"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"


class Technology(str, Enum):
    WIFI = "WIFI"
    IOT = "IOT"
    ETHERNET = "ETHERNET"
    NFV = "NFV"


class AtomicTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REGENERATING = "REGENERATING"


class RegistryEventType(str, Enum):
    PROPOSED = "PROPOSED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REGENERATING = "REGENERATING"


class CommandFormat(str, Enum):
    CLI = "cli"
    NETCONF_XML = "netconf_xml"
    RESTCONF_JSON = "restconf_json"
    ANSIBLE_YAML = "ansible_yaml"


class CommandStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACK_OK = "ACK_OK"
    ACK_ERROR = "ACK_ERROR"
    TIMEOUT = "TIMEOUT"
    REGENERATING = "REGENERATING"


class AckStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class ValidationStep(str, Enum):
    SEMANTIC = "SEMANTIC"
    CONSISTENCY = "CONSISTENCY"
    OVERLAP = "OVERLAP"
    RESOURCE_CAPACITY = "RESOURCE_CAPACITY"
    SECURITY_COMPLIANCE = "SECURITY_COMPLIANCE"


class ValidationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING_USER = "PENDING_USER"


# =====================================================
# TIPOS ENUM DE POSTGRESQL (definidos una sola vez)
# =====================================================

def _enum_values(enum_cls):
    """Devuelve los valores del enum para persistirlos en PostgreSQL."""
    return [member.value for member in enum_cls]


max_scope_enum = SA_Enum(ScopeLevel, name="max_scope_enum")
intent_status_enum = SA_Enum(IntentStatus, name="intent_status_enum")
intent_scope_level_enum = SA_Enum(ScopeLevel, name="intent_scope_level_enum")
policy_status_enum = SA_Enum(PolicyStatus, name="policy_status_enum")
logical_task_status_enum = SA_Enum(LogicalTaskStatus, name="logical_task_status_enum")
device_type_enum = SA_Enum(DeviceType, name="device_type_enum")
device_technology_enum = SA_Enum(Technology, name="device_technology_enum")
device_status_enum = SA_Enum(DeviceStatus, name="device_status_enum")
atomic_task_status_enum = SA_Enum(AtomicTaskStatus, name="atomic_task_status_enum")
command_format_enum = SA_Enum(
    CommandFormat,
    name="command_format_enum",
    values_callable=_enum_values,
)
device_capability_enum = SA_Enum(
    Capability,
    name="device_capability_enum",
    values_callable=_enum_values,
)
execution_plan_format_enum = SA_Enum(
    ArtifactFormat,
    name="execution_plan_format_enum",
    values_callable=_enum_values,
)
execution_plan_protocol_enum = SA_Enum(
    Protocol,
    name="execution_plan_protocol_enum",
    values_callable=_enum_values,
)
execution_plan_executor_enum = SA_Enum(
    Executor,
    name="execution_plan_executor_enum",
    values_callable=_enum_values,
)
execution_plan_rollback_enum = SA_Enum(
    RollbackStrategy,
    name="execution_plan_rollback_enum",
    values_callable=_enum_values,
)
command_status_enum = SA_Enum(CommandStatus, name="command_status_enum")
ack_status_enum = SA_Enum(AckStatus, name="ack_status_enum")
validation_step_enum = SA_Enum(ValidationStep, name="validation_step_enum")
validation_result_enum = SA_Enum(ValidationResult, name="validation_result_enum")


# =====================================================
# NIVEL 0 - Sin dependencias
# =====================================================

class Role(SQLModel, table=True):
    __tablename__ = "roles"
    role_id: UUID = Field(default_factory=uuid4, primary_key=True)
    role_name: str = Field(unique=True, max_length=50)
    priority_level: int = Field(ge=1, le=5)
    max_scope: ScopeLevel = Field(
        default=ScopeLevel.NETWORK,
        sa_column=Column(max_scope_enum)
    )
    description: str | None = Field(default=None, sa_column=Column(Text))


class NetworkDevice(SQLModel, table=True):
    __tablename__ = "network_devices"
    device_id: UUID = Field(default_factory=uuid4, primary_key=True)
    hostname: str = Field(unique=True, max_length=150)
    device_type: DeviceType = Field(
        default=DeviceType.ROUTER,
        sa_column=Column(device_type_enum)
    )
    technology: Technology | None = Field(
        default=None,
        sa_column=Column(device_technology_enum)
    )
    vendor: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    is_virtual: bool = Field(default=False)
    management_ip: str | None = Field(default=None, max_length=45)
    location: str | None = Field(default=None, max_length=150)
    status: DeviceStatus = Field(
        default=DeviceStatus.ACTIVE,
        sa_column=Column(device_status_enum)
    )
    current_config: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_verified_at: datetime | None = Field(default=None)
    secret_ref: str | None = Field(default=None, max_length=255)
    inventory_version: int = Field(default=1)


class DeviceCapability(SQLModel, table=True):
    """Capacidades soportadas por un dispositivo de red."""
    __tablename__ = "device_capabilities"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    device_id: UUID = Field(foreign_key="network_devices.device_id")
    capability: Capability = Field(
        sa_column=Column(device_capability_enum)
    )
    supported: bool = True
    verified: bool = False
    version_min: str | None = Field(default=None, max_length=50)
    version_max: str | None = Field(default=None, max_length=50)
    details: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    last_verified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunks"
    id: int | None = Field(default=None, primary_key=True)
    source: str
    chunk_index: int = Field(default=0)
    chunk_text: str
    embedding: list[float] = Field(sa_column=Column(Vector(768)))
    chunk_metadata: dict = Field(default_factory=dict, sa_column=Column(PG_JSONB))
    vendor: str | None = None
    platform: str | None = None
    technology: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================
# NIVEL 1 - Depende de Role
# =====================================================

class User(SQLModel, table=True):
    __tablename__ = "users"
    user_id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=150)
    email: str = Field(unique=True, max_length=150)
    password_hash: str = Field(max_length=255)
    role_id: UUID = Field(foreign_key="roles.role_id")
    organization_unit: str | None = Field(default=None, max_length=150)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_login: datetime | None = None


# =====================================================
# NIVEL 2 - Depende de User
# =====================================================

class Intent(SQLModel, table=True):
    __tablename__ = "intents"
    intent_id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.user_id")
    action: str | None = Field(default=None, max_length=50)
    object: str | None = Field(default=None, max_length=100)
    technology: str | None = Field(default=None, max_length=100)
    mechanism: str | None = Field(default=None, sa_column=Column(Text))
    condition: str | None = Field(default=None, sa_column=Column(Text))
    parameters: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    raw_text: str | None = Field(default=None, sa_column=Column(Text))
    json_translated: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    status: IntentStatus = Field(
        default=IntentStatus.DRAFT,
        sa_column=Column(intent_status_enum)
    )
    priority_level: int | None = Field(default=None, ge=1, le=5)
    scope_level: ScopeLevel = Field(
        default=ScopeLevel.ELEMENT,
        sa_column=Column(intent_scope_level_enum)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sent_at: datetime | None = None
    tmf_intent_type: str | None = Field(default=None, max_length=100)


# =====================================================
# NIVEL 3 - Depende de Intent
# =====================================================

class Policy(SQLModel, table=True):
    __tablename__ = "policies"
    policy_id: UUID = Field(default_factory=uuid4, primary_key=True)
    intent_id: UUID = Field(foreign_key="intents.intent_id")
    version: int = Field(default=1)
    policy_description: str | None = Field(default=None, sa_column=Column(Text))
    policy_json: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    parameters_to_monitor: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    status: PolicyStatus = Field(
        default=PolicyStatus.PROPOSED,
        sa_column=Column(policy_status_enum)
    )
    generated_by: str | None = Field(default="AGENT_AI3", max_length=50)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sent_at: datetime | None = None


# =====================================================
# NIVEL 4 - Depende de Policy e Intent
# =====================================================

class LogicalTask(SQLModel, table=True):
    __tablename__ = "logical_tasks"
    task_id: UUID = Field(default_factory=uuid4, primary_key=True)
    policy_id: UUID = Field(foreign_key="policies.policy_id")
    intent_id: UUID = Field(foreign_key="intents.intent_id")
    task_order: int | None = None
    task_description: str | None = Field(default=None, sa_column=Column(Text))
    task_json: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    status: LogicalTaskStatus = Field(
        default=LogicalTaskStatus.PROPOSED,
        sa_column=Column(logical_task_status_enum)
    )
    generated_by: str | None = Field(default="AGENT_AI3", max_length=50)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sent_at: datetime | None = None


# =====================================================
# NIVEL 5 - Depende de LogicalTask, Policy, Intent
# =====================================================

class AtomicTask(SQLModel, table=True):
    __tablename__ = "atomic_tasks"
    atomic_task_id: UUID = Field(default_factory=uuid4, primary_key=True)
    logical_task_id: UUID = Field(foreign_key="logical_tasks.task_id")
    policy_id: UUID = Field(foreign_key="policies.policy_id")
    intent_id: UUID = Field(foreign_key="intents.intent_id")
    task_order: int | None = None
    task_description: str | None = Field(default=None, sa_column=Column(Text))
    task_json: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    required_capabilities: dict | None = Field(default=None, sa_column=Column(PG_JSONB))
    status: AtomicTaskStatus = Field(
        default=AtomicTaskStatus.PENDING,
        sa_column=Column(atomic_task_status_enum)
    )
    attempt_count: int = Field(default=1, ge=1, le=3)
    generated_by: str | None = Field(default="AGENT_AI5", max_length=50)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================
# NIVEL 6.5 - Depende de AtomicTask
# =====================================================

class ExecutionPlanRecord(SQLModel, table=True):
    """Plan de ejecución generado por el motor de decisión."""
    __tablename__ = "execution_plans"
    plan_id: UUID = Field(default_factory=uuid4, primary_key=True)
    atomic_task_id: UUID = Field(foreign_key="atomic_tasks.atomic_task_id")
    device_ids: list[UUID] = Field(sa_column=Column(PG_JSONB))
    artifact_format: ArtifactFormat = Field(
        sa_column=Column(execution_plan_format_enum)
    )
    protocol: Protocol = Field(
        sa_column=Column(execution_plan_protocol_enum)
    )
    executor: Executor = Field(
        sa_column=Column(execution_plan_executor_enum)
    )
    rollback_strategy: RollbackStrategy = Field(
        sa_column=Column(execution_plan_rollback_enum)
    )
    requires_approval: bool = False
    fallback_used: bool = False
    inventory_version: int = 1
    decision_trace: list[str] = Field(sa_column=Column(PG_JSONB))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================
# NIVEL 7 - Depende de ExecutionPlan, AtomicTask, LogicalTask, Policy, Intent
# =====================================================

class Command(SQLModel, table=True):
    __tablename__ = "commands"
    command_id: UUID = Field(default_factory=uuid4, primary_key=True)
    atomic_task_id: UUID = Field(foreign_key="atomic_tasks.atomic_task_id")
    logical_task_id: UUID = Field(foreign_key="logical_tasks.task_id")
    policy_id: UUID = Field(foreign_key="policies.policy_id")
    intent_id: UUID = Field(foreign_key="intents.intent_id")
    execution_plan_id: UUID | None = Field(
        default=None,
        foreign_key="execution_plans.plan_id",
    )
    vendor: str = Field(max_length=50)
    format: CommandFormat = Field(
        sa_column=Column(command_format_enum)
    )
    command_payload: str = Field(sa_column=Column(Text))
    validation_hash: str | None = Field(default=None, max_length=64)
    status: CommandStatus = Field(
        default=CommandStatus.PENDING,
        sa_column=Column(command_status_enum)
    )
    attempt_count: int = Field(default=1, ge=1, le=3)
    generated_by: str | None = Field(default="AGENT_AI6", max_length=50)
    generated_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_sent_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =====================================================
# NIVEL 8 - Depende de Command y NetworkDevice
# =====================================================

class CommandExecution(SQLModel, table=True):
    __tablename__ = "command_executions"
    execution_id: UUID = Field(default_factory=uuid4, primary_key=True)
    command_id: UUID = Field(foreign_key="commands.command_id")
    attempt_number: int = Field(ge=1, le=3)
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ack_received_at: datetime | None = Field(default=None)
    ack_status: AckStatus | None = Field(
        default=None,
        sa_column=Column(ack_status_enum)
    )
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    device_id: UUID | None = Field(foreign_key="network_devices.device_id")
    response_payload: str | None = Field(default=None, sa_column=Column(Text))


# =====================================================
# NIVEL 9 - Sin dependencias (plantillas)
# =====================================================

class AtomicTaskTemplate(SQLModel, table=True):
    __tablename__ = "atomic_task_templates"
    template_id: UUID = Field(default_factory=uuid4, primary_key=True)
    template_name: str
    applicable_technologies: list[str] | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    required_capabilities: dict | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    task_json_schema: dict | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    default_parameters: dict | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_active: bool = True


# =====================================================
# NIVEL 10 - Depende de AtomicTaskTemplate
# =====================================================

class CommandTemplate(SQLModel, table=True):
    __tablename__ = "command_templates"
    template_id: UUID = Field(default_factory=uuid4, primary_key=True)
    atomic_task_template_id: UUID = Field(
        foreign_key="atomic_task_templates.template_id"
    )
    vendor: str = Field(max_length=50)
    format: CommandFormat = Field(
        sa_column=Column(command_format_enum)
    )
    command_template: str = Field(sa_column=Column(Text))
    parameter_mapping: dict | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    validation_regex: str | None = Field(default=None, sa_column=Column(Text))
    is_active: bool = True


# =====================================================
# NIVEL 11 - Depende de CommandTemplate
# =====================================================

class CommandExample(SQLModel, table=True):
    __tablename__ = "command_examples"
    example_id: UUID = Field(default_factory=uuid4, primary_key=True)
    command_template_id: UUID | None = Field(
        foreign_key="command_templates.template_id"
    )
    input_parameters: dict | None = Field(
        default=None, sa_column=Column(PG_JSONB)
    )
    output_command: str
    description: str | None = None
    embedding_vector: list[float] | None = Field(
        default=None, sa_column=Column(Vector(768))
    )