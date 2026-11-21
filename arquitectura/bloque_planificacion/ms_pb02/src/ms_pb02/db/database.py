"""Acceso asíncrono a las tablas compartidas de planificación.

Las tablas de negocio pertenecen al modelo global IBNM; este módulo no crea
esquemas en producción y solamente consulta/actualiza los recursos definidos
en la documentación del proyecto.
"""

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ms_pb02.config.settings import settings


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Comprueba la disponibilidad de PostgreSQL al arrancar."""
    async with Session() as session:
        await session.execute(text("SELECT 1"))


async def close_db() -> None:
    await engine.dispose()

async def get_logical_task_try(task_id: UUID) -> int:
    """Devuelve el contador 'try' propio de MS-PB02 para esa tarea lógica."""
    async with Session() as session:
        result = await session.execute(
            text("SELECT try FROM logical_tasks WHERE task_id = :task_id"),
            {"task_id": str(task_id)},
        )
        value = result.scalar_one_or_none()
    return int(value) if value is not None else 1


async def increment_logical_task_try(task_id: UUID) -> int:
    """Incrementa atómicamente el contador 'try' y devuelve el nuevo valor."""
    async with Session.begin() as session:
        result = await session.execute(
            text(
                "UPDATE logical_tasks SET try = try + 1 "
                "WHERE task_id = :task_id RETURNING try"
            ),
            {"task_id": str(task_id)},
        )
        value = result.scalar_one()
    return int(value)


async def create_logical_task(policy_id: UUID, intent_id: UUID) -> UUID:
    task_id = uuid4()
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO logical_tasks
                    (task_id, policy_id, intent_id, status, generated_by, generated_at)
                VALUES
                    (:task_id, :policy_id, :intent_id, 'PROPOSED', 'MS-PB02', NOW())
                """
            ),
            {"task_id": str(task_id), "policy_id": str(policy_id), "intent_id": str(intent_id)},
        )
    return task_id

async def update_logical_task(
    task_id: UUID,
    *,
    status: str,
    task_json: dict[str, Any] | None = None,
    task_description: str | None = None,
    version: int | None = None,          # <-- NUEVO
) -> None:
    assignments = ["status = :status"]
    values: dict[str, Any] = {"task_id": str(task_id), "status": status}
    if task_json is not None:
        assignments.append("task_json = CAST(:task_json AS JSONB)")
        values["task_json"] = json.dumps(task_json, ensure_ascii=False)
    if task_description is not None:
        assignments.append("task_description = :task_description")
        values["task_description"] = task_description
    if version is not None:              # <-- NUEVO
        assignments.append("version = :version")
        values["version"] = version
    async with Session.begin() as session:
        await session.execute(
            text(f"UPDATE logical_tasks SET {', '.join(assignments)} WHERE task_id = :task_id"),
            values,
        )

        
async def append_registry(task_id: UUID, event_type: str, snapshot: dict[str, Any]) -> None:
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO logical_task_registry
                    (registry_id, task_id, event_type, task_snapshot, recorded_at)
                VALUES
                    (:registry_id, :task_id, :event_type, CAST(:snapshot AS JSONB), NOW())
                """
            ),
            {
                "registry_id": str(uuid4()),
                "task_id": str(task_id),
                "event_type": event_type,
                "snapshot": json.dumps(snapshot, ensure_ascii=False),
            },
        )


async def save_validation_layers(task_id: UUID, layers: dict[str, Any]) -> None:
    mapping = {
        "layer_1_semantic": "SEMANTIC",
        "layer_2_consistency": "CONSISTENCY",
        "layer_3_overlap": "OVERLAP",
        "layer_4_resources": "RESOURCE_CAPACITY",
        "layer_5_security": "SECURITY_COMPLIANCE",
    }
    async with Session.begin() as session:
        for name, layer in layers.items():
            result = layer["status"] if isinstance(layer, dict) else layer.status
            findings = layer.get("findings", []) if isinstance(layer, dict) else layer.findings
            await session.execute(
                text(
                    """
                    INSERT INTO logical_task_validations
                        (validation_id, task_id, validation_step, result,
                         error_detail, validated_at, validated_by)
                    VALUES
                        (:validation_id, :task_id, :validation_step, :result,
                         :error_detail, NOW(), 'MS-PB02')
                    """
                ),
                {
                    "validation_id": str(uuid4()),
                    "task_id": str(task_id),
                    "validation_step": mapping.get(name, name),
                    "result": result,
                    "error_detail": "; ".join(findings) or None,
                },
            )


async def load_validation_context() -> dict[str, Any]:
    """Carga contexto local y evidencia de dispositivos/reglas desde el SSoT."""
    result: dict[str, list[dict[str, Any]] | None] = {
        "existing_tasks": None,
        "network_resources": None,
        "network_capacity": None,
        "compliance_rules": None,
    }
    async with Session() as session:
        rows = await session.execute(
            text("SELECT task_id, task_json, status FROM logical_tasks")
        )
        result["existing_tasks"] = [dict(row) for row in rows.mappings().all()]

    async with httpx.AsyncClient(
        base_url=settings.SSOT_BASE_URL.rstrip("/"),
        timeout=settings.SSOT_TIMEOUT_SECONDS,
    ) as client:
        for key, path in (
            ("network_resources", "/api/v1/ssot/devices"),
            ("network_capacity", "/api/v1/ssot/capacity"),
            ("compliance_rules", "/api/v1/ssot/compliance-rules"),
        ):
            try:
                response = await client.get(path)
                response.raise_for_status()
                payload = response.json()
                result[key] = payload.get("items", [])
            except (httpx.HTTPError, ValueError):
                result[key] = None
    return result


async def find_task_context(task_id: UUID) -> dict[str, Any] | None:
    async with Session() as session:
        row = await session.execute(
            text(
                """
                SELECT lt.task_id, lt.policy_id, lt.intent_id, p.policy_json
                FROM logical_tasks lt
                JOIN policies p ON p.policy_id = lt.policy_id
                WHERE lt.task_id = :task_id
                """
            ),
            {"task_id": str(task_id)},
        )
        data = row.mappings().first()
        return dict(data) if data else None
