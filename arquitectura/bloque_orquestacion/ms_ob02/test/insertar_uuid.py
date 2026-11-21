"""
Script para crear la jerarquía completa (roles → users → intents → policies → logical_tasks → atomic_tasks)
y devolver los UUIDs para usarlos en el evento Kafka.

Ejecuta desde la raíz del proyecto:
    cd ~/TESIS_IBNM/IBNM/arquitectura/bloque_orquestacion/ms_ob02
    uv run python test/insertar_uuid.py
"""

import asyncio
import json
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from ms_ob02.config.settings import settings
from ms_ob02.db.modelos_tablas_BD import (
    Role, User, Intent, Policy, LogicalTask, AtomicTask,
    IntentStatus, PolicyStatus, LogicalTaskStatus, AtomicTaskStatus,
    ScopeLevel,
)


DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed_hierarchy():
    """Inserta la jerarquía completa y devuelve los UUIDs generados."""
    ids = {
        "role_id": uuid4(),
        "user_id": uuid4(),
        "intent_id": uuid4(),
        "policy_id": uuid4(),
        "logical_task_id": uuid4(),
        "atomic_task_id": uuid4(),
    }

    async with SessionLocal() as session:
        # 1. Role
        session.add(Role(
            role_id=ids["role_id"],
            role_name=f"OPERATOR_{ids['role_id'].hex[:8]}",
            priority_level=2,
            max_scope=ScopeLevel.NETWORK,
        ))
        await session.commit()
        print(f"✅ Role creado: {ids['role_id']}")

        # 2. User
        session.add(User(
            user_id=ids["user_id"],
            name="Test Operator",
            email=f"operator_{ids['user_id'].hex[:8]}@test.com",
            password_hash="hash",
            role_id=ids["role_id"],
        ))
        await session.commit()
        print(f"✅ User creado: {ids['user_id']}")

        # 3. Intent
        session.add(Intent(
            intent_id=ids["intent_id"],
            user_id=ids["user_id"],
            action="garantizar",
            object="ancho de banda",
            status=IntentStatus.ACTIVE,
            scope_level=ScopeLevel.NETWORK,
        ))
        await session.commit()
        print(f"✅ Intent creado: {ids['intent_id']}")

        # 4. Policy
        session.add(Policy(
            policy_id=ids["policy_id"],
            intent_id=ids["intent_id"],
            status=PolicyStatus.VALIDATED,
        ))
        await session.commit()
        print(f"✅ Policy creada: {ids['policy_id']}")

        # 5. LogicalTask
        session.add(LogicalTask(
            task_id=ids["logical_task_id"],
            policy_id=ids["policy_id"],
            intent_id=ids["intent_id"],
            status=LogicalTaskStatus.SENT,
        ))
        await session.commit()
        print(f"✅ LogicalTask creada: {ids['logical_task_id']}")

        # 6. AtomicTask
        session.add(AtomicTask(
            atomic_task_id=ids["atomic_task_id"],
            logical_task_id=ids["logical_task_id"],
            policy_id=ids["policy_id"],
            intent_id=ids["intent_id"],
            status=AtomicTaskStatus.PENDING,
        ))
        await session.commit()
        print(f"✅ AtomicTask creada: {ids['atomic_task_id']}")

    # Guardar los UUIDs en un archivo JSON para usarlos después
    with open("test/uuids_generados.json", "w") as f:
        json.dump({k: str(v) for k, v in ids.items()}, f, indent=2)

    return {k: str(v) for k, v in ids.items()}


if __name__ == "__main__":
    ids = asyncio.run(seed_hierarchy())

    print("\n" + "=" * 60)
    print("UUIDs generados (guardados en test/uuids_generados.json):")
    print("=" * 60)
    for k, v in ids.items():
        print(f"{k} = \"{v}\"")
    print("=" * 60)
    print("\nUsa estos UUIDs en publish_atomic_task.py")