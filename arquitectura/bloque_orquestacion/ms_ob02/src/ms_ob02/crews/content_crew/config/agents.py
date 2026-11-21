from crewai import Agent, LLM
from ms_ob02.tools.rag_tool import NetworkKnowledgeTool

from ms_ob02.config.settings import settings

llm_agentes = LLM(
    model=settings.DEEPSEEK_MODEL,
    base_url=settings.DEEPSEEK_BASE_URL,
    api_key=settings.DEEPSEEK_API_KEY,
    temperature=settings.DEEPSEEK_TEMPERATURE,
    response_format={"type": "json_object"},
)

command_generator_agent = Agent(
    role="Multivendor Network Configuration Command Generator",
    goal=(
        "Transformar tareas atómicas JSON en comandos de configuración "
        "multivendor (Cisco, Juniper, Arista, Huawei, Nokia, VyOS, Cumulus, Mikrotik) "
        "de forma precisa, segura y ejecutable."
    ),
    backstory=(
        "Ingeniero de automatización de redes con amplia experiencia generando "
        "configuraciones para múltiples plataformas. Has trabajado en despliegues "
        "masivos donde cada vendor tiene su propia sintaxis, convenciones y "
        "restricciones. Domina la traducción de tareas atómicas en comandos "
        "perfectamente formados, evitando ambigüedades y asegurando compatibilidad "
        "con el sistema operativo de red correspondiente."
    ),
    llm=llm_agentes,
    tools=[NetworkKnowledgeTool()],
    verbose=True,
    allow_delegation=False,
    max_iter=20,
    max_retry_limit=2,
    respect_context_window=True,
    memory=False,
)

command_validator_agent = Agent(
    role="Multivendor Network Configuration Command Validator",
    goal=(
        "Validar sintaxis, coherencia, seguridad y compatibilidad de comandos "
        "multivendor generados (Cisco, Juniper, Arista, Huawei, Nokia) "
        "asegurando que sean seguros y ejecutables."
    ),
    backstory=(
        "Auditor experto en configuraciones de red para entornos de misión crítica. "
        "Ha participado en proyectos donde un solo comando mal formado puede causar "
        "interrupciones severas. Conoce profundamente las diferencias entre los "
        "sistemas operativos de red y aplica mejores prácticas de seguridad, "
        "consistencia y estandarización para garantizar que cada comando sea válido "
        "y seguro antes de su ejecución."
    ),
    llm=llm_agentes,
    verbose=True,
    allow_delegation=False,
    max_iter=20,
    max_retry_limit=2,
    respect_context_window=True,
    memory=False,
)
