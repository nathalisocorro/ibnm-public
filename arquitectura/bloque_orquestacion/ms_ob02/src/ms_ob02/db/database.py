"""
Conexión asíncrona a PostgreSQL usando SQLModel + SQLAlchemy async.
Incluye dos engines:
- engine principal (con pool) para el Flow y los servicios.
- engine dedicado (NullPool) para las herramientas de CrewAI.
"""

import hashlib
from uuid import UUID, uuid4
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from ms_ob02.config.settings import settings
from ms_ob02.db.modelos_tablas_BD import Command, ExecutionPlanRecord
from ms_ob02.execution.decision_models import (
    ArtifactFormat,
    ExecutionPlan,
    Executor,
    Protocol,
    RollbackStrategy,
)
from datetime import datetime, date
from enum import Enum
from uuid import UUID

# =====================================================
# URL de conexión asíncrona
# =====================================================

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)


# =====================================================
# ENGINE PRINCIPAL (con pool) - para Flow y servicios
# =====================================================

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# =====================================================
# ENGINE DEDICADO PARA HERRAMIENTAS (NullPool)
# =====================================================
# NullPool deshabilita el pooling: cada llamada abre y cierra su propia
# conexión en el event loop actual, evitando el error
# "Future attached to a different loop".

_tool_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)

_ToolSessionLocal = async_sessionmaker(
    _tool_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# =====================================================
# Dependencias y ciclo de vida
# =====================================================

async def get_session() -> AsyncSession:
    """Dependencia para obtener una sesión de base de datos (engine principal)."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Inicializa la base de datos creando las tablas."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def close_db():
    """Cierra las conexiones a la base de datos."""
    await engine.dispose()
    await _tool_engine.dispose()


# =====================================================
# FUNCIONES DEL FLOW (usan el engine principal con pool)
# =====================================================

async def search_knowledge_base(
    query: str,
    vendor: str,
    platform: str,
    technology: Optional[str] = None,
    limit: int = 5,
) -> list:
    """
    Busca en la base de conocimiento usando pgvector.
    Versión para el Flow (engine principal con pool).
    """
    import ollama

    client = ollama.Client(host=settings.OLLAMA_BASE_URL)
    response = client.embeddings(
        model=settings.OLLAMA_EMBED_MODEL,
        prompt=f"search_query: {query}",
    )
    query_embedding = response["embedding"]

    sql = """
        SELECT id, source, chunk_text, vendor, platform, technology,
               1 - (embedding <=> :query_embedding) as score
        FROM knowledge_chunks
        WHERE vendor = :vendor AND platform = :platform
    """
    params = {
        "query_embedding": str(query_embedding),
        "vendor": vendor,
        "platform": platform,
    }
    if technology:
        sql += " AND technology = :technology"
        params["technology"] = technology
    sql += " ORDER BY embedding <=> :query_embedding LIMIT :limit"
    params["limit"] = limit

    async with AsyncSessionLocal() as session:
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    return [
        {
            "chunk_id": row.id,
            "source": row.source,
            "chunk_text": row.chunk_text,
            "vendor": row.vendor,
            "platform": row.platform,
            "technology": row.technology,
            "score": row.score,
        }
        for row in rows
    ]

from datetime import datetime, date
from enum import Enum
from uuid import UUID


def _json_safe(obj):
    """Convierte objetos no serializables por json.dumps a tipos nativos."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return obj

async def save_execution_plan(plan, atomic_task_id=None) -> None:
    """Persiste un ExecutionPlan del motor de decisión en execution_plans.

    Firma compatible con la llamada del consumer:
        await save_execution_plan(plan, event.atomic_task_id)

    - `plan.atomic_task_id` se usa si existe.
    - `atomic_task_id` (segundo argumento) actúa como fallback.
    - device_ids y decision_trace se convierten con _json_safe porque
      asyncpg usa json.dumps estándar y este no serializa UUID ni Enum.
    """
    resolved_atomic_task_id = getattr(plan, "atomic_task_id", None) or atomic_task_id

    if resolved_atomic_task_id is None:
        raise ValueError(
            "save_execution_plan: no hay atomic_task_id ni en plan ni en el argumento"
        )

    record = ExecutionPlanRecord(
        plan_id=plan.plan_id,
        atomic_task_id=resolved_atomic_task_id,
        device_ids=_json_safe(plan.device_ids),
        artifact_format=plan.artifact_format,
        protocol=plan.protocol,
        executor=plan.executor,
        rollback_strategy=plan.rollback_strategy,
        requires_approval=plan.requires_approval,
        fallback_used=plan.fallback_used,
        inventory_version=plan.inventory_version,
        decision_trace=_json_safe(plan.decision_trace),
    )

    async with AsyncSessionLocal() as session:
        session.add(record)
        await session.commit()

    print(
        f"[db] execution_plan guardado: {plan.plan_id} "
        f"(atomic_task_id={resolved_atomic_task_id})",
        flush=True,
    )


async def get_execution_plan(plan_id: UUID) -> ExecutionPlan | None:
    """
    Lee un ExecutionPlan por su plan_id.

    Args:
        plan_id: UUID del plan.

    Returns:
        ExecutionPlan reconstruido, o None si no existe.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT plan_id, device_ids, artifact_format, protocol, executor,
                       rollback_strategy, requires_approval, fallback_used,
                       inventory_version, decision_trace
                FROM execution_plans
                WHERE plan_id = :plan_id
            """),
            {"plan_id": str(plan_id)},
        )
        row = result.fetchone()

    if not row:
        return None

    return ExecutionPlan(
        plan_id=row.plan_id,
        device_ids=row.device_ids,
        artifact_format=ArtifactFormat(row.artifact_format),
        protocol=Protocol(row.protocol),
        executor=Executor(row.executor),
        rollback_strategy=RollbackStrategy(row.rollback_strategy),
        requires_approval=row.requires_approval,
        fallback_used=row.fallback_used,
        inventory_version=row.inventory_version,
        decision_trace=row.decision_trace,
    )


async def list_execution_plans(atomic_task_id: UUID) -> list[ExecutionPlan]:
    """
    Lista los planes de ejecución de una tarea atómica.

    Args:
        atomic_task_id: UUID de la tarea atómica.

    Returns:
        Lista de ExecutionPlan (uno por cohorte generada).
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT plan_id, device_ids, artifact_format, protocol, executor,
                       rollback_strategy, requires_approval, fallback_used,
                       inventory_version, decision_trace
                FROM execution_plans
                WHERE atomic_task_id = :atomic_task_id
                ORDER BY created_at
            """),
            {"atomic_task_id": str(atomic_task_id)},
        )
        rows = result.fetchall()

    return [
        ExecutionPlan(
            plan_id=row.plan_id,
            device_ids=row.device_ids,
            artifact_format=ArtifactFormat(row.artifact_format),
            protocol=Protocol(row.protocol),
            executor=Executor(row.executor),
            rollback_strategy=RollbackStrategy(row.rollback_strategy),
            requires_approval=row.requires_approval,
            fallback_used=row.fallback_used,
            inventory_version=row.inventory_version,
            decision_trace=row.decision_trace,
        )
        for row in rows
    ]


async def save_command_execution(
    command_id: UUID,
    attempt_number: int,
    ack_status: str,
    device_id: Optional[UUID] = None,
    error_message: Optional[str] = None,
    response_payload: Optional[str] = None,
) -> UUID:
    """
    Registra el resultado de una ejecución de comando.

    Args:
        command_id: UUID del comando ejecutado.
        attempt_number: Número de intento (1-3).
        ack_status: Resultado (SUCCESS, ERROR, TIMEOUT).
        device_id: Dispositivo donde se ejecutó.
        error_message: Mensaje de error opcional.
        response_payload: Respuesta del dispositivo opcional.

    Returns:
        execution_id: UUID de la ejecución registrada.
    """
    from ms_ob02.db.modelos_tablas_BD import AckStatus, CommandExecution

    execution_id = uuid4()

    async with AsyncSessionLocal() as session:
        execution = CommandExecution(
            execution_id=execution_id,
            command_id=command_id,
            attempt_number=attempt_number,
            ack_status=AckStatus(ack_status),
            device_id=device_id,
            error_message=error_message,
            response_payload=response_payload,
        )
        session.add(execution)
        await session.commit()

    return execution_id


async def get_execution_devices(
    device_ids: list[UUID],
) -> list[dict]:
    """
    Resuelve los dispositivos objetivo con sus datos de conexión.

    Args:
        device_ids: Lista de device_id.

    Returns:
        Lista de dicts con device_id, hostname, management_ip, vendor, platform.
    """
    if not device_ids:
        return []

    ids = [str(device_id) for device_id in device_ids]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT device_id, hostname, management_ip, vendor, model, status
                FROM network_devices
                WHERE device_id = ANY(:device_ids)
            """),
            {"device_ids": ids},
        )
        rows = result.fetchall()

    return [
        {
            "device_id": row.device_id,
            "hostname": row.hostname,
            "management_ip": row.management_ip,
            "vendor": row.vendor,
            "platform": row.model,
            "status": row.status,
        }
        for row in rows
    ]


async def get_successful_execution(
    command_id: UUID,
    device_id: UUID,
) -> bool:
    """
    Verifica si el comando ya se ejecutó con éxito en el dispositivo.

    Se usa para idempotencia: si el proceso muere después de ejecutar
    pero antes de confirmar el offset, al reiniciar se reprocesaría el
    mensaje. Esta comprobación evita repetir la ejecución.

    Args:
        command_id: UUID del comando.
        device_id: UUID del dispositivo.

    Returns:
        True si ya existe una ejecución exitosa.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT 1 FROM command_executions
                WHERE command_id = :command_id
                  AND device_id = :device_id
                  AND ack_status = 'SUCCESS'
                LIMIT 1
            """),
            {"command_id": str(command_id), "device_id": str(device_id)},
        )
        return result.fetchone() is not None


async def count_command_executions(command_id: UUID) -> int:
    """
    Cuenta los intentos de ejecución previos de un comando.

    Args:
        command_id: UUID del comando.

    Returns:
        Número de ejecuciones registradas.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM command_executions WHERE command_id = :command_id"),
            {"command_id": str(command_id)},
        )
        return result.scalar() or 0


async def update_command_status(
    command_id: UUID,
    status: str,
) -> bool:
    """Actualiza el status de un comando en PostgreSQL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("UPDATE commands SET status = :status WHERE command_id = :command_id"),
            {"status": status, "command_id": command_id},
        )
        await session.commit()
        return result.rowcount > 0


async def save_command_result(
    atomic_task_id: UUID,
    logical_task_id: UUID,
    policy_id: UUID,
    intent_id: UUID,
    vendor: str,
    platform: str,
    format: str,
    command_payload: str,
    status: str = "PENDING",
    execution_plan_id: Optional[UUID] = None,
    command_id: Optional[UUID] = None,
    attempt_count: int = 1,
) -> UUID:
    """
    Guarda el resultado de la generación de comandos en PostgreSQL.

    Args:
        command_id: UUID del comando. Si no se pasa, se genera.
        attempt_count: Número del intento que produjo el comando (1-3).
        execution_plan_id: Plan de ejecución del que proviene.
    """
    from ms_ob02.db.modelos_tablas_BD import CommandFormat, CommandStatus

    if command_id is None:
        command_id = uuid4()
    validation_hash = hashlib.sha256(command_payload.encode()).hexdigest()

    async with AsyncSessionLocal() as session:
        command = Command(
            command_id=command_id,
            atomic_task_id=atomic_task_id,
            logical_task_id=logical_task_id,
            policy_id=policy_id,
            intent_id=intent_id,
            execution_plan_id=execution_plan_id,
            vendor=vendor,
            format=CommandFormat(format),
            command_payload=command_payload,
            validation_hash=validation_hash,
            status=CommandStatus(status),
            attempt_count=attempt_count,
        )
        session.add(command)
        await session.commit()

    return command_id


# =====================================================
# FUNCIÓN PARA HERRAMIENTAS (usa el engine dedicado con NullPool)
# =====================================================

async def search_knowledge_base_tool(
    query: str,
    vendor: str,
    platform: str,
    technology: Optional[str] = None,
    limit: int = 5,
) -> list:
    """
    Busca en la base de conocimiento usando pgvector.
    Versión para herramientas de CrewAI (engine dedicado con NullPool).
    Esta versión evita el error "Future attached to a different loop"
    porque no reutiliza conexiones entre event loops.
    """
    import ollama

    client = ollama.Client(host=settings.OLLAMA_BASE_URL)
    response = client.embeddings(
        model=settings.OLLAMA_EMBED_MODEL,
        prompt=f"search_query: {query}",
    )
    query_embedding = response["embedding"]

    sql = """
        SELECT id, source, chunk_text, vendor, platform, technology,
               1 - (embedding <=> :query_embedding) as score
        FROM knowledge_chunks
        WHERE vendor = :vendor AND platform = :platform
    """
    params = {
        "query_embedding": str(query_embedding),
        "vendor": vendor,
        "platform": platform,
    }
    if technology:
        sql += " AND technology = :technology"
        params["technology"] = technology
    sql += " ORDER BY embedding <=> :query_embedding LIMIT :limit"
    params["limit"] = limit

    async with _ToolSessionLocal() as session:
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    return [
        {
            "chunk_id": row.id,
            "source": row.source,
            "chunk_text": row.chunk_text,
            "vendor": row.vendor,
            "platform": row.platform,
            "technology": row.technology,
            "score": row.score,
        }
        for row in rows
    ]