"""
Script para publicar un evento ATOMIC_TASK_PROPOSED en Kafka.
Úsalo para simular que MS-O01 ha enviado una tarea atómica a MS-O04.
"""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from aiokafka import AIOKafkaProducer

with open("test/uuids_generados.json") as f:
    uuids = json.load(f)


KAFKA_BOOTSTRAP = "localhost:9092"
TOPIC = "ATOMIC_TASK_PROPOSED"


def build_event() -> dict:
    """Construye el evento con el formato que espera MS-O04."""
    return {
        "event": "ATOMIC_TASK_PROPOSED",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "MS-O01",

        # Trazabilidad
        "command_id": str(uuid4()),                    # Este sí es nuevo (no existe en la BD)
        "atomic_task_id": uuids["atomic_task_id"],     # Del seed
        "logical_task_id": uuids["logical_task_id"],   # Del seed
        "policy_id": uuids["policy_id"],               # Del seed
        "intent_id": uuids["intent_id"],               # Del seed
        "trace_id": str(uuid4()),
        "correlation_id": str(uuid4()),

        # Contexto de la tarea
        "task_order": 1,
        "task_description": "Crear VLAN 200 (VOICE_VLAN) con SVI y relay DHCP",
        "task_type": "SIMPLE_CONFIG",
        "criticality": "MEDIUM",

        # Datos del dispositivo objetivo
        "vendor": "huawei",
        "platform": "Huawei S5700",
        "os_version": "V200R023C00",
        "device_targets": ["router-core-02"],

        # Preferencias del motor de decisión
        "executor_preference": "AUTO",
        "format": "cli",
        "format_preference": "cli",
        "rollback_requirement": "OPTIONAL",

        # Restricciones
        "required_capabilities": {
            "supports_vlan": True,
            "supports_netconf": True
        },
        "constraints": {
            "must_not": ["No modificar VLANs existentes"],
            "must_do": ["Verificar que la VLAN no exista antes de crearla"]
        },

        # Tarea atómica completa
        "atomic_task_json": {
            "vendor": "cisco",
            "platform": "IOS-XE",
            "device_targets": ["router-core-01"],
            "steps": [
                {
                    "step": 1,
                    "operation": "vlan_create",
                    "vlan_id": 200,
                    "name": "VOICE_VLAN"
                },
                {
                    "step": 2,
                    "operation": "interface_vlan_create",
                    "vlan_id": 200
                },
                {
                    "step": 3,
                    "operation": "ip_address_assign",
                    "interface": "Vlan200",
                    "ip_address": "10.200.0.1",
                    "subnet_mask": "255.255.255.0"
                },
                {
                    "step": 4,
                    "operation": "dhcp_relay_config",
                    "interface": "Vlan200",
                    "helper_address": "10.10.10.50"
                },
                {
                    "step": 5,
                    "operation": "interface_activate",
                    "interface": "Vlan200"
                }
            ],
            "rollback_steps": [
                {
                    "step": 1,
                    "operation": "no_interface_vlan",
                    "vlan_id": 200
                },
                {
                    "step": 2,
                    "operation": "no_vlan",
                    "vlan_id": 200
                }
            ]
        },

        # Control de reintentos
        "version": 1,
        "attempt_count": 1,
        "max_attempts": 3,
        "previous_failed_commands": [],

        # Metadatos
        "priority_level": 2,
        "generated_by": "AGENT_AI6",
        "metadata": {
            "origin_block": "ORCHESTRATION",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    }


async def publish():
    event = build_event()

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        acks="all",
    )
    await producer.start()
    try:
        await producer.send_and_wait(TOPIC, value=event)
        print(f"✅ Evento publicado en {TOPIC}")
        print(f"   command_id: {event['command_id']}")
        print(f"   atomic_task_id: {event['atomic_task_id']}")
        print(f"   vendor: {event['vendor']} | platform: {event['platform']}")
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(publish())
