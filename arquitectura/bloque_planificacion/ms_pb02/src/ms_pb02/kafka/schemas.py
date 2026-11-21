"""Contratos de los eventos que consume y publica MS-PB02."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyProposedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    event: str = "POLICY_PROPOSED"
    policy_id: UUID
    intent_id: UUID
    user_id: UUID | None = None
    priority_level: int | None = None
    scope_level: str | None = None
    version: int = Field(default=1, ge=1, le=3)
    try_number: int = Field(default=1, alias="try", ge=1, le=3)
    status: str = "VALIDATED"
    policy_description: str = ""
    policy_json: dict[str, Any]


class LogicalTaskFaultEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    event: str = "LOGICAL_TASK_FAULT"
    event_id: UUID | None = None
    timestamp: datetime | None = None
    source: str | None = None
    atomic_task_id: UUID | None = None
    logical_task_id: UUID = Field(alias="task_id")
    policy_id: UUID | None = None
    intent_id: UUID | None = None
    try_number: int = Field(default=1, alias="try", ge=1, le=3)
    reason: str = "ORCHESTRATION_REJECTED"


class LogicalTaskProposedEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str = "LOGICAL_TASK_PROPOSED"
    event_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "MS-PB02"
    task_id: UUID
    policy_id: UUID
    intent_id: UUID
    user_id: UUID | None = None
    priority_level: int | None = None
    scope_level: str | None = None
    version: int = Field(ge=1, le=3)
    try_number: int = Field(alias="try", ge=1, le=3)
    status: str = "VALIDATED"
    task_description: str
    task_json: dict[str, Any]
    validation_layers: dict[str, dict[str, Any]]


class PolicyFaultEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str = "POLICY_FAULT"
    event_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "MS-PB02"
    policy_id: UUID
    intent_id: UUID
    task_id: UUID
    try_number: int = Field(alias="try", ge=1)
    reason: str
