"""
Script de laboratorio: prepara datos falsos y publica DOS eventos
ATOMIC_TASK_PROPOSED, uno por vendor (Opción A: una tarea atómica = un vendor).

Ejecuta desde la raíz del proyecto:
    cd ~/IBNM/arquitectura/bloque_orquestacion/ms_ob02
    uv run python test/setup_lab.py

Pasos:
    1. Crea las tablas que falten (init_db).
    2. Limpia las tablas de ejecución (opcional, para pruebas limpias).
    3. Inserta la jerarquía base y guarda los UUIDs.
    4. Inserta dispositivos reales de Containerlab en network_devices.
    5. Inserta sus capacidades en device_capabilities.
    6. Publica UN evento por dispositivo:
       - router-netconf-01 (nokia/SR Linux) → format=netconf_xml
       - router-cli-02 (frr/Linux)          → format=cli

Prerrequisitos en el laboratorio (verificar antes de ejecutar):
    - SR Linux con NETCONF en 830 y credenciales admin/NokiaSrl1!
    - FRR con SSH en 22, usuario admin/admin y shell apuntando a vtysh
      (o usar NETMIKO_DEVICE_TYPE=cisco_ios si vtysh imita Cisco)
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from ms_ob02.config.settings import settings
from ms_ob02.db.database import init_db, close_db
from ms_ob02.db.modelos_tablas_BD import (
    Role, User, Intent, Policy, LogicalTask, AtomicTask,
    NetworkDevice, DeviceCapability,
    DeviceType, DeviceStatus, IntentStatus, PolicyStatus,
    LogicalTaskStatus, AtomicTaskStatus, ScopeLevel, Technology,
)


UUIDS_FILE = Path("test/uuids_generados.json")


# =====================================================
# MOTOR
# =====================================================

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# =====================================================
# DISPOSITIVOS DEL LABORATORIO (CONTAINERLAB)
# =====================================================

# (hostname, vendor, platform, model, management_ip, interface_name, capabilities)
LAB_DEVICES = [
    (
        "router-netconf-01",
        "nokia",
        "SR Linux",
        "7220 IXR-D2L",
        "172.30.30.2",
        "ethernet-1/1",
        {
            "cli": True,
            "ssh": True,
            "netconf": True,
            "candidate_config": True,
            "confirmed_commit": True,
            "rollback": True,
            "config_backup": True,
        },
    ),
    (
        "router-cli-02",
        "frr",
        "Linux",
        "v8.4",
        "172.30.30.3",
        "eth1",
        {
            "cli": True,
            "ssh": True,
            "netconf": False,
            "candidate_config": False,
            "confirmed_commit": False,
            "rollback": True,
            "config_backup": True,
        },
    ),
]


# =====================================================
# PASOS DEL SETUP
# =====================================================

async def clean_execution_tables(session) -> None:
    for table in ("command_executions", "commands", "execution_plans"):
        await session.execute(text(f"DELETE FROM {table}"))
    await session.commit()
    print("Tablas de ejecución limpiadas", flush=True)


async def seed_hierarchy(session) -> dict:
    ids = {
        "role_id": uuid4(),
        "user_id": uuid4(),
        "intent_id": uuid4(),
        "policy_id": uuid4(),
        "logical_task_id": uuid4(),
        "atomic_task_id": uuid4(),
    }

    session.add(Role(
        role_id=ids["role_id"],
        role_name=f"OPERATOR_{ids['role_id'].hex[:8]}",
        priority_level=2,
        max_scope=ScopeLevel.NETWORK,
    ))
    await session.commit()

    session.add(User(
        user_id=ids["user_id"],
        name="Lab Operator",
        email=f"operator_{ids['user_id'].hex[:8]}@lab.local",
        password_hash="lab-hash",
        role_id=ids["role_id"],
    ))
    await session.commit()

    session.add(Intent(
        intent_id=ids["intent_id"],
        user_id=ids["user_id"],
        action="configurar",
        object="descripcion de interfaz",
        status=IntentStatus.ACTIVE,
        scope_level=ScopeLevel.NETWORK,
    ))
    await session.commit()

    session.add(Policy(
        policy_id=ids["policy_id"],
        intent_id=ids["intent_id"],
        status=PolicyStatus.VALIDATED,
    ))
    await session.commit()

    session.add(LogicalTask(
        task_id=ids["logical_task_id"],
        policy_id=ids["policy_id"],
        intent_id=ids["intent_id"],
        status=LogicalTaskStatus.SENT,
    ))
    await session.commit()

    session.add(AtomicTask(
        atomic_task_id=ids["atomic_task_id"],
        logical_task_id=ids["logical_task_id"],
        policy_id=ids["policy_id"],
        intent_id=ids["intent_id"],
        status=AtomicTaskStatus.PENDING,
    ))
    await session.commit()

    return ids


async def seed_devices(session) -> list[dict]:
    devices = []

    # Limpiar dispositivos de laboratorio previos
    for hostname, *_ in LAB_DEVICES:
        await session.execute(
            text("DELETE FROM device_capabilities WHERE device_id IN "
                 "(SELECT device_id FROM network_devices WHERE hostname = :h)"),
            {"h": hostname},
        )
        await session.execute(
            text("DELETE FROM network_devices WHERE hostname = :h"),
            {"h": hostname},
        )
    await session.commit()

    for hostname, vendor, platform, model, mgmt_ip, interface_name, caps in LAB_DEVICES:
        device_id = uuid4()

        session.add(NetworkDevice(
            device_id=device_id,
            hostname=hostname,
            device_type=DeviceType.ROUTER,
            technology=Technology.ETHERNET,
            vendor=vendor,
            model=model,
            management_ip=mgmt_ip,
            status=DeviceStatus.ACTIVE,
            inventory_version=1,
            secret_ref=f"vault://devices/{hostname}",
        ))
        await session.commit()

        for capability, supported in caps.items():
            session.add(DeviceCapability(
                device_id=device_id,
                capability=capability,
                supported=supported,
                verified=True,
            ))
        await session.commit()

        supported_caps = sorted(k for k, v in caps.items() if v)
        devices.append({
            "device_id": str(device_id),
            "hostname": hostname,
            "vendor": vendor,
            "platform": platform,
            "management_ip": mgmt_ip,
            "interface_name": interface_name,
            "capabilities": supported_caps,
            "supports_netconf": caps.get("netconf", False),
        })

        print(f"Dispositivo creado: {hostname} ({device_id})", flush=True)
        print(f"   IP: {mgmt_ip} | vendor: {vendor} | platform: {platform}", flush=True)
        print(f"   interfaces: {interface_name} | netconf={caps.get('netconf', False)}", flush=True)

    return devices


# =====================================================
# EVENTO POR DISPOSITIVO
# =====================================================

def _build_atomic_task_for_device(device: dict) -> dict:
    """Construye el atomic_task_json adaptado al vendor del device."""
    return {
        "vendor": device["vendor"],
        "platform": device["platform"],
        "device_targets": [device["hostname"]],
        "steps": [
            {
                "step": 1,
                "operation": "set_interface_description",
                "interface": device["interface_name"],
                "description": "UPLINK-TO-CORE",
            }
        ],
        "rollback_steps": [
            {
                "step": 1,
                "operation": "remove_interface_description",
                "interface": device["interface_name"],
            }
        ],
    }


def build_event_for_device(ids: dict, device: dict) -> dict:
    """
    Construye un ATOMIC_TASK_PROPOSED coherente para un único dispositivo.

    El vendor, platform, format y atomic_task_json reflejan el dispositivo
    real. Así el motor de decisión y el LLM reciben contexto consistente.
    """
    # Elegir format según lo que soporte el dispositivo
    if device["supports_netconf"]:
        fmt = "netconf_xml"
        format_pref = "cli"
    else:
        fmt = "cli"
        format_pref = "cli"

    return {
        "event": "ATOMIC_TASK_PROPOSED",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "LAB-SIMULATOR",

        "command_id": str(uuid4()),
        "atomic_task_id": str(ids["atomic_task_id"]),
        "logical_task_id": str(ids["logical_task_id"]),
        "policy_id": str(ids["policy_id"]),
        "intent_id": str(ids["intent_id"]),
        "trace_id": str(uuid4()),
        "correlation_id": str(uuid4()),

        "task_order": 1,
        "task_description": (
            f"Configurar descripcion en {device['interface_name']} "
            f"de {device['hostname']}"
        ),
        "task_type": "SIMPLE_CONFIG",
        "criticality": "MEDIUM",

        "vendor": device["vendor"],
        "platform": device["platform"],
        "os_version": "",
        "device_targets": [device["hostname"]],

        "executor_preference": "AUTO",
        "format": fmt,
        "format_preference": format_pref,
        "rollback_requirement": "OPTIONAL",

        "required_capabilities": {
            "supports_netconf": device["supports_netconf"],
            "supports_rollback": True,
        },
        "constraints": {"must_not": [], "must_do": []},

        "atomic_task_json": _build_atomic_task_for_device(device),

        "version": 1,
        "attempt_count": 1,
        "max_attempts": 3,
        "previous_failed_commands": [],

        "priority_level": 2,
        "generated_by": "AGENT_AI6",
        "metadata": {
            "origin_block": "LAB",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def publish_event(event: dict) -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        acks="all",
    )
    await producer.start()
    try:
        await producer.send_and_wait(
            settings.KAFKA_TOPIC_ATOMIC_TASK_PROPOSED,
            value=event,
        )
        print(
            f"Evento publicado en {settings.KAFKA_TOPIC_ATOMIC_TASK_PROPOSED} "
            f"({event['vendor']}/{event['platform']} → "
            f"{event['device_targets']}, format={event['format']})",
            flush=True,
        )
    finally:
        await producer.stop()


# =====================================================
# MAIN
# =====================================================

async def main():
    print("-> Creando tablas faltantes...", flush=True)
    await init_db()

    async with SessionLocal() as session:
        print("-> Limpiando tablas de ejecución...", flush=True)
        await clean_execution_tables(session)

        print("-> Insertando jerarquia base...", flush=True)
        ids = await seed_hierarchy(session)
        print(f"Jerarquia creada: atomic_task_id={ids['atomic_task_id']}", flush=True)

        print("-> Insertando dispositivos del laboratorio...", flush=True)
        devices = await seed_devices(session)

    payload = {k: str(v) for k, v in ids.items()}
    payload["devices"] = devices
    UUIDS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"-> UUIDs guardados en {UUIDS_FILE}", flush=True)

    # Validar y publicar un evento por dispositivo
    from ms_ob02.kafka.schemas import AtomicTaskProposedEvent

    for device in devices:
        print(
            f"\n-> Construyendo evento para {device['hostname']} "
            f"({device['vendor']}/{device['platform']})...",
            flush=True,
        )
        event = build_event_for_device(ids, device)

        try:
            AtomicTaskProposedEvent(**event)
            print(f"   Evento validado contra el schema Pydantic", flush=True)
        except Exception as e:
            print(f"   ⚠️ Evento inválido para {device['hostname']}: {e}", flush=True)
            continue

        await publish_event(event)
        await asyncio.sleep(1)  # deja que Kafka lo procese antes del siguiente

    print()
    print("=" * 60)
    print("LAB LISTO — eventos publicados por vendor")
    print("=" * 60)
    for device in devices:
        print(
            f"  {device['hostname']:<20} "
            f"{device['vendor']:<8} "
            f"{device['platform']:<10} "
            f"netconf={device['supports_netconf']}"
        )
    print("=" * 60)
    print()
    print("Verifica los planes generados:")
    print('  psql -h 172.19.0.1 -U ibn_user -d ibn_db -c \\')
    print('    "SELECT plan_id, artifact_format, protocol, executor, device_ids '
          'FROM execution_plans ORDER BY created_at DESC LIMIT 5"')
    print()
    print("Sigue los logs del pod:")
    print("  kubectl -n ibnm-bloque-orquestacion logs deploy/ms-ob02 -f")


if __name__ == "__main__":
    asyncio.run(main())