"""Consumidor Kafka de LOGICAL_TASK_PROPOSED y LOGICAL_TASK_FAULT."""

import json
import logging

from aiokafka import AIOKafkaConsumer

from ms_ob01.config.settings import settings
from ms_ob01.kafka.schemas import AtomicTaskFaultEvent, LogicalTaskProposedEvent
from ms_ob01.orchestration.manager import process_atomic_task_fault, process_logical_task

logger = logging.getLogger(__name__)


async def consume_orchestration_events() -> None:
    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_LOGICAL_TASK_PROPOSED,
        settings.KAFKA_TOPIC_ATOMIC_TASK_FAULT,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        max_poll_interval_ms=1_800_000,
        session_timeout_ms=60_000,
        heartbeat_interval_ms=10_000,
    )
    await consumer.start()
    logger.info(
        "MS-OB01 suscrito a %s y %s",
        settings.KAFKA_TOPIC_LOGICAL_TASK_PROPOSED,
        settings.KAFKA_TOPIC_ATOMIC_TASK_FAULT,
    )
    try:
        async for message in consumer:
            try:
                if message.topic == settings.KAFKA_TOPIC_LOGICAL_TASK_PROPOSED:
                    event = LogicalTaskProposedEvent.model_validate(message.value)
                    await process_logical_task(event)
                elif message.topic == settings.KAFKA_TOPIC_ATOMIC_TASK_FAULT:
                    event = AtomicTaskFaultEvent.model_validate(message.value)
                    await process_atomic_task_fault(event)
                else:
                    logger.warning("Topic no reconocido: %s", message.topic)
                await consumer.commit()
            except Exception:
                logger.exception(
                    "Error procesando offset %s; se detiene sin confirmarlo.",
                    message.offset,
                )
                raise
    finally:
        await consumer.stop()
