"""Persistencia compartida del ciclo de vida de atomic_tasks."""

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ms_ob01.config.settings import settings


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with Session() as session:
        await session.execute(text("SELECT 1"))


async def close_db() -> None:
    await engine.dispose()


async def create_atomic_task(event) -> UUID:
    atomic_task_id = uuid4()
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO atomic_tasks
                    (atomic_task_id, logical_task_id, policy_id, intent_id,
                     status, try, version, generated_by, generated_at, last_updated)
                VALUES
                    (:atomic_task_id, :logical_task_id, :policy_id, :intent_id,
                     'PENDING', 1, 1, 'AGENT_AI5', NOW(), NOW())
                """
            ),
            {
                "atomic_task_id": str(atomic_task_id),
                "logical_task_id": str(event.task_id),
                "policy_id": str(event.policy_id),
                "intent_id": str(event.intent_id),
            },
        )
    return atomic_task_id


async def update_atomic_task(
    atomic_task_id: UUID,
    *,
    status: str,
    task_json: dict[str, Any] | None = None,
    task_description: str | None = None,
    required_capabilities: dict[str, Any] | None = None,
    version: int | None = None,
) -> None:
    assignments = ["status = :status", "last_updated = NOW()"]
    values: dict[str, Any] = {"atomic_task_id": str(atomic_task_id), "status": status}
    for column, value in (
        ("task_json", task_json),
        ("required_capabilities", required_capabilities),
    ):
        if value is not None:
            assignments.append(f"{column} = CAST(:{column} AS JSONB)")
            values[column] = json.dumps(value, ensure_ascii=False, default=str)
    if task_description is not None:
        assignments.append("task_description = :task_description")
        values["task_description"] = task_description
    if version is not None:
        assignments.append("version = :version")
        values["version"] = version
    async with Session.begin() as session:
        await session.execute(
            text(f"UPDATE atomic_tasks SET {', '.join(assignments)} WHERE atomic_task_id = :atomic_task_id"),
            values,
        )


async def append_registry(atomic_task_id: UUID, event_type: str, snapshot: dict[str, Any]) -> None:
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO atomic_task_registry
                    (registry_id, atomic_task_id, event_type, task_snapshot, recorded_at)
                VALUES
                    (:registry_id, :atomic_task_id, :event_type,
                     CAST(:snapshot AS JSONB), NOW())
                """
            ),
            {
                "registry_id": str(uuid4()),
                "atomic_task_id": str(atomic_task_id),
                "event_type": event_type,
                "snapshot": json.dumps(snapshot, ensure_ascii=False, default=str),
            },
        )


async def get_logical_task_json(logical_task_id: UUID) -> dict[str, Any]:
    """Obtiene la tarea lógica original para regenerar una tarea atómica."""
    async with Session() as session:
        result = await session.execute(
            text("SELECT task_json FROM logical_tasks WHERE task_id = :task_id"),
            {"task_id": str(logical_task_id)},
        )
        row = result.first()
    if row is None or not isinstance(row[0], dict):
        raise ValueError(f"No existe task_json para logical_task_id={logical_task_id}")
    return row[0]


async def increment_atomic_task_try(atomic_task_id: UUID) -> int:
    """Incrementa el contador de regeneraciones respetando la configuración."""

    max_tries = settings.MAX_REGENERATION_TRIES

    async with Session.begin() as session:
        result = await session.execute(
            text(
                """
                UPDATE atomic_tasks
                   SET try = LEAST(COALESCE(try, 0) + 1, :max_tries),
                       last_updated = NOW()
                 WHERE atomic_task_id = :atomic_task_id
             RETURNING try
                """
            ),
            {
                "atomic_task_id": str(atomic_task_id),
                "max_tries": max_tries,
            },
        )
        row = result.first()

    if row is None:
        raise ValueError(
            f"No existe atomic_task_id={atomic_task_id}"
        )

    return int(row[0])

async def get_atomic_task_attempt_count(atomic_task_id: UUID) -> int:
    async with Session() as session:
        result = await session.execute(
            text("SELECT COALESCE(try, 0) FROM atomic_tasks WHERE atomic_task_id = :atomic_task_id"),
            {"atomic_task_id": str(atomic_task_id)},
        )
        row = result.first()
    if row is None:
        raise ValueError(f"No existe atomic_task_id={atomic_task_id}")
    return int(row[0])
