"""Punto de entrada de MS-OB01."""

import asyncio
import logging

from ms_ob01.config.settings import settings
from ms_ob01.db.database import close_db, init_db
from ms_ob01.kafka.consumer import consume_orchestration_events
from ms_ob01.kafka.producer import kafka_producer

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main_async() -> None:
    await init_db()
    await kafka_producer.start()
    try:
        await consume_orchestration_events()
    finally:
        await kafka_producer.stop()
        await close_db()


def main() -> None:
    asyncio.run(main_async())


def kickoff() -> None:
    main()


def plot() -> None:
    raise RuntimeError("MS-OB01 es un gestor Kafka; no tiene un Flow LLM local.")


def run_with_trigger() -> None:
    raise RuntimeError("MS-OB01 procesa LOGICAL_TASK_PROPOSED desde Kafka.")


if __name__ == "__main__":
    main()
