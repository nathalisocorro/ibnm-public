"""
Adaptador de ejecución NETCONF usando ncclient.

Aplica configuración estructurada en dispositivos que soportan NETCONF.
El formato esperado es `netconf_xml` y el protocolo `netconf`.

Soporta los dos formatos de payload:

- RPC completo: ``<rpc>...</rpc>`` → se envía tal cual
- Fragmento de config: ``<config>...</config>`` → se envuelve en
  ``<rpc><edit-config>...</edit-config></rpc>``

El acceso se realiza sobre SSH (paramiko) con validación de host key
contra ``known_hosts``.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from ncclient import manager
from ncclient.operations import RPCError
from ncclient.xml_ import to_ele

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


# Namespace base de NETCONF.
NETCONF_BASE_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"

# XML de discard-changes para revertir la configuración candidata.
_DISCARD_CHANGES = f"""
<discard-changes xmlns="{NETCONF_BASE_NS}"/>
"""


class NetconfAdapter(ExecutionAdapter):
    """
    Adaptador NETCONF basado en ncclient.

    Ejecuta un RPC de configuración sobre el dispositivo objetivo y
    detecta errores en la respuesta.
    """

    supported_formats = (ArtifactFormat.NETCONF_XML.value,)

    def __init__(self) -> None:
        self._connections: dict[str, object] = {}

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
                f"el adaptador NETCONF no soporta el formato "
                f"'{plan.artifact_format.value}'. "
                f"Soportados: {', '.join(self.supported_formats)}"
            )

        if plan.protocol != Protocol.NETCONF:
            raise ExecutionAdapterError(
                f"el adaptador NETCONF requiere el protocolo 'netconf', "
                f"pero el plan indica '{plan.protocol.value}'"
            )

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_payload(payload: str) -> str:
        """
        Normaliza el payload a un RPC completo.

        Si el payload ya es un ``<rpc>`` se devuelve tal cual. Si es un
        fragmento (por ejemplo ``<config>``) se envuelve en
        ``<rpc><edit-config>...</edit-config></rpc>``.

        Args:
            payload: Payload generado por el agente.

        Returns:
            RPC completo listo para enviar.
        """
        stripped = payload.strip()

        if stripped.startswith("<rpc"):
            return stripped

        return (
            f'<rpc xmlns="{NETCONF_BASE_NS}">'
            f"<edit-config>"
            f"{stripped}"
            f"</edit-config>"
            f"</rpc>"
        )

    @staticmethod
    def _extract_rpc_error(response) -> Optional[str]:
        """
        Extrae el error de un RPC si la respuesta lo contiene.

        Args:
            response: Respuesta de ncclient.

        Returns:
            Texto del error, o None si la respuesta fue correcta.
        """
        if response is None:
            return "respuesta vacía del dispositivo"

        if not response.ok:
            error_text = getattr(response, "error", None)
            if error_text:
                return str(error_text)
            return "el dispositivo rechazó la configuración"

        return None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def _connect(self, device: DeviceTarget):
        """
        Abre una sesión NETCONF sobre SSH.

        Args:
            device: Dispositivo objetivo.

        Returns:
            Sesión de ncclient activa.

        Raises:
            ExecutionAdapterError: si la conexión falla.
        """
        creds = resolve_credentials(device, "netconf")
        host = device.management_ip or device.hostname

        params = {
            "host": host,
            "port": creds.port,
            "username": creds.username,
            "password": creds.password,
            "hostkey_verify": settings.NETCONF_HOST_KEY_VALIDATION,
            "timeout": settings.NETCONF_TIMEOUT,
        }

        device_params = {"name": creds.device_type} if creds.device_type else None
        if device_params:
            params["device_params"] = device_params

        try:
            connection = manager.connect(**params)
        except Exception as exc:
            raise ExecutionAdapterError(
                f"error conectando por NETCONF a '{device.hostname}': "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self._connections[device.hostname] = connection
        return connection

    def _disconnect(self, hostname: str) -> None:
        """Cierra la sesión NETCONF de un dispositivo si existe."""
        connection = self._connections.pop(hostname, None)
        if connection is not None:
            try:
                connection.close_session()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass

    def disconnect_all(self) -> None:
        """Cierra todas las sesiones abiertas."""
        for hostname in list(self._connections.keys()):
            self._disconnect(hostname)

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------
    def _send_rpc(self, connection, rpc_xml: str):
        """
        Envía un RPC al dispositivo.

        Para edit-config se usa edit_config() de ncclient, pasándole el
        elemento <config> COMPLETO en el namespace NETCONF base (ncclient
        valida el root con validated_element y rechaza cualquier otro).

        Si el target es candidate, se envía un <commit/> posterior para
        aplicar el cambio a running. Sin ese commit, edit-config deja el
        cambio pendiente en candidate y el ACK_OK es engañoso.

        El <config> y el <target> se localizan por local-name() para no
        depender de que el LLM los emita con un namespace explícito.
        """
        from lxml import etree

        NS_NC = "urn:ietf:params:xml:ns:netconf:base:1.0"
        NS = {"nc": NS_NC}

        # Parsear el XML
        try:
            rpc = to_ele(rpc_xml.strip())
        except Exception as exc:
            raise ExecutionAdapterError(
                f"XML del comando no es parseable: {type(exc).__name__}: {exc}"
            ) from exc

        # Desenvolver <rpc>...</rpc> si el LLM lo incluyó
        if rpc.tag in (f"{{{NS_NC}}}rpc", "rpc"):
            children = list(rpc)
            if not children:
                raise ExecutionAdapterError(
                    "RPC vacío: el <rpc> no contiene ninguna operación"
                )
            rpc = children[0]

        tag = rpc.tag.split("}")[-1] if "}" in rpc.tag else rpc.tag

        # Debug: ver qué llegó realmente al adaptador
        print(
            f"[netconf] rpc.tag={rpc.tag} | children="
            f"{[c.tag for c in rpc]}",
            flush=True,
        )

        # ------------------------------------------------------------------
        # edit-config
        # ------------------------------------------------------------------
        if tag == "edit-config":
            # --- target: buscar por local-name, no por namespace ---
            target = "candidate"
            target_matches = rpc.xpath(".//*[local-name()='target']")
            if target_matches:
                for child in target_matches[0]:
                    target = (
                        child.tag.split("}")[-1]
                        if "}" in child.tag
                        else child.tag
                    )
                    break

            # --- config: buscar por local-name, no por namespace ---
            config_matches = rpc.xpath(".//*[local-name()='config']")
            if not config_matches:
                raise ExecutionAdapterError(
                    f"edit-config recibido sin <config>. "
                    f"rpc.tag={rpc.tag}, "
                    f"children={[c.tag for c in rpc]}"
                )
            config_el = config_matches[0]

            # Serializar el <config>. Si el LLM no le puso xmlns explícito,
            # forzamos el namespace NETCONF para que ncclient lo valide.
            config_xml = etree.tostring(config_el, encoding="unicode")
            if f'xmlns="{NS_NC}"' not in config_xml:
                # Insertar el xmlns NETCONF en el root <config>
                config_el.set(
                    "{http://www.w3.org/2000/xmlns/}xmlns", NS_NC
                )
                config_xml = etree.tostring(config_el, encoding="unicode")

            print(
                f"[netconf] edit-config target={target} "
                f"len={len(config_xml)} chars",
                flush=True,
            )
            print(
                f"[netconf] config a enviar: {config_xml[:500]}"
                f"{'...' if len(config_xml) > 500 else ''}",
                flush=True,
            )

            try:
                result = connection.edit_config(
                    target=target, config=config_xml
                )
                print(
                    f"[netconf] edit-config OK (target={target})",
                    flush=True,
                )
            except Exception as exc:
                raise ExecutionAdapterError(
                    f"edit_config falló (target={target}): "
                    f"{type(exc).__name__}: {exc} | "
                    f"config={config_xml[:300]}"
                ) from exc

            # Si el target es candidate, aplicar el cambio a running
            if target == "candidate":
                try:
                    commit_result = connection.commit()
                    print(
                        "[netconf] commit OK (candidate → running)",
                        flush=True,
                    )
                except Exception as exc:
                    raise ExecutionAdapterError(
                        f"commit falló tras edit-config: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                return commit_result

            return result

        # ------------------------------------------------------------------
        # Otros RPCs: dispatch normal
        # ------------------------------------------------------------------
        print(f"[netconf] dispatch rpc tag={tag}", flush=True)
        return connection.dispatch(rpc)



    async def apply(
        self,
        plan: ExecutionPlan,
        command: str,
        device: DeviceTarget,
    ) -> ExecutionResult:
        """
        Aplica la configuración NETCONF en el dispositivo.

        Args:
            plan: Plan de ejecución.
            command: Payload XML con la configuración.
            device: Dispositivo objetivo.

        Returns:
            ExecutionResult con el resultado.
        """
        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            device_id=device.device_id,
            hostname=device.hostname,
        )

        rpc_xml = self._wrap_payload(command)

        try:
            connection = self._connect(device)
        except ExecutionAdapterError as exc:
            result.error = str(exc)
            result.completed_at = datetime.now(timezone.utc)
            return result

        try:
            # ncclient es bloqueante: se ejecuta en un hilo aparte.
            response = await asyncio.to_thread(self._send_rpc, connection, rpc_xml)

            error = self._extract_rpc_error(response)
            if error:
                result.status = ExecutionStatus.ERROR
                result.error = error
            else:
                result.status = ExecutionStatus.SUCCESS
                result.response = getattr(response, "data_xml", None)

        except RPCError as exc:
            result.status = ExecutionStatus.ERROR
            result.error = f"rpc-error: {exc}"
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
        Revierte el cambio según la estrategia del plan.

        - ``confirmed-commit``: el commit confirmado expiró solo, no
          requiere acción sobre el dispositivo.
        - ``candidate-discard``: envía ``<discard-changes/>`` para
          descartar la configuración candidata.
        """
        if plan.rollback_strategy == RollbackStrategy.CONFIRMED_COMMIT:
            return ExecutionResult(
                status=ExecutionStatus.ROLLBACK_SUCCESS,
                device_id=device.device_id,
                hostname=device.hostname,
                response="el commit confirmado expiró automáticamente",
                completed_at=datetime.now(timezone.utc),
            )

        if plan.rollback_strategy == RollbackStrategy.CANDIDATE_DISCARD:
            result = ExecutionResult(
                status=ExecutionStatus.ERROR,
                device_id=device.device_id,
                hostname=device.hostname,
            )

            try:
                connection = self._connect(device)
            except ExecutionAdapterError as exc:
                result.error = str(exc)
                result.completed_at = datetime.now(timezone.utc)
                return result

            try:
                response = await asyncio.to_thread(
                    self._send_rpc, connection, _DISCARD_CHANGES
                )
                error = self._extract_rpc_error(response)
                if error:
                    result.status = ExecutionStatus.ROLLBACK_ERROR
                    result.error = error
                else:
                    result.status = ExecutionStatus.ROLLBACK_SUCCESS
                    result.response = getattr(response, "data_xml", None)
            except Exception as exc:
                result.status = ExecutionStatus.ROLLBACK_ERROR
                result.error = f"{type(exc).__name__}: {exc}"
            finally:
                self._disconnect(device.hostname)
                result.completed_at = datetime.now(timezone.utc)

            return result

        return await super().rollback(plan, device)
