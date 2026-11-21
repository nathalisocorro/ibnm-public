"""MS-V03: servicio de referencia SSoT para pruebas de integración IBNM."""

import json
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


DB_PATH = Path(os.getenv("SSOT_DB_PATH", "./data/ssot.db"))


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ssot_devices (
                resource_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                name TEXT NOT NULL,
                scope TEXT,
                target TEXT,
                vendor TEXT NOT NULL,
                model TEXT NOT NULL,
                platform TEXT NOT NULL,
                os_version TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('available', 'maintenance', 'offline')
                ),
                management_address TEXT,
                data_origin TEXT NOT NULL DEFAULT 'injected_test_data',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ssot_device_configs (
                resource_id TEXT PRIMARY KEY,
                config_version INTEGER NOT NULL DEFAULT 1,
                configuration_json TEXT NOT NULL,
                observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resource_id)
                    REFERENCES ssot_devices(resource_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ssot_device_capacities (
                resource_id TEXT PRIMARY KEY,
                cpu_total_percent REAL,
                cpu_available_percent REAL,
                memory_total_mb REAL,
                memory_available_mb REAL,
                available_bandwidth_mbps REAL,
                total_interfaces INTEGER,
                available_interfaces INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resource_id)
                    REFERENCES ssot_devices(resource_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ssot_compliance_rules (
                rule_id TEXT PRIMARY KEY,
                rule_type TEXT NOT NULL,
                description TEXT NOT NULL,
                rule_expression_json TEXT NOT NULL,
                severity TEXT NOT NULL CHECK (
                    severity IN ('info', 'warning', 'blocking')
                ),
                is_active INTEGER NOT NULL DEFAULT 1,
                applies_to_json TEXT NOT NULL DEFAULT '[]',
                vendor TEXT,
                platform TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def json_dict(value: str | None) -> dict[str, Any]:
    return json.loads(value or "{}")


def seed_data() -> None:
    """Inserta fixtures sintéticos únicamente cuando la base está vacía."""
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM ssot_devices").fetchone()[0]
        if count:
            return

        devices = [
            (
                "edge-rtr-01", "edge-rtr-01", "Router de borde 01",
                "edge", "edge-rtr-01", "Cisco", "ISR 4331",
                "Cisco IOS XE", "17.9.4a", "EDGE_ROUTER", "available",
                "192.0.2.11", "synthetic_test_data",
                {"site": "LAB-01", "management_protocol": "SSH"}
            ),
            (
                "core-rtr-01", "core-rtr-01", "Router de núcleo 01",
                "core", "core-rtr-01", "Juniper", "MX204",
                "Junos OS", "23.2R1", "CORE_ROUTER", "available",
                "192.0.2.21", "synthetic_test_data",
                {"site": "LAB-01", "management_protocol": "SSH"}
            ),
            (
                "edge-rtr-02", "edge-rtr-02", "Router de borde 02",
                "edge", "edge-rtr-02", "Huawei", "AR6140",
                "Huawei VRP", "V300R022C00", "EDGE_ROUTER", "maintenance",
                "192.0.2.12", "synthetic_test_data",
                {"site": "LAB-02", "management_protocol": "SSH"}
            ),
        ]

        db.executemany(
            """
            INSERT INTO ssot_devices (
                resource_id, hostname, name, scope, target, vendor,
                model, platform, os_version, role, status,
                management_address, data_origin, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*device[:-1], json.dumps(device[-1], ensure_ascii=False))
                for device in devices
            ],
        )

        configs = [
            (
                "edge-rtr-01", 1,
                {
                    "interfaces": [
                        {
                            "name": "GigabitEthernet0/0/0",
                            "admin_status": "up",
                            "description": "WAN",
                            "ipv4_address": "192.0.2.11/30"
                        }
                    ],
                    "routing": {"protocols": ["BGP", "OSPF"]},
                    "qos": {"policies": []},
                    "access_control": {"acls": []}
                }
            ),
            (
                "core-rtr-01", 1,
                {
                    "interfaces": [
                        {
                            "name": "ge-0/0/0",
                            "admin_status": "up",
                            "description": "CORE-UPLINK",
                            "ipv4_address": "192.0.2.21/30"
                        }
                    ],
                    "routing": {"protocols": ["BGP", "OSPF", "IS-IS"]},
                    "qos": {"policies": []},
                    "access_control": {"filters": []}
                }
            ),
            (
                "edge-rtr-02", 1,
                {
                    "interfaces": [
                        {
                            "name": "GigabitEthernet0/0/0",
                            "admin_status": "down",
                            "description": "WAN",
                            "ipv4_address": "192.0.2.13/30"
                        }
                    ],
                    "routing": {"protocols": ["OSPF"]},
                    "qos": {"policies": []},
                    "access_control": {"acls": []}
                }
            ),
        ]

        db.executemany(
            """
            INSERT INTO ssot_device_configs
                (resource_id, config_version, configuration_json)
            VALUES (?, ?, ?)
            """,
            [
                (resource_id, version, json.dumps(config, ensure_ascii=False))
                for resource_id, version, config in configs
            ],
        )

        capacities = [
            ("edge-rtr-01", 35, 65, 8192, 5120, 500, 8, 5, {}),
            ("core-rtr-01", 42, 58, 32768, 20480, 1000, 16, 10, {}),
            ("edge-rtr-02", 20, 80, 8192, 6144, 100, 8, 2, {}),
        ]

        db.executemany(
            """
            INSERT INTO ssot_device_capacities (
                resource_id, cpu_total_percent, cpu_available_percent,
                memory_total_mb, memory_available_mb,
                available_bandwidth_mbps, total_interfaces,
                available_interfaces, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*capacity[:-1], json.dumps(capacity[-1]))
                for capacity in capacities
            ],
        )

        rules = [
            (
                "SSOT-RULE-001",
                "LOGICAL_TASK_VENDOR_NEUTRALITY",
                "Las tareas logicas no deben incluir comandos especificos de fabricante.",
                {"condition": "forbid_vendor_specific_commands"},
                "blocking",
                1,
                ["logical_task"],
                None,
                None,
            ),
            (
                "SSOT-RULE-002",
                "ATOMIC_TASK_VENDOR_MATCH",
                "La tarea atomica debe corresponder al fabricante, plataforma y version del dispositivo destino.",
                {"condition": "require_vendor_platform_os_match"},
                "blocking",
                1,
                ["atomic_task"],
                None,
                None,
            ),
            (
                "SSOT-RULE-003",
                "DEVICE_AVAILABILITY",
                "No se deben proponer cambios de configuracion en dispositivos fuera de servicio o mantenimiento.",
                {"condition": "require_available_device_for_changes"},
                "blocking",
                1,
                ["atomic_task"],
                None,
                None,
            ),
            (
                "SSOT-RULE-004",
                "CONFIGURATION_ROLLBACK",
                "Las tareas que modifican configuracion deben definir una estrategia de rollback.",
                {
                    "condition": "require_rollback_for_configuration_changes",
                    "operation_type": "configuration_change"
                },
                "blocking",
                1,
                ["atomic_task"],
                None,
                None,
            ),
        ]

        db.executemany(
            """
            INSERT INTO ssot_compliance_rules (
                rule_id, rule_type, description, rule_expression_json,
                severity, is_active, applies_to_json, vendor, platform
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    rule_id, rule_type, description,
                    json.dumps(expression, ensure_ascii=False),
                    severity, active, json.dumps(applies_to),
                    vendor, platform
                )
                for (
                    rule_id, rule_type, description, expression,
                    severity, active, applies_to, vendor, platform
                ) in rules
            ],
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceInput(StrictModel):
    resource_id: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scope: str | None = None
    target: str | None = None
    vendor: str = Field(min_length=1)
    model: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    os_version: str = Field(min_length=1)
    role: str = Field(min_length=1)
    status: Literal["available", "maintenance", "offline"]
    management_address: str | None = None
    data_origin: str = "injected_test_data"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("vendor", "model", "platform", "os_version")
    @classmethod
    def reject_unknown_metadata(cls, value: str) -> str:
        forbidden = {"generic", "unknown", "n/a", "none", "null"}
        if value.strip().lower() in forbidden:
            raise ValueError(
                "Debe proporcionarse el valor real o de prueba identificado; "
                "no se permiten generic/unknown."
            )
        return value.strip()


class DeviceConfigInput(StrictModel):
    config_version: int = Field(default=1, ge=1)
    configuration: dict[str, Any]


class CapacityInput(StrictModel):
    resource_id: str
    cpu_total_percent: float | None = Field(default=None, ge=0, le=100)
    cpu_available_percent: float | None = Field(default=None, ge=0, le=100)
    memory_total_mb: float | None = Field(default=None, ge=0)
    memory_available_mb: float | None = Field(default=None, ge=0)
    available_bandwidth_mbps: float | None = Field(default=None, ge=0)
    total_interfaces: int | None = Field(default=None, ge=0)
    available_interfaces: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComplianceRuleInput(StrictModel):
    rule_id: str
    rule_type: str
    description: str
    rule_expression: dict[str, Any]
    severity: Literal["info", "warning", "blocking"]
    is_active: bool = True
    applies_to: list[str] = Field(default_factory=list)
    vendor: str | None = None
    platform: str | None = None


def device_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "resource_id": row["resource_id"],
        "hostname": row["hostname"],
        "name": row["name"],
        "scope": row["scope"],
        "target": row["target"],
        "vendor": row["vendor"],
        "model": row["model"],
        "platform": row["platform"],
        "os_version": row["os_version"],
        "role": row["role"],
        "status": row["status"],
        "management_address": row["management_address"],
        "data_origin": row["data_origin"],
        "metadata": json_dict(row["metadata_json"]),
        "updated_at": row["updated_at"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_data()
    yield


app = FastAPI(
    title="MS-V03 Source of Truth",
    description="Servicio SSoT de referencia para integración y pruebas IBNM.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    with get_db() as db:
        db.execute("SELECT 1")
    return {"service": "MS-V03-SSOT", "status": "ok", "mock": True}


@app.get("/api/v1/ssot/devices")
def get_devices():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM ssot_devices ORDER BY resource_id"
        ).fetchall()
    items = [device_to_dict(row) for row in rows]
    return {"items": items, "total": len(items)}


@app.get("/api/v1/ssot/devices/{device_id}/config")
def get_device_config(device_id: str):
    with get_db() as db:
        device = db.execute(
            "SELECT * FROM ssot_devices WHERE resource_id = ?",
            (device_id,),
        ).fetchone()
        config = db.execute(
            "SELECT * FROM ssot_device_configs WHERE resource_id = ?",
            (device_id,),
        ).fetchone()

    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    if config is None:
        raise HTTPException(
            status_code=404,
            detail="El dispositivo no tiene configuracion registrada",
        )

    return {
        "resource_id": device_id,
        "device": device_to_dict(device),
        "config_version": config["config_version"],
        "configuration": json_dict(config["configuration_json"]),
        "observed_at": config["observed_at"],
    }


@app.get("/api/v1/ssot/capacity")
def get_capacity():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT c.*, d.hostname, d.vendor, d.platform, d.status
            FROM ssot_device_capacities c
            JOIN ssot_devices d ON d.resource_id = c.resource_id
            ORDER BY c.resource_id
            """
        ).fetchall()

    items = [
        {
            "resource_id": row["resource_id"],
            "hostname": row["hostname"],
            "vendor": row["vendor"],
            "platform": row["platform"],
            "device_status": row["status"],
            "cpu_total_percent": row["cpu_total_percent"],
            "cpu_available_percent": row["cpu_available_percent"],
            "memory_total_mb": row["memory_total_mb"],
            "memory_available_mb": row["memory_available_mb"],
            "available_bandwidth_mbps": row["available_bandwidth_mbps"],
            "total_interfaces": row["total_interfaces"],
            "available_interfaces": row["available_interfaces"],
            "metadata": json_dict(row["metadata_json"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}


@app.get("/api/v1/ssot/compliance-rules")
def get_compliance_rules(active_only: bool = True):
    query = "SELECT * FROM ssot_compliance_rules"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY rule_id"

    with get_db() as db:
        rows = db.execute(query).fetchall()

    items = [
        {
            "rule_id": row["rule_id"],
            "rule_type": row["rule_type"],
            "description": row["description"],
            "rule_expression": json_dict(row["rule_expression_json"]),
            "severity": row["severity"],
            "is_active": bool(row["is_active"]),
            "applies_to": json.loads(row["applies_to_json"]),
            "vendor": row["vendor"],
            "platform": row["platform"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}


@app.put("/api/v1/ssot/devices/{device_id}")
def upsert_device(device_id: str, device: DeviceInput):
    if device_id != device.resource_id:
        raise HTTPException(
            status_code=400,
            detail="device_id debe coincidir con resource_id",
        )

    with get_db() as db:
        db.execute(
            """
            INSERT INTO ssot_devices (
                resource_id, hostname, name, scope, target, vendor,
                model, platform, os_version, role, status,
                management_address, data_origin, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(resource_id) DO UPDATE SET
                hostname=excluded.hostname,
                name=excluded.name,
                scope=excluded.scope,
                target=excluded.target,
                vendor=excluded.vendor,
                model=excluded.model,
                platform=excluded.platform,
                os_version=excluded.os_version,
                role=excluded.role,
                status=excluded.status,
                management_address=excluded.management_address,
                data_origin=excluded.data_origin,
                metadata_json=excluded.metadata_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                device.resource_id, device.hostname, device.name,
                device.scope, device.target, device.vendor, device.model,
                device.platform, device.os_version, device.role, device.status,
                device.management_address, device.data_origin,
                json.dumps(device.metadata, ensure_ascii=False),
            ),
        )
    return {"message": "Dispositivo guardado", "device": device.model_dump()}


@app.put("/api/v1/ssot/devices/{device_id}/config")
def upsert_device_config(device_id: str, config: DeviceConfigInput):
    with get_db() as db:
        exists = db.execute(
            "SELECT 1 FROM ssot_devices WHERE resource_id = ?",
            (device_id,),
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

        db.execute(
            """
            INSERT INTO ssot_device_configs
                (resource_id, config_version, configuration_json, observed_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(resource_id) DO UPDATE SET
                config_version=excluded.config_version,
                configuration_json=excluded.configuration_json,
                observed_at=CURRENT_TIMESTAMP
            """,
            (
                device_id,
                config.config_version,
                json.dumps(config.configuration, ensure_ascii=False),
            ),
        )
    return {"message": "Configuracion guardada", "resource_id": device_id}


@app.put("/api/v1/ssot/capacity/{device_id}")
def upsert_capacity(device_id: str, capacity: CapacityInput):
    if device_id != capacity.resource_id:
        raise HTTPException(status_code=400, detail="resource_id no coincide")

    with get_db() as db:
        exists = db.execute(
            "SELECT 1 FROM ssot_devices WHERE resource_id = ?",
            (device_id,),
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

        db.execute(
            """
            INSERT INTO ssot_device_capacities (
                resource_id, cpu_total_percent, cpu_available_percent,
                memory_total_mb, memory_available_mb, available_bandwidth_mbps,
                total_interfaces, available_interfaces, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(resource_id) DO UPDATE SET
                cpu_total_percent=excluded.cpu_total_percent,
                cpu_available_percent=excluded.cpu_available_percent,
                memory_total_mb=excluded.memory_total_mb,
                memory_available_mb=excluded.memory_available_mb,
                available_bandwidth_mbps=excluded.available_bandwidth_mbps,
                total_interfaces=excluded.total_interfaces,
                available_interfaces=excluded.available_interfaces,
                metadata_json=excluded.metadata_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                capacity.resource_id, capacity.cpu_total_percent,
                capacity.cpu_available_percent, capacity.memory_total_mb,
                capacity.memory_available_mb, capacity.available_bandwidth_mbps,
                capacity.total_interfaces, capacity.available_interfaces,
                json.dumps(capacity.metadata, ensure_ascii=False),
            ),
        )
    return {"message": "Capacidad guardada", "resource_id": device_id}


@app.put("/api/v1/ssot/compliance-rules/{rule_id}")
def upsert_compliance_rule(rule_id: str, rule: ComplianceRuleInput):
    if rule_id != rule.rule_id:
        raise HTTPException(status_code=400, detail="rule_id no coincide")

    with get_db() as db:
        db.execute(
            """
            INSERT INTO ssot_compliance_rules (
                rule_id, rule_type, description, rule_expression_json,
                severity, is_active, applies_to_json, vendor, platform, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(rule_id) DO UPDATE SET
                rule_type=excluded.rule_type,
                description=excluded.description,
                rule_expression_json=excluded.rule_expression_json,
                severity=excluded.severity,
                is_active=excluded.is_active,
                applies_to_json=excluded.applies_to_json,
                vendor=excluded.vendor,
                platform=excluded.platform,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                rule.rule_id, rule.rule_type, rule.description,
                json.dumps(rule.rule_expression, ensure_ascii=False),
                rule.severity, int(rule.is_active),
                json.dumps(rule.applies_to), rule.vendor, rule.platform,
            ),
        )
    return {"message": "Regla guardada", "rule_id": rule_id}
