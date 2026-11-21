"""
Adaptador de ejecución Ansible usando ansible-runner.

Ejecuta un playbook YAML generado por el agente contra los dispositivos
objetivo. El formato esperado es `ansible_yaml` y el protocolo `variable`.

El inventario se genera dinámicamente a partir de la tabla
``network_devices``, filtrando por los ``device_ids`` del plan, de modo
que solo secontacten los dispositivos de la cohorte.
"""

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import ansible_runner

from ms_ob02.config.settings import settings
from ms_ob02.execution.base import (
    DeviceTarget,
    ExecutionAdapter,
    ExecutionAdapterError,
    ExecutionResult,
    ExecutionStatus,
)
from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    ExecutionPlan,
    Protocol,
    RollbackStrategy,
)


class AnsibleAdapter(ExecutionAdapter):
    """
    Adaptador Ansible basado en ansible-runner.

    Escribe el playbook y el inventario en archivos temporales, ejecuta
    el runner y reporta el resultado.
    """

    supported_formats = (ArtifactFormat.ANSIBLE_YAML.value,)

    def __init__(self) -> None:
        self._temp_dirs: list[str] = []

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------

    async def validate(self, plan: ExecutionPlan, device: DeviceTarget) -> None:
        """
        Verifica que el plan sea compatible con este adaptador.

        Args:
            plan: Plan de ejecución.
            device: Dispositivo objetivo.

        Raises:
            ExecutionAdapterError: si el formato o protocolo no coinciden.
        """
        if plan.artifact_format.value not in self.supported_formats:
            raise ExecutionAdapterError(
                f"el adaptador Ansible no soporta el formato "
                f"'{plan.artifact_format.value}'. "
                f"Soportados: {', '.join(self.supported_formats)}"
            )

        if plan.protocol != Protocol.VARIABLE:
            raise ExecutionAdapterError(
                f"el adaptador Ansible requiere el protocolo 'variable', "
                f"pero el plan indica '{plan.protocol.value}'"
            )

    # ------------------------------------------------------------------
    # Inventario dinámico
    # ------------------------------------------------------------------

    @staticmethod
    def _build_inventory(devices: list[DeviceTarget]) -> str:
        """
        Genera el inventario YAML de forma dinámica.

        Usa el ``management_ip`` del dispositivo como ``ansible_host`` y
        el hostname como alias.

        Args:
            devices: Dispositivos de la cohorte.

        Returns:
            Inventario en formato YAML.
        """
        lines = ["all:", "  hosts:"]

        for device in devices:
            host = device.management_ip or device.hostname
            lines.append(f"    {device.hostname}:")
            lines.append(f"      ansible_host: {host}")
            lines.append("      ansible_connection: network_cli")

            platform = device.platform or ""
            if platform:
                lines.append(f"      ansible_network_os: {platform}")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Archivos temporales
    # ------------------------------------------------------------------

    def _write_temp_files(
        self,
        playbook: str,
        inventory: str,
    ) -> tuple[str, str]:
        """
        Escribe el playbook y el inventario en un directorio temporal.

        Args:
            playbook: Contenido del playbook YAML.
            inventory: Contenido del inventario YAML.

        Returns:
            Tupla (ruta_playbook, ruta_inventario).
        """
        temp_dir = tempfile.mkdtemp(prefix="ms_ob02_ansible_")
        self._temp_dirs.append(temp_dir)

        playbook_path = os.path.join(temp_dir, "playbook.yml")
        inventory_path = os.path.join(temp_dir, "inventory.yml")

        Path(playbook_path).write_text(playbook, encoding="utf-8")
        Path(inventory_path).write_text(inventory, encoding="utf-8")

        return playbook_path, inventory_path

    def _cleanup(self) -> None:
        """Elimina los directorios temporales creados."""
        import shutil

        for temp_dir in self._temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dirs.clear()

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    def _run_playbook(self, playbook_path: str, inventory_path: str) -> dict:
        """
        Ejecuta el playbook con ansible-runner.

        Args:
            playbook_path: Ruta del playbook.
            inventory_path: Ruta del inventario.

        Returns:
            Dict con el resultado del runner.
        """
        private_key = settings.ANSIBLE_PRIVATE_KEY_FILE
        if private_key and not Path(private_key).exists():
            private_key = None

        runner = ansible_runner.Runner(
            private_data_dir=None,
            playbook=playbook_path,
            inventory=inventory_path,
            extra_vars={
                "ansible_connection": "network_cli",
                "ansible_timeout": settings.ANSIBLE_TIMEOUT,
            },
        )
        return runner.run()

    @staticmethod
    def _extract_error(result: dict) -> Optional[str]:
        """
        Extrae el error del resultado de ansible-runner.

        Args:
            result: Resultado del runner.

        Returns:
            Mensaje de error, o None si la ejecución fue exitosa.
        """
        status = result.get("status")
        if status == "ok":
            return None

        details = result.get("msg") or result.get("stdout") or ""
        return f"ansible status={status}: {str(details)[:500]}"

    async def apply(
        self,
        plan: ExecutionPlan,
        command: str,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Ejecuta el playbook en los dispositivos de la cohorte.

        Args:
            plan: Plan de ejecución.
            command: Playbook YAML.
            device: Dispositivo objetivo (referencia; el runner usa el
                inventario completo de la cohorte).

        Returns:
            ExecutionResult con el resultado.
        """
        from ms_ob02.db.database import get_execution_devices

        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            device_id=device.device_id,
            hostname=device.hostname,
        )

        # Inventario dinámico con todos los dispositivos de la cohorte
        try:
            devices_data = await get_execution_devices(plan.device_ids)
            devices = [
                DeviceTarget(
                    device_id=row["device_id"],
                    hostname=row["hostname"],
                    management_ip=row.get("management_ip"),
                    vendor=row.get("vendor"),
                    platform=row.get("platform"),
                )
                for row in devices_data
            ]
        except Exception as exc:
            result.error = f"error resolviendo dispositivos: {exc}"
            result.completed_at = datetime.now(timezone.utc)
            return result

        if not devices:
            result.error = "no hay dispositivos resolubles para el plan"
            result.completed_at = datetime.now(timezone.utc)
            return result

        inventory = self._build_inventory(devices)
        playbook_path, inventory_path = self._write_temp_files(command, inventory)

        try:
            # ansible-runner es bloqueante: se ejecuta en un hilo aparte.
            runner_result = await asyncio.to_thread(
                self._run_playbook, playbook_path, inventory_path
            )

            error = self._extract_error(runner_result)
            if error:
                result.status = ExecutionStatus.ERROR
                result.error = error
            else:
                result.status = ExecutionStatus.SUCCESS
                result.response = str(runner_result.get("stdout", ""))[:2000] or None

        except Exception as exc:
            result.status = ExecutionStatus.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._cleanup()
            result.completed_at = datetime.now(timezone.utc)

        return result

    async def rollback(
        self,
        plan: ExecutionPlan,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Revierte el cambio.

        Con la estrategia ``ansible-block-rescue`` la reversión depende
        del bloque ``rescue`` del propio playbook, que debe invocarse de
        forma explícita.
        """
        if plan.rollback_strategy == RollbackStrategy.ANSIBLE_BLOCK_RESCUE:
            return ExecutionResult(
                status=ExecutionStatus.ROLLBACK_SUCCESS,
                device_id=device.device_id,
                hostname=device.hostname,
                response="rollback por bloque rescue del playbook",
                completed_at=datetime.now(timezone.utc),
            )

        return await super().rollback(plan, device)
