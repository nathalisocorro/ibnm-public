
"""Cliente HTTP para consultar la configuración de dispositivos en MS-V03."""

from typing import Any

import httpx

from ms_ob01.config.settings import settings


async def get_device_config(device_id: str) -> dict:
    """Consulta la configuración actual de un dispositivo en SSoT."""

    if not device_id or not device_id.strip():
        raise ValueError("device_id es obligatorio para consultar SSoT.")

    url = (
        f"{settings.SSOT_BASE_URL.rstrip('/')}"
        f"/api/v1/ssot/devices/{device_id}/config"
    )

    timeout = httpx.Timeout(settings.SSOT_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ValueError(
            "MS-V03 devolvió una respuesta de configuración inválida."
        )

    return data


async def get_device(device_reference: str) -> dict[str, Any]:
    """Busca un dispositivo por resource_id, hostname o nombre en el SSoT."""
    if not device_reference or not device_reference.strip():
        raise ValueError("device_reference es obligatorio para consultar SSoT.")

    async with httpx.AsyncClient(
        base_url=settings.SSOT_BASE_URL.rstrip("/"),
        timeout=settings.SSOT_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get("/api/v1/ssot/devices")
        response.raise_for_status()
        payload = response.json()

    devices = payload.get("items", []) if isinstance(payload, dict) else []
    reference = device_reference.strip()
    for device in devices:
        if not isinstance(device, dict):
            continue
        if reference in {
            device.get("resource_id"),
            device.get("hostname"),
            device.get("name"),
        }:
            required = ("resource_id", "vendor", "platform", "os_version", "status")
            missing = [field for field in required if not str(device.get(field) or "").strip()]
            if missing:
                raise ValueError(
                    "DEVICE_METADATA_NOT_FOUND: "
                    f"{reference} no contiene {', '.join(missing)} en el SSoT."
                )
            return device

    raise ValueError(f"DEVICE_METADATA_NOT_FOUND: no existe {reference} en el SSoT.")


async def get_device_context(device_reference: str) -> dict[str, Any]:
    """Devuelve el inventario y la configuraci\u00f3n observada del dispositivo."""
    device = await get_device(device_reference)
    device_id = str(device["resource_id"])
    return {
        "device": device,
        "configuration": await get_device_config(device_id),
    }
