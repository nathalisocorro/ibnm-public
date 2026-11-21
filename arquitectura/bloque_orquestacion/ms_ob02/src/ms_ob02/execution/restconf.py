"""
Adaptador de ejecución RESTCONF usando httpx.

Aplica configuración estructurada en dispositivos que exponen una API
REST. El formato esperado es `restconf_json` y el protocolo `restconf`.

RESTCONF no ofrece rollback atómico. Si el plan exige una estrategia
transaccional (confirmed-commit), la validación falla: el adaptador
comprueba que exista un mecanismo de backup compatible.
"""

import json
from datetime import datetime, timezone
from typing import Optional

import httpx

from ms_ob02.config.settings import settings
from ms_ob02.execution.base import (
    DeviceTarget,
    ExecutionAdapter,
    ExecutionAdapterError,
    ExecutionResult,
    ExecutionStatus,
)
from ms_ob02.execution.credentials import resolve_credentials
from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    ExecutionPlan,
    Protocol,
    RollbackStrategy,
)


# Media types de RESTCONF.
YANG_JSON = "application/yang-data+json"

# Métodos HTTP soportados para aplicar configuración.
_ALLOWED_METHODS = ("POST", "PUT", "PATCH")


class RestconfAdapter(ExecutionAdapter):
    """
    Adaptador RESTCONF basado en httpx.

    Envía la configuración como JSON sobre HTTPS y detecta errores
    según el código de estado y el cuerpo de la respuesta.
    """

    supported_formats = (ArtifactFormat.RESTCONF_JSON.value,)

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
            ExecutionAdapterError: si el formato, el protocolo o la
                estrategia de rollback no son compatibles.
        """
        if plan.artifact_format.value not in self.supported_formats:
            raise ExecutionAdapterError(
                f"el adaptador RESTCONF no soporta el formato "
                f"'{plan.artifact_format.value}'. "
                f"Soportados: {', '.join(self.supported_formats)}"
            )

        if plan.protocol != Protocol.RESTCONF:
            raise ExecutionAdapterError(
                f"el adaptador RESTCONF requiere el protocolo 'restconf', "
                f"pero el plan indica '{plan.protocol.value}'"
            )

        # RESTCONF no implementa rollback transaccional.
        if plan.rollback_strategy in (
            RollbackStrategy.CONFIRMED_COMMIT,
            RollbackStrategy.CANDIDATE_DISCARD,
        ):
            raise ExecutionAdapterError(
                f"RESTCONF no soporta la estrategia de rollback "
                f"'{plan.rollback_strategy.value}'. Use 'config-backup' o "
                f"'compensation-commands'."
            )

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_payload(payload: str) -> tuple[dict, str]:
        """
        Interpreta el payload de configuración.

        Acepta dos formatos:
        - Un objeto JSON con las claves ``method``/``path``/``body``
        - Un objeto JSON plano, que se envía como PATCH a la ruta base

        Args:
            payload: Payload generado por el agente.

        Returns:
            Tupla (metodo, ruta, cuerpo).

        Raises:
            ExecutionAdapterError: si el JSON es inválido.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ExecutionAdapterError(
                f"el payload RESTCONF no es JSON válido: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ExecutionAdapterError(
                "el payload RESTCONF debe ser un objeto JSON"
            )

        method = str(data.get("method", "PATCH")).upper()
        path = data.get("path") or data.get("uri") or ""
        body = data.get("body", data.get("data"))

        if method not in _ALLOWED_METHODS:
            raise ExecutionAdapterError(
                f"método HTTP '{method}' no soportado por RESTCONF. "
                f"Permitidos: {', '.join(_ALLOWED_METHODS)}"
            )

        if body is None:
            body = {
                k: v for k, v in data.items()
                if k not in ("method", "path", "uri", "body", "data")
            } or data

        return method, path, body

    @staticmethod
    def _extract_error(response: httpx.Response) -> Optional[str]:
        """
        Extrae el mensaje de error de una respuesta RESTCONF.

        Args:
            response: Respuesta HTTP.

        Returns:
            Mensaje de error, o None si la operación fue exitosa.
        """
        if response.status_code < 400:
            return None

        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return f"HTTP {response.status_code}: {response.text[:300]}"

        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            messages = []
            for item in errors:
                if isinstance(item, dict):
                    messages.append(
                        f"{item.get('error-tag', 'error')}: "
                        f"{item.get('error-message', '')}"
                    )
                else:
                    messages.append(str(item))
            return " | ".join(messages)

        return f"HTTP {response.status_code}: {response.text[:300]}"

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    def _base_url(self, device: DeviceTarget, creds) -> str:
        """Construye la URL base del dispositivo."""
        host = device.management_ip or device.hostname
        scheme = "https" if settings.RESTCONF_PORT != 80 else "http"
        base_path = settings.RESTCONF_BASE_PATH.rstrip("/")
        return f"{scheme}://{host}:{creds.port}{base_path}"

    async def apply(
        self,
        plan: ExecutionPlan,
        command: str,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Aplica la configuración RESTCONF en el dispositivo.

        Args:
            plan: Plan de ejecución.
            command: Payload JSON con la configuración.
            device: Dispositivo objetivo.

        Returns:
            ExecutionResult con el resultado.
        """
        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            device_id=device.device_id,
            hostname=device.hostname,
        )

        try:
            creds = resolve_credentials(device, "restconf")
            method, path, body = self._parse_payload(command)
        except ExecutionAdapterError as exc:
            result.error = str(exc)
            result.completed_at = datetime.now(timezone.utc)
            return result

        url = f"{self._base_url(device, creds)}{path}"

        try:
            # httpx es async nativo: no necesita to_thread.
            async with httpx.AsyncClient(
                verify=settings.RESTCONF_VERIFY_TLS,
                timeout=settings.RESTCONF_TIMEOUT,
                auth=(creds.username, creds.password),
                headers={
                    "Accept": YANG_JSON,
                    "Content-Type": YANG_JSON,
                },
            ) as client:
                response = await client.request(method, url, json=body)

            error = self._extract_error(response)
            if error:
                result.status = ExecutionStatus.ERROR
                result.error = error
            else:
                result.status = ExecutionStatus.SUCCESS
                result.response = response.text[:2000] or None

        except httpx.TimeoutException as exc:
            result.status = ExecutionStatus.TIMEOUT
            result.error = f"timeout aplicando configuración: {exc}"
        except httpx.HTTPError as exc:
            result.status = ExecutionStatus.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            result.status = ExecutionStatus.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.completed_at = datetime.now(timezone.utc)

        return result

    async def rollback(
        self,
        plan: ExecutionPlan,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Revierte el cambio.

        RESTCONF no ofrece rollback atómico. La reversión depende de un
        backup previo, que debe aplicar el orquestador.
        """
        if plan.rollback_strategy == RollbackStrategy.CONFIG_BACKUP:
            return ExecutionResult(
                status=ExecutionStatus.ROLLBACK_SUCCESS,
                device_id=device.device_id,
                hostname=device.hostname,
                response="reversión por backup previo a cargo del orquestador",
                completed_at=datetime.now(timezone.utc),
            )

        return await super().rollback(plan, device)
