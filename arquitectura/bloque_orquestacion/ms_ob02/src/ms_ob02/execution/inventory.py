"""
Inventario de dispositivos de red y sus capacidades.

Funciones de solo lectura sobre PostgreSQL:
- Resuelve hostnames a dispositivos registrados.
- Obtiene las capacidades declaradas de cada dispositivo.
- Calcula la intersección de capacidades (comunes para cohortes).
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text

from ms_ob02.db.database import AsyncSessionLocal


# =====================================================
# MODELOS
# =====================================================

class DeviceInfo(BaseModel):
    """Información de un dispositivo del inventario."""
    device_id: UUID
    hostname: str
    vendor: Optional[str] = None
    platform: Optional[str] = None
    model: Optional[str] = None
    status: str
    last_verified_at: Optional[datetime] = None
    inventory_version: int = 1


# =====================================================
# CONSULTAS
# =====================================================

async def resolve_devices_by_hostname(hostnames: list[str]) -> list[DeviceInfo]:
    """
    Resuelve una lista de hostnames a dispositivos registrados.

    Los hostnames que no existan en `network_devices` se omiten del resultado.

    Args:
        hostnames: Lista de hostnames objetivo.

    Returns:
        Lista de DeviceInfo con los dispositivos encontrados.
    """
    if not hostnames:
        return []

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT device_id, hostname, vendor, model, status,
                       last_verified_at, inventory_version
                FROM network_devices
                WHERE hostname = ANY(:hostnames)
            """),
            {"hostnames": list(hostnames)},
        )
        rows = result.fetchall()

    return [
        DeviceInfo(
            device_id=row.device_id,
            hostname=row.hostname,
            vendor=row.vendor,
            platform=row.model,
            model=row.model,
            status=row.status,
            last_verified_at=row.last_verified_at,
            inventory_version=row.inventory_version or 1,
        )
        for row in rows
    ]


async def get_device_capabilities(device_ids: list[UUID]) -> dict[UUID, dict]:
    """
    Obtiene las capacidades declaradas de cada dispositivo.

    El dict resultante incluye la clave `active`, derivada del status
    del dispositivo en `network_devices` (ACTIVE → True, resto → False).

    Formato de cada valor:
        {
            "active": True,
            "cli": True,
            "ssh": True,
            "netconf": False,
            "candidate_config": True,
            ...
        }

    Args:
        device_ids: Lista de device_id.

    Returns:
        Dict {device_id: {capability: bool}}.
    """
    if not device_ids:
        return {}

    ids = [str(device_id) for device_id in device_ids]

    async with AsyncSessionLocal() as session:
        # Status de los dispositivos
        result = await session.execute(
            text("""
                SELECT device_id, status
                FROM network_devices
                WHERE device_id = ANY(:device_ids)
            """),
            {"device_ids": ids},
        )
        status_rows = result.fetchall()

        # Capacidades declaradas
        result = await session.execute(
            text("""
                SELECT device_id, capability, supported
                FROM device_capabilities
                WHERE device_id = ANY(:device_ids)
            """),
            {"device_ids": ids},
        )
        capability_rows = result.fetchall()

    # Base: todos los dispositivos con su estado activo
    capabilities: dict[UUID, dict] = {}
    for row in status_rows:
        capabilities[row.device_id] = {"active": row.status == "ACTIVE"}

    # Sobrescribir con las capacidades declaradas
    for row in capability_rows:
        device = capabilities.setdefault(row.device_id, {"active": False})
        # La columna es un ENUM de PostgreSQL; asyncpg devuelve el valor (str).
        capability = row.capability
        device[getattr(capability, "value", capability)] = bool(row.supported)

    return capabilities


async def get_common_capabilities(device_ids: list[UUID]) -> dict:
    """
    Calcula la intersección de capacidades entre varios dispositivos.

    Solo se consideran las capacidades que todos los dispositivos soportan.
    La clave `active` se excluye del cálculo.

    Args:
        device_ids: Lista de device_id.

    Returns:
        Dict {capability: True} con las capacidades comunes.
    """
    if not device_ids:
        return {}

    all_capabilities = await get_device_capabilities(device_ids)
    if not all_capabilities:
        return {}

    common: Optional[set[str]] = None
    for capabilities in all_capabilities.values():
        supported = {
            name
            for name, value in capabilities.items()
            if name != "active" and value
        }
        common = supported if common is None else (common & supported)

    return {capability: True for capability in (common or set())}
