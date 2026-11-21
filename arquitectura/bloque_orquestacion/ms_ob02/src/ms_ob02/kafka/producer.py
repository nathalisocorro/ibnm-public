"""
Productor de eventos Kafka para MS-O02.
"""

import json
import logging
from aiokafka import AIOKafkaProducer
from ms_ob02.config.settings import settings

logger = logging.getLogger(__name__)


class KafkaProducer:
    def __init__(self):
        self.producer: AIOKafkaProducer | None = None

    async def start(self):
        """Inicializa el productor dentro del event loop."""
        if self.producer is None:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                acks=settings.KAFKA_PRODUCER_ACKS,
                enable_idempotence=True,
            )
            await self.producer.start()
            logger.info("Kafka Producer iniciado")

    async def stop(self):
        """Detiene el productor."""
        if self.producer:
            await self.producer.stop()
            self.producer = None
            logger.info("Kafka Producer detenido")

    async def _send(self, topic: str, event: dict):
        if self.producer is None:
            raise RuntimeError("Producer no iniciado. Llama a start() primero.")
        await self.producer.send_and_wait(topic, value=event)
        logger.info(f"Evento publicado en {topic}")

    async def send_command_sent(self, event):
        """Publica un evento COMMAND_SENT."""
        topic = settings.KAFKA_TOPIC_COMMAND_SENT            # ← cambio 1
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        await self._send(topic, payload)

    async def send_atomic_task_fault(self, event):
        """Publica un evento ATOMIC_TASK_FAULT."""
        topic = settings.KAFKA_TOPIC_ATOMIC_TASK_FAULT       # ← cambio 2
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        await self._send(topic, payload)

    async def send_command_execution_completed(self, event):
        """Publica un evento COMMAND_EXECUTION_COMPLETED."""
        topic = settings.KAFKA_TOPIC_COMMAND_EXECUTION_COMPLETED
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        await self._send(topic, payload)

    async def send_command_execution_failed(self, event):
        """Publica un evento COMMAND_EXECUTION_FAILED."""
        topic = settings.KAFKA_TOPIC_COMMAND_EXECUTION_FAILED
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        await self._send(topic, payload)


# Instancia global SIN inicializar
kafka_producer = KafkaProducer()