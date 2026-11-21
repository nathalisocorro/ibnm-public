"""
Resolución de credenciales de acceso a dispositivos.

Las credenciales se resuelven desde variables de entorno, con prioridad:

1. Override por hostname en ``{PREFIX}_DEVICE_CREDENTIALS`` (JSON)
2. Variables globales ``{PREFIX}_*``

Nunca se almacenan contraseñas en la base de datos: ``network_devices``
solo guarda un ``secret_ref`` que apunta al gestor de secretos.
"""

import json
from typing import Optional

from pydantic import BaseModel

from ms_ob02.config.settings import settings
from ms_ob02.execution.base import DeviceTarget, ExecutionAdapterError


# =====================================================
# TRANSPORTES
# =====================================================

class Transport(BaseModel):
    """Define cómo se acceden las credenciales de un transporte."""
    name: str
    prefix: str
    default_port: int
    requires_username: bool = True
    requires_password: bool = True


TRANSPORTS: dict[str, Transport] = {
    "ssh_cli": Transport(
        name="ssh_cli",
        prefix="NETMIKO",
        default_port=22,
    ),
    "netconf": Transport(
        name="netconf",
        prefix="NETCONF",
        default_port=830,
    ),
    "restconf": Transport(
        name="restconf",
        prefix="RESTCONF",
        default_port=443,
    ),
    "ansible": Transport(
        name="ansible",
        prefix="ANSIBLE",
        default_port=0,
        requires_username=False,
        requires_password=False,
    ),
}


# =====================================================
# MODELO
# =====================================================

class DeviceCredentials(BaseModel):
    """Credenciales de acceso a un dispositivo."""
    username: str = ""
    password: str = ""
    secret: Optional[str] = None
    port: int = 22
    device_type: Optional[str] = None
    extra: dict = {}


# =====================================================
# RESOLUCIÓN
# =====================================================

def _device_overrides(transport) -> dict:
    """
    Devuelve {hostname: override_data_del_transporte}.

    Prioridad:
      1. settings.DEVICE_CREDENTIALS (JSON unificado, anidado por transporte).
         Estructura: {"<hostname>": {"<transporte>": {...}, ...}}
         El lookup del transporte es case-insensitive: acepta "netmiko",
         "NETMIKO", "Netmiko", etc. (transport.prefix está en mayúsculas).
      2. settings.{PREFIX}_DEVICE_CREDENTIALS (compatibilidad con el esquema
         anterior, JSON plano indexado por hostname).

    El resultado se usa con .get(device.hostname, {}) en resolve_credentials.
    """
    # 1) JSON unificado (prioritario)
    unified_raw = getattr(settings, "DEVICE_CREDENTIALS", None)
    if unified_raw:
        try:
            # Puede llegar como str (si settings usa Optional[str]) o como
            # dict (si usa dict = {}). Cubrimos ambos casos.
            data = (
                json.loads(unified_raw)
                if isinstance(unified_raw, str)
                else unified_raw
            )
            prefix_lower = transport.prefix.lower()
            overrides = {}
            for hostname, transports in data.items():
                if not isinstance(transports, dict):
                    continue
                # Normalizar las claves del sub-árbol a minúsculas
                transports_lower = {
                    str(k).lower(): v for k, v in transports.items()
                }
                overrides[hostname] = transports_lower.get(prefix_lower) or {}
            return overrides
        except (json.JSONDecodeError, TypeError) as exc:
            print(
                f"[credentials] DEVICE_CREDENTIALS no es JSON válido: {exc}. "
                f"Se ignora y se usa el fallback por transporte.",
                flush=True,
            )

    # 2) Fallback: esquema anterior por transporte
    legacy_raw = getattr(
        settings, f"{transport.prefix}_DEVICE_CREDENTIALS", None
    )
    if not legacy_raw:
        return {}
    try:
        return (
            json.loads(legacy_raw)
            if isinstance(legacy_raw, str)
            else legacy_raw
        )
    except (json.JSONDecodeError, TypeError):
        return {}
    
def resolve_credentials(
    device: DeviceTarget,
    transport_name: str,
) -> DeviceCredentials:
    """
    Resuelve las credenciales de un dispositivo para un transporte.

    Prioridad:
        1. Override por hostname en ``{PREFIX}_DEVICE_CREDENTIALS``
        2. Variables globales ``{PREFIX}_*``

    Args:
        device: Dispositivo objetivo.
        transport_name: Nombre del transporte (ssh_cli, netconf, ...).

    Returns:
        DeviceCredentials con los datos de acceso.

    Raises:
        ExecutionAdapterError: si el transporte no existe o faltan
            credenciales obligatorias.
    """
    transport = TRANSPORTS.get(transport_name)
    if transport is None:
        available = ", ".join(sorted(TRANSPORTS))
        raise ExecutionAdapterError(
            f"transporte desconocido: '{transport_name}'. Disponibles: {available}"
        )

    override = _device_overrides(transport).get(device.hostname, {})
    if not override:
        print(
            f"[credentials] sin override para '{device.hostname}' "
            f"en transporte '{transport.prefix}'; usando globales",
            flush=True,
        )
    username = override.get("username") or getattr(
        settings, f"{transport.prefix}_USERNAME", ""
    )
    password = override.get("password") or getattr(
        settings, f"{transport.prefix}_PASSWORD", ""
    )
    secret = override.get("secret") or getattr(
        settings, f"{transport.prefix}_SECRET", ""
    ) or None

    # Perfil de plataforma: override > mapeo por platform > default global
    device_type = override.get("device_type") or getattr(
        settings, f"{transport.prefix}_DEVICE_TYPE", ""
    ) or None
    port = int(
        override.get("port")
        or getattr(settings, f"{transport.prefix}_PORT", transport.default_port)
        or transport.default_port
    )

    if transport.requires_username and not username:
        raise ExecutionAdapterError(
            f"faltan credenciales para '{device.hostname}' en el transporte "
            f"'{transport_name}'. Define {transport.prefix}_USERNAME y "
            f"{transport.prefix}_PASSWORD, o un override en "
            f"{transport.prefix}_DEVICE_CREDENTIALS."
        )

    if transport.requires_password and not password:
        raise ExecutionAdapterError(
            f"faltan credenciales para '{device.hostname}' en el transporte "
            f"'{transport_name}'. Define {transport.prefix}_PASSWORD, o un "
            f"override en {transport.prefix}_DEVICE_CREDENTIALS."
        )

    return DeviceCredentials(
        username=username,
        password=password,
        secret=secret,
        port=port,
        device_type=device_type,
        extra={k: v for k, v in override.items() if k not in (
            "username", "password", "secret", "port", "device_type",
        )},
    )
