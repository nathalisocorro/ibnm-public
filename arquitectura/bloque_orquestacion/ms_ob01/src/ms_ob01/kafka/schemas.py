"""Contratos Kafka del gestor de tareas atomicas."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommandFormat(str, Enum):
    CLI = "cli"
    NETCONF_XML = "netconf_xml"
    RESTCONF_JSON = "restconf_json"
    ANSIBLE_YAML = "ansible_yaml"

class LogicalTaskProposedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    event: str = "LOGICAL_TASK_PROPOSED"
    task_id: UUID
    policy_id: UUID
    intent_id: UUID
    user_id: UUID | None = None
    priority_level: int | None = None
    scope_level: str | None = None
    version: int = Field(default=1, ge=1, le=3)
    try_number: int = Field(default=1, alias="try", ge=1, le=3)
    status: str = "VALIDATED"
    task_description: str = ""
    task_json: dict[str, Any]
    validation_layers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AtomicTaskProposedEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str = "ATOMIC_TASK_PROPOSED"
    event_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "MS-OB01"
    atomic_task_id: UUID
    logical_task_id: UUID
    policy_id: UUID
    intent_id: UUID
    task_order: int = 1
    task_description: str
    atomic_task_json: dict[str, Any]
    vendor: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    os_version: str = Field(min_length=1)
    device_targets: list[str] = Field(min_length=1)
    executor_preference: str = "AUTO"
    format: CommandFormat = CommandFormat.CLI
    format_preference: str | None = None
    criticality: str = "MEDIUM"
    attempt_count: int = 1
    max_attempts: int = 3
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(ge=1, le=3)
    try_number: int = Field(alias="try", ge=1, le=3)
    status: str = "VALIDATED"
    generated_by: str = "AGENT_AI5"

    @field_validator("vendor", "platform", "os_version")
    @classmethod
    def metadata_must_be_real(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.lower() in {"", "generic", "unknown", "n/a", "none", "null"}:
            raise ValueError("La metadata de infraestructura debe proceder del SSoT.")
        return normalized

    @field_validator("device_targets")
    @classmethod
    def device_targets_must_be_identified(cls, value: list[str]) -> list[str]:
        normalized = [device.strip() for device in value if isinstance(device, str) and device.strip()]
        if len(normalized) != len(value):
            raise ValueError("device_targets contiene dispositivos vacíos o inválidos.")
        return normalized


class LogicalTaskFaultEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str = "LOGICAL_TASK_FAULT"
    event_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "MS-OB01"
    atomic_task_id: UUID
    logical_task_id: UUID = Field(alias="task_id")
    policy_id: UUID
    intent_id: UUID
    try_number: int = Field(alias="try", ge=1)
    reason: str


class AtomicTaskFaultEvent(BaseModel):
    """Contrato publicado por MS-O04 cuando no pudo generar comandos."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    event: str = "ATOMIC_TASK_FAULT"
    atomic_task_id: UUID
    logical_task_id: UUID
    policy_id: UUID
    intent_id: UUID
    vendor: str
    platform: str
    format: CommandFormat = CommandFormat.CLI
    format_preference: CommandFormat | None = None
    plan_id: UUID | None = None
    device_ids: list[UUID] | None = None
    error_reason: str
    error_detail: str | None = None
    attempts_made: int = Field(default=0, ge=0)
    last_validation_result: str | None = None
    decision_trace: list[str] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    fault_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_by: str = "AGENT_AI6"
