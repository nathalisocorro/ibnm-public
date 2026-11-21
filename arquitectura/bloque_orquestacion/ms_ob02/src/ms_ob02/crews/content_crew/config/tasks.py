"""
Definición de tareas para el sistema multi-agente de generación y validación de comandos.
Basado en la documentación oficial de CrewAI.

NOTA: No se usan guardrails ni `output_pydantic`. La validación del JSON
se hace en el consumidor (consumer.py) al parsear `result.raw`.
"""

import json
from typing import List, Optional
from crewai import Task, Agent


# =====================================================
# PERFIL DE EJECUCIÓN
# =====================================================

def _format_execution_profile(profile: dict | None) -> str:
    """
    Formatea el perfil de ejecución para inyectarlo en el prompt.

    Args:
        profile: execution_profile generado por el motor de decisión.

    Returns:
        Bloque de texto con el perfil, o cadena vacía si no hay perfil.
    """
    if not profile:
        return ""

    capabilities = ", ".join(profile.get("required_capabilities", [])) or "ninguna"

    return (
        "\nPERFIL DE EJECUCIÓN (OBLIGATORIO):\n"
        f"- Formato requerido: {profile.get('requested_format')}\n"
        f"- Formatos permitidos: {', '.join(profile.get('allowed_formats', []))}\n"
        f"- Protocolo de transporte: {profile.get('protocol')}\n"
        f"- Ejecutor previsto: {profile.get('executor')}\n"
        f"- Capacidades requeridas: {capabilities}\n"
        f"- Rollback requerido: {profile.get('rollback_required')}\n"
        "El payload de CADA versión debe respetar estrictamente el formato "
        "requerido. No generes comandos en otro formato.\n"
    )


# =====================================================
# TAREA 1: GENERACIÓN DE COMANDOS (MS-O05)
# =====================================================

def create_generation_task(
    agent: Agent,
    atomic_task_json: dict,
    vendor: str,
    platform: str,
    format: str,
    attempt_count: int,
    command_id: str,
    execution_profile: dict | None = None,
) -> Task:
    """Crea la tarea de generación de comandos."""
    return Task(
        name="generate_command_versions",
        description=(
            f"Recibirás una tarea atómica de red: {json.dumps(atomic_task_json)}\n"
            f"Fabricante: {vendor}\n"
            f"Plataforma: {platform}\n"
            f"Formato: {format}\n"
            f"Intento: {attempt_count}\n"
            f"command_id: {command_id}\n"
            + _format_execution_profile(execution_profile)
            + "\n"
            "OBJETIVO: Generar DOS versiones de comandos que sean estructuralmente "
            "equivalentes. La diferencia entre ambas versiones debe ser unicamente "
            "en la redacción del prompt, NO en el enfoque, la estructura ni el "
            "contenido del comando resultante.\n\n"
            "PRINCIPIO CLAVE: si el modelo es fiable, las dos versiones deben ser "
            "casi idénticas. La variación del prompt es un CONTROL DE CALIDAD para "
            "detectar alucinaciones, no una invitación a explorar enfoques distintos.\n\n"
            "VARIACIONES PERMITIDAS entre el prompt A y el prompt B:\n"
            "- Sinónimos: 'Genera' ↔ 'Crea', 'Requisitos' ↔ 'Pasos a implementar'.\n"
            "- Orden de cláusulas: la misma información, reordenada.\n"
            "- Tono: directo ↔ formal.\n"
            "- Formato visual: lista numerada ↔ viñetas ↔ párrafo con separadores.\n\n"
            "VARIACIONES PROHIBIDAS:\n"
            "- NO cambiar el enfoque.\n"
            "- NO cambiar la estructura del comando.\n"
            "- NO cambiar los parámetros.\n"
            "- NO añadir ni eliminar pasos.\n"
            "- NO cambiar el formato de salida.\n\n"
            "PASOS A SEGUIR:\n"
            "1. Consultar la base de conocimiento RAG (pgvector).\n"
            "2. Construir el PROMPT A con un estilo.\n"
            "3. Invocar al LLM con el PROMPT A.\n"
            "4. Construir el PROMPT B con variaciones ligeras.\n"
            "5. Invocar al LLM con el PROMPT B.\n"
            "6. Limpiar y formatear ambas versiones.\n"
            "7. Empaquetar el resultado en el JSON de salida.\n\n"
            "FORMATO DE SALIDA OBLIGATORIO:\n"
            "- Devuelve ÚNICAMENTE un objeto JSON válido.\n"
            "- NO incluyas bloques de código markdown.\n"
            "- NO incluyas texto antes ni después del JSON.\n"
            "- El JSON debe poder parsearse directamente con json.loads().\n"
            "- El campo 'format' de cada versión debe ser EXACTAMENTE: "
            f"'{format}'.\n"
        ),
        expected_output=(
            "Un objeto JSON válido con la estructura: "
            "{command_id: str, validation_result: 'PENDING', selected_version: null, "
            "equivalence_score: null, commands: [{version: 1, format: str, payload: str}, "
            "{version: 2, format: str, payload: str}], notes: str}."
        ),
        agent=agent,
    )


# =====================================================
# TAREA 2: VALIDACIÓN DE COMANDOS (MS-O06)
# =====================================================

def create_validation_task(
    agent: Agent,
    generation_task: Task,
    atomic_task_json: dict,
    vendor: str,
    platform: str,
    format: str,
    attempt_count: int,
    command_id: str,
    execution_profile: dict | None = None,
) -> Task:
    """Crea la tarea de validación de comandos."""
    return Task(
        name="validate_command_versions",
        description=(
            f"Recibirás del contexto las dos versiones de comandos generadas.\n"
            f"command_id: {command_id}\n"
            f"Datos de la tarea atómica: {json.dumps(atomic_task_json)}\n"
            f"Fabricante: {vendor}, Plataforma: {platform}, Formato: {format}\n"
            + _format_execution_profile(execution_profile)
            + "\n"
            "Debes validar esas dos versiones realizando una validación cruzada "
            "en dos capas.\n\n"
            "Sigue estos pasos en orden:\n"
            "1. Obtener del contexto el array 'commands' con las dos traducciones.\n"
            "2. Validar la sintaxis (Capa 1) de cada versión según su formato.\n"
            "3. Comparar la equivalencia semántica (Capa 2):\n"
            "   - Normalizar ambos payloads.\n"
            "   - Calcular equivalence_score entre 0 y 1.\n"
            "4. Decidir el resultado: si Capa 1 pasa y equivalence_score >= 0.95 → 'PASS'.\n"
            "5. Seleccionar la versión ganadora.\n"
            "6. Empaquetar el resultado en el JSON de salida.\n\n"
            "FORMATO DE SALIDA OBLIGATORIO:\n"
            "- Devuelve ÚNICAMENTE un objeto JSON válido.\n"
            "- NO incluyas bloques de código markdown.\n"
            "- El JSON debe poder parsearse directamente con json.loads().\n"
            "\n\nIMPORTANTE: cuando validation_result sea 'PASS', debes incluir en "
            "selected_payload el contenido COMPLETO del campo 'payload' de la versión "
            "que seleccionaste (la que está en commands[selected_version - 1]['payload'] "
            "del output del generador). No lo resumas, no lo modifiques, no lo trunques: "
            "cópialo literalmente. Este campo es el que se enviará al dispositivo real.\n"
        ),
        expected_output=(
            "Un objeto JSON válido con la estructura: "
            "{command_id: str, validation_result: 'PASS'|'INVALID', "
            "layer_1_syntax: 'PASS'|'FAIL', layer_2_equivalence: 'PASS'|'FAIL', "
            "selected_version: int|null, selected_payload: str|null, "
            "equivalence_score: float, notes: str}. "
            "Si validation_result es 'PASS', selected_payload DEBE contener el payload "
            "completo de la versión seleccionada, copiado literalmente del output del "
            "generador. Si es 'INVALID', selected_payload debe ser null."
        ),
        agent=agent,
        context=[generation_task],
    )