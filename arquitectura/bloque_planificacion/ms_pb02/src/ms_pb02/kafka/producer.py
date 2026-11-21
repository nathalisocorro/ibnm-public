"""Productor idempotente de eventos Kafka para MS-PB02."""

import json

from aiokafka import AIOKafkaProducer

from ms_pb02.config.settings import settings


class KafkaProducer:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                acks="all",
                enable_idempotence=True,
                value_serializer=lambda value: json.dumps(
                    value, default=str, ensure_ascii=False
                ).encode("utf-8"),
            )
            await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def _send(self, topic: str, event) -> None:
        if self._producer is None:
            raise RuntimeError("El productor Kafka no ha sido iniciado.")
        payload = event.model_dump(by_alias=True) if hasattr(event, "model_dump") else event
        await self._producer.send_and_wait(topic, payload)

    async def send_logical_task_proposed(self, event) -> None:
        await self._send(settings.KAFKA_TOPIC_LOGICAL_TASK_PROPOSED, event)

    async def send_policy_fault(self, event) -> None:
        await self._send(settings.KAFKA_TOPIC_POLICY_FAULT, event)


kafka_producer = KafkaProducer()
