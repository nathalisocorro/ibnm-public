"""Flow que coordina gestión, generación y validación de tareas lógicas."""

import json
import re
from typing import Any

from crewai.flow import Flow, listen, start
from pydantic import BaseModel, Field

from ms_pb02.crews.content_crew.content_crew import (
    run_logical_task_crew,
    run_logical_task_validation_crew,
)
from ms_pb02.db.database import load_validation_context
from ms_pb02.planning.validator import LayerResult, ValidationReport


class LogicalTaskFlowState(BaseModel):
    task_id: str = ""
    policy_id: str = ""
    intent_id: str = ""
    policy_json: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    raw_generation: str = ""
    generated: dict[str, Any] = Field(default_factory=dict)
    final_result: dict[str, Any] = Field(default_factory=dict)


_LAYER_CANONICAL = {
    "layer_1": "layer_1_semantic",
    "layer_2": "layer_2_consistency",
    "layer_3": "layer_3_overlap",
    "layer_4": "layer_4_resources",
    "layer_5": "layer_5_security",
}


def _normalise_layers(raw: dict[str, Any]) -> dict[str, Any]:
    """Mapea los nombres que emite el LLM a los canónicos por prefijo.

    Tolera: nombres exactos, variantes de mayúsculas, sufijos distintos
    (``layer_1_semantic`` vs ``layer_1_semantics``) y prefijo puro
    (``layer_1``). Ignora capas extra (``layer_6_*``) sin romper.
    """
    normalised: dict[str, Any] = {}
    for name, value in raw.items():
        clean = re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_")
        for prefix, canonical in _LAYER_CANONICAL.items():
            if clean == canonical or clean == prefix or clean.startswith(prefix + "_"):
                normalised[canonical] = value
                break
    return normalised

def _parse_generation(raw: str, state: LogicalTaskFlowState) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).removeprefix("json").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("El generador debe devolver un objeto JSON.")
    for field, expected in {
        "task_id": state.task_id,
        "policy_id": state.policy_id,
        "intent_id": state.intent_id,
    }.items():
        if payload.get(field) != expected:
            raise ValueError(f"El generador devolvió {field} inconsistente.")
    if not isinstance(payload.get("logical_task_json"), dict):
        raise ValueError("logical_task_json falta o no es un objeto.")
    return payload

def _parse_validation(raw: str) -> ValidationReport:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).removeprefix("json").strip()
    payload = json.loads(text)

    layers = payload.get("validation_layers")
    if not isinstance(layers, dict):
        raise ValueError("El agente validador no devolvió validation_layers.")

    normalised = _normalise_layers(layers)
    missing = set(_LAYER_CANONICAL.values()) - set(normalised)
    if missing:
        raise ValueError(
            f"Faltan capas obligatorias: {sorted(missing)}. "
            f"Recibidas: {sorted(layers)}."
        )

    report = ValidationReport(
        validation_result=payload.get("validation_result"),
        validation_layers={
            name: LayerResult.model_validate(value)
            for name, value in normalised.items()
        },
    )
    expected = (
        "VALIDATED"
        if all(layer.status == "PASS" for layer in report.validation_layers.values())
        else "INVALID"
    )
    if report.validation_result != expected:
        raise ValueError("El resultado general no coincide con los estados de las capas.")
    return report
class LogicalTaskFlow(Flow[LogicalTaskFlowState]):
    @start()
    def receive_policy(self) -> str:
        if not self.state.task_id or not self.state.policy_id or not self.state.intent_id:
            raise ValueError("Los identificadores de trazabilidad son obligatorios.")
        if not self.state.policy_json:
            raise ValueError("policy_json no puede estar vacío.")
        return "policy_received"

    @listen(receive_policy)
    async def generate_logical_task(self, _: str) -> str:
        self.state.raw_generation = await run_logical_task_crew(
            task_id=self.state.task_id,
            policy_id=self.state.policy_id,
            intent_id=self.state.intent_id,
            policy_json=self.state.policy_json,
            version=self.state.version,
        )
        self.state.generated = _parse_generation(self.state.raw_generation, self.state)
        return "task_generated"

    @listen(generate_logical_task)
    async def validate_generated_task(self, _: str) -> dict[str, Any]:
        context = await load_validation_context()
        task_json = self.state.generated["logical_task_json"]
        raw_validation = await run_logical_task_validation_crew(
            policy_json=self.state.policy_json,
            logical_task_json=task_json,
            validation_context=context,
        )
        report = _parse_validation(raw_validation)
        self.state.final_result = {
            "task_description": str(self.state.generated.get("task_description", "")),
            "logical_task_json": task_json,
            "validation_result": report.validation_result,
            "validation_layers": {
                name: value.model_dump() for name, value in report.validation_layers.items()
            },
        }
        return self.state.final_result
