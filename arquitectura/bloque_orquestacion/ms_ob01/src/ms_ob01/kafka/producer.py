"""Productor Kafka de MS-OB01."""

import json

from aiokafka import AIOKafkaProducer

from ms_ob01.config.settings import settings


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

    async def send(self, event) -> None:
        if self._producer is None:
            raise RuntimeError("El productor Kafka no ha sido iniciado.")
        payload = event.model_dump(by_alias=True) if hasattr(event, "model_dump") else event
        await self._producer.send_and_wait(settings.KAFKA_TOPIC_ATOMIC_TASK_PROPOSED, payload)

    async def send_fault(self, event) -> None:
        if self._producer is None:
            raise RuntimeError("El productor Kafka no ha sido iniciado.")
        payload = event.model_dump(by_alias=True) if hasattr(event, "model_dump") else event
        await self._producer.send_and_wait(settings.KAFKA_TOPIC_LOGICAL_TASK_FAULT, payload)


kafka_producer = KafkaProducer()
