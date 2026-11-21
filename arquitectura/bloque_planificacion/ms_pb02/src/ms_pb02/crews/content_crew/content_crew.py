"""CrewAI para generar una tarea lógica vendor-agnostic."""

from crewai import Crew, Process, Task

from ms_pb02.crews.content_crew.config.agents import (
    logical_task_generator,
    logical_task_validator,
)
from ms_pb02.crews.content_crew.config.tasks import (
    create_generation_task,
    create_validation_task,
)


async def run_logical_task_crew(
    *,
    task_id: str,
    policy_id: str,
    intent_id: str,
    policy_json: dict,
    version: int,
) -> str:
    """Ejecuta el agente generador y devuelve su salida cruda."""
    task: Task = create_generation_task(
        agent=logical_task_generator,
        task_id=task_id,
        policy_id=policy_id,
        intent_id=intent_id,
        policy_json=policy_json,
        version=version,
    )
    crew = Crew(
        agents=[logical_task_generator],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        memory=False,
    )
    result = await crew.kickoff_async()
    return result.raw


async def run_logical_task_validation_crew(
    *, policy_json: dict, logical_task_json: dict, validation_context: dict,
) -> str:
    """Ejecuta el agente que interpreta SSoT y reglas de compliance."""
    task: Task = create_validation_task(
        agent=logical_task_validator,
        policy_json=policy_json,
        logical_task_json=logical_task_json,
        validation_context=validation_context,
    )
    crew = Crew(
        agents=[logical_task_validator],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        memory=False,
    )
    result = await crew.kickoff_async()
    return result.raw
