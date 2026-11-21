"""Punto de entrada de MS-PB02.

El servicio concentra la gestión, generación y validación de tareas lógicas.
Su interfaz de integración es Kafka: consume políticas validadas y publica
tareas lógicas solo después de validar las cinco capas.
"""

import asyncio
import logging

from ms_pb02.config.settings import settings
from ms_pb02.db.database import close_db, init_db
from ms_pb02.kafka.consumer import consume_planning_events
from ms_pb02.kafka.producer import kafka_producer


logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main_async() -> None:
    await init_db()
    await kafka_producer.start()
    try:
        await consume_planning_events()
    finally:
        await kafka_producer.stop()
        await close_db()


def main() -> None:
    asyncio.run(main_async())


def kickoff() -> None:
    """Entrada compatible con CrewAI CLI."""
    main()


def plot() -> None:
    """Genera el diagrama del Flow de generación y validación."""
    from ms_pb02.flows.main_flow import LogicalTaskFlow

    LogicalTaskFlow().plot()


def run_with_trigger() -> None:
    raise RuntimeError("MS-PB02 procesa eventos Kafka; use POLICY_PROPOSED.")


if __name__ == "__main__":
    main()
