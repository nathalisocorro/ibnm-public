"""
Adaptador de ejecución CLI sobre SSH usando Netmiko.

Aplica comandos de configuración en dispositivos que solo soportan
CLI por SSH. El formato esperado es `cli` y el protocolo `ssh_cli`.
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from ms_ob02.config.settings import settings
from ms_ob02.execution.base import (
    DeviceTarget,
    ExecutionAdapter,
    ExecutionAdapterError,
    ExecutionResult,
    ExecutionStatus,
)
from ms_ob02.execution.credentials import resolve_credentials
from ms_ob02.execution.decision_models import ArtifactFormat, ExecutionPlan


# Patrones que indican error en la salida de un dispositivo de red.
_ERROR_PATTERNS = (
    re.compile(r"% ?Invalid input", re.IGNORECASE),
    re.compile(r"% ?Incomplete command", re.IGNORECASE),
    re.compile(r"% ?Error", re.IGNORECASE),
    re.compile(r"^Error:", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"Unknown command", re.IGNORECASE),
    re.compile(r"Ambiguous command", re.IGNORECASE),
    re.compile(r"%\s*Bad mask", re.IGNORECASE),
)


class CliNetmikoAdapter(ExecutionAdapter):
    """
    Adaptador CLI/SSH basado en Netmiko.

    Ejecuta el comando enviado por línea, de forma secuencial, en el
    dispositivo objetivo.
    """

    supported_formats = (ArtifactFormat.CLI.value,)

    def __init__(self) -> None:
        self._connections: dict[str, ConnectHandler] = {}

    # ------------------------------------------------------------------
    # Resolución de credenciales
    # ------------------------------------------------------------------

    def _credentials_for(self, device: DeviceTarget) -> dict:
        """
        Resuelve los parámetros de conexión del dispositivo.

        Usa el resolver común de credenciales con el transporte ssh_cli.

        Returns:
            Dict con los parámetros de conexión.
        """
        creds = resolve_credentials(device, "ssh_cli")

        params = {
            "host": device.management_ip or device.hostname,
            "username": creds.username,
            "password": creds.password,
            "device_type": creds.device_type,
            "port": creds.port,
            "timeout": settings.NETMIKO_CONN_TIMEOUT,
        }
        if creds.secret:
            params["secret"] = creds.secret

        return params

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def _connect(self, device: DeviceTarget) -> ConnectHandler:
        """
        Abre una conexión SSH al dispositivo.

        Args:
            device: Dispositivo objetivo.

        Returns:
            Conexión de Netmiko activa.

        Raises:
            ExecutionAdapterError: si la conexión falla.
        """
        params = self._credentials_for(device)

        try:
            connection = ConnectHandler(**params)
        except NetmikoAuthenticationException as exc:
            raise ExecutionAdapterError(
                f"autenticación fallida en '{device.hostname}': {exc}"
            ) from exc
        except NetmikoTimeoutException as exc:
            raise ExecutionAdapterError(
                f"timeout conectando a '{device.hostname}': {exc}"
            ) from exc
        except Exception as exc:
            raise ExecutionAdapterError(
                f"error conectando a '{device.hostname}': {type(exc).__name__}: {exc}"
            ) from exc

        # Ajustar timeouts post-conexión. En algunas versiones de Netmiko
        # no son kwargs de ConnectHandler, pero sí atributos de la sesión.
        try:
            connection.read_timeout = settings.NETMIKO_TIMEOUT
        except Exception:
            pass
        try:
            connection.global_delay_factor = 2
        except Exception:
            pass
        try:
            connection.fast_cli = False
        except Exception:
            pass

        self._connections[device.hostname] = connection
        return connection

    def _disconnect(self, hostname: str) -> None:
        """Cierra la conexión de un dispositivo si existe."""
        connection = self._connections.pop(hostname, None)
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

    def disconnect_all(self) -> None:
        """Cierra todas las conexiones abiertas."""
        for hostname in list(self._connections.keys()):
            self._disconnect(hostname)

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    @staticmethod
    def _split_commands(command: str) -> list[str]:
        """
        Divide el payload en líneas de comando.

        Ignora líneas vacías y comentarios.

        Args:
            command: Payload del comando.

        Returns:
            Lista de comandos a ejecutar.
        """
        commands = []
        for line in command.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("!"):
                continue
            commands.append(stripped)
        return commands

    @staticmethod
    def _detect_error(output: str) -> Optional[str]:
        """
        Detecta si la salida del dispositivo indica un error.

        Args:
            output: Salida del comando.

        Returns:
            Texto del error detectado, o None si no hay error.
        """
        for pattern in _ERROR_PATTERNS:
            match = pattern.search(output)
            if match:
                return match.group(0).strip()
        return None

    async def validate(self, plan: ExecutionPlan, device: DeviceTarget) -> None:
        """
        Verifica que el plan sea compatible con este adaptador.

        Args:
            plan: Plan de ejecución.
            device: Dispositivo objetivo.

        Raises:
            ExecutionAdapterError: si el formato no es soportado.
        """
        if plan.artifact_format.value not in self.supported_formats:
            raise ExecutionAdapterError(
                f"el adaptador CLI/Netmiko no soporta el formato "
                f"'{plan.artifact_format.value}'. "
                f"Soportados: {', '.join(self.supported_formats)}"
            )

        if plan.protocol.value != "ssh_cli":
            raise ExecutionAdapterError(
                f"el adaptador CLI/Netmiko requiere el protocolo 'ssh_cli', "
                f"pero el plan indica '{plan.protocol.value}'"
            )

    async def apply(
        self,
        plan: ExecutionPlan,
        command: str,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Aplica el comando CLI en el dispositivo.

        Estrategia:
          - Si el payload contiene 'configure terminal' o comandos de
            configuración (interface, description, etc.), se agrupan y se
            envían con send_config_set(), que gestiona el cambio de prompt
            entre exec (frr#) y config (frr(config)#).
          - 'write memory' / 'copy running-config startup-config' se envían
            aparte con send_command() en modo exec, tras salir de config.
          - Comandos de solo lectura (show ...) van con send_command().

        Args:
            plan: Plan de ejecución.
            command: Payload con los comandos a ejecutar.
            device: Dispositivo objetivo.

        Returns:
            ExecutionResult con el resultado.
        """
        started_at = datetime.now(timezone.utc)
        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            device_id=device.device_id,
            hostname=device.hostname,
            started_at=started_at,
        )

        commands = self._split_commands(command)
        if not commands:
            result.error = "el payload no contiene comandos ejecutables"
            result.completed_at = datetime.now(timezone.utc)
            return result

        try:
            connection = self._connect(device)
        except ExecutionAdapterError as exc:
            result.error = str(exc)
            result.completed_at = datetime.now(timezone.utc)
            return result

        outputs: list[str] = []

        try:
            # Palabras que indican comandos de ejecución (no de config)
            EXEC_COMMANDS = ("write memory", "copy running-config startup-config",
                             "write", "save")
            CONFIG_NOISE = ("configure terminal", "conf t", "end", "exit")

            # Separar: config vs exec vs read-only
            config_lines: list[str] = []
            exec_lines: list[str] = []
            readonly_lines: list[str] = []

            for cmd in commands:
                low = cmd.lower()
                if low in (c.lower() for c in EXEC_COMMANDS):
                    exec_lines.append(cmd)
                elif low in (c.lower() for c in CONFIG_NOISE):
                    # 'end'/'exit'/'configure terminal' los gestiona
                    # send_config_set automáticamente; no los reenviamos.
                    continue
                elif low.startswith("show ") or low.startswith("display "):
                    readonly_lines.append(cmd)
                else:
                    config_lines.append(cmd)

            # 1) Bloque de configuración con send_config_set
            if config_lines:
                output = await asyncio.to_thread(
                    connection.send_config_set,
                    config_lines,
                    read_timeout=settings.NETMIKO_TIMEOUT,
                    cmd_verify=False,
                )
                outputs.append(output)
                error = self._detect_error(output)
                if error:
                    result.status = ExecutionStatus.ERROR
                    result.error = f"config_set → {error}"
                    result.response = "\n".join(outputs)
                    result.completed_at = datetime.now(timezone.utc)
                    return result

            # 2) Comandos de solo lectura (show)
            for cmd in readonly_lines:
                output = await asyncio.to_thread(
                    connection.send_command,
                    cmd,
                    read_timeout=settings.NETMIKO_TIMEOUT,
                )
                outputs.append(output)
                error = self._detect_error(output)
                if error:
                    result.status = ExecutionStatus.ERROR
                    result.error = f"'{cmd}' → {error}"
                    result.response = "\n".join(outputs)
                    result.completed_at = datetime.now(timezone.utc)
                    return result

            # 3) Comandos de exec (write memory), después de salir de config
            for cmd in exec_lines:
                output = await asyncio.to_thread(
                    connection.send_command,
                    cmd,
                    read_timeout=settings.NETMIKO_TIMEOUT,
                    expect_string=r"#\s*$",
                )
                outputs.append(output)
                error = self._detect_error(output)
                if error:
                    result.status = ExecutionStatus.ERROR
                    result.error = f"'{cmd}' → {error}"
                    result.response = "\n".join(outputs)
                    result.completed_at = datetime.now(timezone.utc)
                    return result

            result.status = ExecutionStatus.SUCCESS
            result.response = "\n".join(outputs)

        except NetmikoTimeoutException as exc:
            result.status = ExecutionStatus.TIMEOUT
            result.error = f"timeout ejecutando en '{device.hostname}': {exc}"
        except Exception as exc:
            result.status = ExecutionStatus.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._disconnect(device.hostname)
            result.completed_at = datetime.now(timezone.utc)

        return result

    async def rollback(
        self,
        plan: ExecutionPlan,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Revierte el cambio usando comandos compensatorios.

        Netmiko no soporta rollback transaccional, así que el rollback
        depende de la estrategia de rollback del plan. Cuando es
        'compensation-commands', la reversión queda a cargo del
        llamador con los rollback_steps de la tarea.
        """
        if plan.rollback_strategy.value == "compensation-commands":
            return ExecutionResult(
                status=ExecutionStatus.ROLLBACK_SUCCESS,
                device_id=device.device_id,
                hostname=device.hostname,
                response="rollback por comandos compensatorios a cargo del orquestador",
                completed_at=datetime.now(timezone.utc),
            )

        return await super().rollback(plan, device)
