"""Tarea dinámica para generar logical_task_json."""

import json

from crewai import Agent, Task


def _json_dump(value: object) -> str:
    """Serializa contexto de BD, incluidos UUIDs, para el prompt del agente."""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def create_generation_task(
    *, agent: Agent, task_id: str, policy_id: str, intent_id: str,
    policy_json: dict, version: int,
) -> Task:
    policy = _json_dump(policy_json)
    return Task(
        description=(
            "Genera UNA tarea lógica para implementar la política recibida. "
            "La salida debe ser únicamente JSON válido, sin Markdown. "
            "La tarea es vendor-agnostic: están prohibidos CLI, comandos, "
            "nombres de interfaces y sintaxis de Cisco, Juniper, Huawei o Ansible.\n\n"
            "El scope de la política identifica el recurso objetivo. Usa ese valor "
            "exactamente como target de las acciones y rollback cuando se refieran "
            "al recurso principal. No uses alias genéricos como edge_link, "
            "enlace_de_borde o link; el target debe poder relacionarse directamente "
            "con el SSoT.\n\n"
            f"task_id obligatorio: {task_id}\npolicy_id obligatorio: {policy_id}\n"
            f"intent_id obligatorio: {intent_id}\nversión de generación: {version}\n\n"
            f"Política:\n{policy}\n\n"
            "Esquema obligatorio:\n"
            "{\n"
            f'  "task_id": "{task_id}",\n  "policy_id": "{policy_id}",\n'
            f'  "intent_id": "{intent_id}",\n  "task_description": "...",\n'
            '  "logical_task_json": {"task_type": "...", "scope": "...", '
            '"actions": [{"step": 1, "action": "...", "target": "..."}], '
            '"rollback_steps": [{"step": 1, "action": "..."}], '
            '"parameters_to_monitor": ["..."]}\n}'
        ),
        expected_output="Un objeto JSON válido que cumple exactamente el esquema indicado.",
        agent=agent,
    )


def create_validation_task(
    *, agent: Agent, policy_json: dict, logical_task_json: dict,
    validation_context: dict,
) -> Task:
    return Task(
        description=(
            "Valida la tarea lógica contra la política y la evidencia recibida. "
            "Antes de decidir, usa la herramienta ssot_query con resource=all para "
            "consultar dispositivos, capacidades y reglas de compliance vigentes; compara "
            "esa respuesta con la evidencia recibida. Interpreta las reglas de compliance "
            "y los atributos de los dispositivos. "
            "No inventes datos y no uses reglas externas a la evidencia. Devuelve "
            "únicamente JSON válido, sin Markdown, con este esquema exacto:\n"
            '{"validation_result":"VALIDATED|INVALID",'
            '"validation_layers":{"layer_1_semantic":{"status":"PASS|FAIL|NOT_EVALUATED",'
            '"findings":[],"evidence":[]},"layer_2_consistency":{},'
            '"layer_3_overlap":{},"layer_4_resources":{},"layer_5_security":{}}}\n\n'
            f"POLÍTICA:\n{_json_dump(policy_json)}\n\n"
            f"TAREA LÓGICA:\n{_json_dump(logical_task_json)}\n\n"
            f"EVIDENCIA SSoT Y CONTEXTO:\n{_json_dump(validation_context)}\n\n"
            "VALIDA: semántica, consistencia de scope, solapamiento, disponibilidad "
            "de recursos y compliance/seguridad. El resultado general solo puede ser "
            "VALIDATED si las cinco capas son PASS."
        ),
        expected_output="Un informe JSON con las cinco capas y evidencia trazable.",
        agent=agent,
    )
