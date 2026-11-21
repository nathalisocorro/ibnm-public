"""Herramienta CrewAI para consultar el SSoT de dispositivos y compliance."""

import json
from typing import Type

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ms_pb02.config.settings import settings


class SSoTQueryInput(BaseModel):
    resource: str = Field(
        description="Recurso a consultar: devices, capacity, compliance_rules o all."
    )


class SSoTQueryTool(BaseTool):
    name: str = "ssot_query"
    description: str = (
        "Consulta el SSoT HTTP para obtener dispositivos, capacidades y reglas de compliance. "
        "Usa resource=devices, resource=capacity, resource=compliance_rules o resource=all."
    )
    args_schema: Type[BaseModel] = SSoTQueryInput

    def _run(self, resource: str) -> str:
        paths = {
            "devices": "/api/v1/ssot/devices",
            "capacity": "/api/v1/ssot/capacity",
            "compliance_rules": "/api/v1/ssot/compliance-rules",
        }
        if resource == "all":
            selected = paths
        elif resource in paths:
            selected = {resource: paths[resource]}
        else:
            raise ValueError("resource debe ser devices, capacity, compliance_rules o all.")

        result: dict[str, object] = {}
        with httpx.Client(
            base_url=settings.SSOT_BASE_URL.rstrip("/"),
            timeout=settings.SSOT_TIMEOUT_SECONDS,
        ) as client:
            for name, path in selected.items():
                response = client.get(path)
                response.raise_for_status()
                result[name] = response.json().get("items", [])
        return json.dumps(result, ensure_ascii=False)
