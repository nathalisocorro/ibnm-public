"""Validador determinista de las cinco capas para logical_task_json."""

import json
import re
from typing import Any

from pydantic import BaseModel, Field


VENDOR_PATTERNS = (
    r"\bclass-map\b", r"\bpolicy-map\b", r"\bconfigure terminal\b",
    r"\bset class-of-service\b", r"\binterface gigabitethernet\b",
    r"\bansible\b", r"\bnetconf\b",
)


class LayerResult(BaseModel):
    status: str
    findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    validation_result: str
    validation_layers: dict[str, LayerResult]


def _norm(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _actions(task: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for action in task.get("actions", []):
        if isinstance(action, dict):
            operation = _norm(action.get("action"))
            target = _norm(action.get("target"))
            if operation and target:
                result.add((operation, target))
    return result


def _layer_semantic(task: dict[str, Any]) -> LayerResult:
    findings: list[str] = []
    if not isinstance(task.get("task_type"), str) or not task["task_type"].strip():
        findings.append("task_type es obligatorio.")
    if not isinstance(task.get("scope"), (str, dict)) or not task.get("scope"):
        findings.append("scope es obligatorio.")
    actions = task.get("actions")
    if not isinstance(actions, list) or not actions:
        findings.append("actions debe contener al menos una acción.")
    else:
        for index, action in enumerate(actions):
            if not isinstance(action, dict) or not _norm(action.get("action")) or not _norm(action.get("target")):
                findings.append(f"La acción {index} debe definir action y target.")
    if not isinstance(task.get("rollback_steps"), list) or not task["rollback_steps"]:
        findings.append("rollback_steps debe contener al menos un paso.")
    if not isinstance(task.get("parameters_to_monitor"), list):
        findings.append("parameters_to_monitor debe ser una lista.")
    serialized = _norm(task)
    if any(re.search(pattern, serialized) for pattern in VENDOR_PATTERNS):
        findings.append("La tarea lógica contiene sintaxis o tecnología vendor-specific.")
    return LayerResult(
        status="FAIL" if findings else "PASS",
        findings=findings or ["La estructura es completa y vendor-agnostic."],
    )


def _layer_consistency(policy: dict[str, Any], task: dict[str, Any]) -> LayerResult:
    if not policy:
        return LayerResult(status="NOT_EVALUATED", findings=["No se recibió policy_json."])
    policy_scope = policy.get("scope") or policy.get("target_scope")
    task_scope = task.get("scope")
    if policy_scope is None or task_scope is None:
        return LayerResult(status="NOT_EVALUATED", findings=["No hay scopes comparables."])
    if _norm(policy_scope) != _norm(task_scope):
        return LayerResult(status="FAIL", findings=["El scope de la tarea no coincide con la política."])
    return LayerResult(status="PASS", findings=["El scope coincide con la política."])


def _layer_overlap(task: dict[str, Any], existing: list[dict[str, Any]] | None) -> LayerResult:
    if existing is None:
        return LayerResult(status="NOT_EVALUATED", findings=["No se pudo consultar logical_tasks."])
    expected = _actions(task)
    for record in existing:
        other = record.get("task_json") if isinstance(record.get("task_json"), dict) else record
        if expected and expected & _actions(other):
            return LayerResult(status="FAIL", findings=["Hay acciones y objetivos solapados con una tarea existente."])
    return LayerResult(status="PASS", findings=["No se detectó solapamiento con tareas existentes."])


def _layer_resources(task: dict[str, Any], resources: list[dict[str, Any]] | None) -> LayerResult:
    if resources is None or not resources:
        return LayerResult(status="NOT_EVALUATED", findings=["No hay evidencia de SSoT para validar recursos."])
    references = {_norm(action.get("target")) for action in task.get("actions", []) if isinstance(action, dict)}
    matched = []
    for resource in resources:
        names = {_norm(resource.get(key)) for key in ("resource_id", "hostname", "name", "scope")}
        if any(
            reference == name or reference in name or name in reference
            for reference in references
            for name in names
            if reference and name
        ):
            matched.append(resource)
    if not matched:
        return LayerResult(status="NOT_EVALUATED", findings=["No se relacionaron objetivos con recursos SSoT."])
    unavailable = [str(item.get("hostname") or item.get("resource_id")) for item in matched if _norm(item.get("status")) not in {"active", "available", "ready", "activo", "disponible"}]
    if unavailable:
        return LayerResult(status="FAIL", findings=[f"Recursos no disponibles: {', '.join(unavailable)}."])
    return LayerResult(status="PASS", findings=["Los recursos objetivo están disponibles."])


def _layer_security(task: dict[str, Any], policy: dict[str, Any], rules: list[dict[str, Any]] | None) -> LayerResult:
    if rules is None:
        return LayerResult(status="NOT_EVALUATED", findings=["No se pudieron consultar compliance_rules."])
    active = [rule for rule in rules if rule.get("is_active", rule.get("status", "ACTIVE")) in (True, "ACTIVE", "active")]
    if not active:
        return LayerResult(status="NOT_EVALUATED", findings=["No hay reglas activas para evaluar."])
    serialized = _norm({"task": task, "policy": policy})
    findings: list[str] = []
    for rule in active:
        if _norm(rule.get("severity")) not in {"blocking", "critical", "bloqueante", "critica", "crítica"}:
            continue
        expression = rule.get("rule_expression") or {}
        condition = _norm(expression.get("condition") if isinstance(expression, dict) else rule.get("condition"))
        if condition == "require_rollback_steps" and not task.get("rollback_steps"):
            findings.append(f"La regla {rule.get('rule_id')} exige rollback.")
        if condition == "forbid_vendor_specific_commands" and any(re.search(pattern, serialized) for pattern in VENDOR_PATTERNS):
            findings.append(f"La regla {rule.get('rule_id')} prohíbe sintaxis específica de fabricante.")
    return LayerResult(status="FAIL" if findings else "PASS", findings=findings or ["No se incumplieron reglas bloqueantes."])


def validate_logical_task(
    *, policy_json: dict[str, Any], logical_task_json: dict[str, Any], context: dict[str, Any],
) -> ValidationReport:
    layers = {
        "layer_1_semantic": _layer_semantic(logical_task_json),
        "layer_2_consistency": _layer_consistency(policy_json, logical_task_json),
        "layer_3_overlap": _layer_overlap(logical_task_json, context.get("existing_tasks")),
        "layer_4_resources": _layer_resources(logical_task_json, context.get("network_resources")),
        "layer_5_security": _layer_security(logical_task_json, policy_json, context.get("compliance_rules")),
    }
    statuses = [item.status for item in layers.values()]
    overall = "VALIDATED" if statuses and all(status == "PASS" for status in statuses) else "INVALID"
    return ValidationReport(validation_result=overall, validation_layers=layers)
