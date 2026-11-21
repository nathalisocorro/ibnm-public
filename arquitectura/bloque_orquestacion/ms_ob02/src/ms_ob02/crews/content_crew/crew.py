"""
Definición del Crew que agrupa a los agentes generador y validador con sus tareas.
Usa kickoff_async() para ser compatible con contextos asíncronos (Kafka consumer).
"""

from uuid import uuid4
from crewai import Crew, Process

from ms_ob02.crews.content_crew.config.agents import (
    command_generator_agent,
    command_validator_agent,
)
from ms_ob02.crews.content_crew.config.tasks import (
    create_generation_task,
    create_validation_task,
)


def build_command_crew(generation_task, validation_task) -> Crew:
    """
    Construye el Crew con los dos agentes y sus tareas correspondientes.

    El proceso es secuencial: primero se ejecuta la generación (MS-O05),
    luego la validación (MS-O06).
    """
    return Crew(
        agents=[command_generator_agent, command_validator_agent],
        tasks=[generation_task, validation_task],
        process=Process.sequential,
        verbose=True,
        memory=False,
    )


async def run_command_crew(
    atomic_task_json: dict,
    vendor: str,
    platform: str,
    format: str,
    attempt_count: int = 1,
    command_id: str = None,
    execution_profile: dict | None = None,
):
    """
    Función asíncrona que construye las tareas con los datos de entrada,
    ensambla el Crew y lo ejecuta con kickoff_async().

    Args:
        atomic_task_json: Tarea atómica con steps y rollback_steps.
        vendor: Fabricante objetivo (ej. "cisco").
        platform: Plataforma objetivo (ej. "IOS-XE").
        format: Formato del comando a generar (ej. "cli").
        attempt_count: Número de intento actual (1 a 3).
        command_id: UUID del comando (se genera si no se pasa).
        execution_profile: Perfil de ejecución del motor de decisión.

    Returns:
        El resultado crudo del Crew (objeto CrewOutput).
    """
    if command_id is None:
        command_id = str(uuid4())

    # Construir las tareas dinámicamente con los datos de entrada
    generation_task = create_generation_task(
        agent=command_generator_agent,
        atomic_task_json=atomic_task_json,
        vendor=vendor,
        platform=platform,
        format=format,
        attempt_count=attempt_count,
        command_id=command_id,
        execution_profile=execution_profile,
    )

    validation_task = create_validation_task(
        agent=command_validator_agent,
        generation_task=generation_task,
        atomic_task_json=atomic_task_json,
        vendor=vendor,
        platform=platform,
        format=format,
        attempt_count=attempt_count,
        command_id=command_id,
        execution_profile=execution_profile,
    )

    # Construir y ejecutar el Crew de forma asíncrona
    crew = build_command_crew(generation_task, validation_task)
    result = await crew.kickoff_async()
    return result