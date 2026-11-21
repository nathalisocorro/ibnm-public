"""Consumidor Kafka para el ciclo de planificación de MS-PB02."""

import json
import logging

from aiokafka import AIOKafkaConsumer

from ms_pb02.config.settings import settings
from ms_pb02.kafka.schemas import LogicalTaskFaultEvent, PolicyProposedEvent
from ms_pb02.planning.manager import process_logical_task_fault, process_policy


logger = logging.getLogger(__name__)


async def consume_planning_events() -> None:
    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_POLICY_PROPOSED,
        settings.KAFKA_TOPIC_LOGICAL_TASK_FAULT,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        # Un LLM puede tardar varios minutos. Evita que Kafka reentregue el
        # mensaje mientras se generan las tres versiones permitidas.
        max_poll_interval_ms=1_800_000,
        session_timeout_ms=60_000,
        heartbeat_interval_ms=10_000,
    )
    await consumer.start()
    logger.info(
        "MS-PB02 suscrito a %s y %s",
        settings.KAFKA_TOPIC_POLICY_PROPOSED,
        settings.KAFKA_TOPIC_LOGICAL_TASK_FAULT,
    )
    try:
        async for message in consumer:
            try:
                if message.topic == settings.KAFKA_TOPIC_POLICY_PROPOSED:
                    await process_policy(PolicyProposedEvent.model_validate(message.value))
                else:
                    await process_logical_task_fault(
                        LogicalTaskFaultEvent.model_validate(message.value)
                    )
                await consumer.commit()
            except Exception:
                logger.exception(
                    "Error procesando offset %s en %s; se detiene sin confirmarlo.",
                    message.offset,
                    message.topic,
                )
                raise
    finally:
        await consumer.stop()
