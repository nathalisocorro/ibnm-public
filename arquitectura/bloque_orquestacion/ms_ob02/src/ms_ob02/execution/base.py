"""
Interfaz común de los adaptadores de ejecución.

Cada adaptador sabe cómo aplicar un comando en un dispositivo real
usando un transporte concreto (SSH/CLI, NETCONF, RESTCONF, Ansible).

Los adaptadores son deterministas: no usan LLM. Solo ejecutan.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from ms_ob02.execution.decision_models import ExecutionPlan


class ExecutionStatus(str, Enum):
    """Resultado de la ejecución."""
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    ROLLBACK_SUCCESS = "ROLLBACK_SUCCESS"
    ROLLBACK_ERROR = "ROLLBACK_ERROR"


class ExecutionResult(BaseModel):
    """Resultado uniforme de una ejecución."""
    status: ExecutionStatus
    device_id: Optional[UUID] = None
    hostname: Optional[str] = None
    response: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    rollback_status: Optional[str] = None


class DeviceTarget(BaseModel):
    """Dispositivo objetivo de una ejecución."""
    device_id: UUID
    hostname: str
    management_ip: Optional[str] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None
    model: Optional[str] = None


class ExecutionAdapter(ABC):
    """
    Interfaz base de los adaptadores de ejecución.

    Cada implementación corresponde a un formato/protocolo concreto.
    """

    #: Formatos que este adaptador puede ejecutar.
    supported_formats: tuple[str, ...] = ()

    @abstractmethod
    async def validate(self, plan: ExecutionPlan, device: DeviceTarget) -> None:
        """
        Verifica que el dispositivo pueda recibir el comando del plan.

        Args:
            plan: Plan de ejecución.
            device: Dispositivo objetivo.

        Raises:
            ExecutionAdapterError: si el dispositivo no es compatible.
        """
        ...

    @abstractmethod
    async def apply(
        self,
        plan: ExecutionPlan,
        command: str,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Aplica el comando en el dispositivo.

        Args:
            plan: Plan de ejecución.
            command: Contenido del comando a ejecutar.
            device: Dispositivo objetivo.

        Returns:
            ExecutionResult con el resultado de la ejecución.
        """
        ...

    async def rollback(
        self,
        plan: ExecutionPlan,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Revierte el cambio aplicado en el dispositivo.

        Por defecto no está soportado. Los adaptadores que sí lo
        soportan (confirmed-commit, candidate-discard) deben sobrescribir.
        """
        return ExecutionResult(
            status=ExecutionStatus.ROLLBACK_ERROR,
            device_id=device.device_id,
            hostname=device.hostname,
            error="rollback no soportado por este adaptador",
        )


class ExecutionAdapterError(Exception):
    """Error durante la validación o ejecución de un comando."""
