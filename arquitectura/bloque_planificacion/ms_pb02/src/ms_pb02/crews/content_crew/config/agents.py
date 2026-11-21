"""Agente especializado en descomposición vendor-agnostic de políticas."""

from crewai import Agent, LLM

from ms_pb02.config.settings import settings
from ms_pb02.tools.ssot_tool import SSoTQueryTool


logical_task_generator = Agent(
    role="Especialista en tareas lógicas de redes",
    goal=(
        "Convertir políticas de red validadas en tareas lógicas reversibles, "
        "vendor-agnostic y trazables."
    ),
    backstory=(
        "Diseñas acciones de red abstractas siguiendo estándares de gestión "
        "de telecomunicaciones. Nunca produces CLI, NETCONF ni sintaxis de "
        "un fabricante concreto."
    ),
    llm=LLM(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=settings.DEEPSEEK_TEMPERATURE,
    ),
    allow_delegation=False,
    verbose=True,
)


logical_task_validator = Agent(
    role="Agente validador de tareas lógicas de redes",
    goal=(
        "Interpretar la política, la tarea lógica generada y la evidencia del SSoT "
        "para decidir si la tarea cumple las cinco capas de validación."
    ),
    backstory=(
        "Eres un auditor de automatización de redes. Consultas e interpretas "
        "capacidades de dispositivos y reglas de compliance del SSoT. No inventas "
        "evidencia: si falta información, informas NOT_EVALUATED. Devuelves siempre "
        "un informe JSON trazable y explicas los hallazgos de cada capa."
    ),
    llm=LLM(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=settings.DEEPSEEK_TEMPERATURE,
    ),
    tools=[SSoTQueryTool()],
    allow_delegation=False,
    verbose=True,
)
