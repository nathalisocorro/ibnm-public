# MS-PB02 - Planificacion de tareas logicas

MS-PB02 concentra la logica que antes estaba separada en PB04, PB05 y PB06:

- gestiona el ciclo de vida de las tareas logicas;
- genera tareas vendor-agnostic con CrewAI;
- ejecuta un agente CrewAI validador de cinco capas;
- consulta dispositivos y reglas de compliance mediante el endpoint HTTP del SSoT;
- persiste el resultado y publica los eventos Kafka para Orquestacion.

El servicio se organiza como un unico paquete, siguiendo el patron de `ms_ob02`.
La cohesion de carpetas no elimina las responsabilidades del diseño: dentro de
`ms_pb02`, `planning/manager.py` cumple el papel de MS-P04, el Crew generador
cumple el papel de MS-P05 y el Crew validador cumple el papel de MS-P06.

## Ejecucion

Desde este directorio:

```bash
uv sync
uv run ms-pb02
```

La entrada principal consume `POLICY_PROPOSED` y `LOGICAL_TASK_FAULT` y publica
`LOGICAL_TASK_PROPOSED` o `POLICY_FAULT` despues de procesar cada evento.

## Desarrollo del Flow

El flujo interno esta dividido por responsabilidad, no por microservicio:

- `crews/content_crew`: generacion con CrewAI;
- `crews/content_crew`: agentes generador y validador;
- `planning/validator.py`: modelos estructurales del informe, no la decision del agente;
- `planning/manager.py`: ciclo de vida, reintentos y persistencia;
- `db/`: acceso a las tablas compartidas;
- `kafka/`: contratos, consumo y publicacion de eventos.

## SSoT local

El SSoT simulado se levanta desde la raiz del repositorio:

```bash
docker compose -f infraestructura/ssot-mock/compose.yaml up -d --build
```

Configura en `.env`:

```env
SSOT_BASE_URL=http://127.0.0.1:6303
SSOT_TIMEOUT_SECONDS=30
```

MS-PB02 consulta estos endpoints antes de ejecutar el agente validador:

- `GET /api/v1/ssot/devices`;
- `GET /api/v1/ssot/capacity`;
- `GET /api/v1/ssot/compliance-rules`.

El agente consulta el SSoT mediante `ssot_query`, interpreta la politica, la
tarea generada y las reglas recibidas, y devuelve un informe JSON con
`layer_1_semantic` hasta `layer_5_security`. El Flow valida solo la forma y
coherencia del informe antes de persistirlo y publicar el resultado.

Los valores de PostgreSQL, Kafka y DeepSeek se configuran mediante `.env`.

---

Welcome to the {{crew_name}} Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the dependencies:

(Optional) Lock the dependencies and install them by using the CLI command:

```bash
crewai install
```

### Customizing

**Add your `OPENAI_API_KEY` into the `.env` file**

- Modify `src/ms_pb02/config/agents.yaml` to define your agents
- Modify `src/ms_pb02/config/tasks.yaml` to define your tasks
- Modify `src/ms_pb02/crew.py` to add your own logic, tools and specific args
- Modify `src/ms_pb02/main.py` to add custom inputs for your agents and tasks

## Running the Project

To kickstart your flow and begin execution, run this from the root folder of your project:

```bash
crewai run
```

This command initializes the ms-pb02 Flow as defined in your configuration.

This example, unmodified, will run a content creation flow on AI Agents and save the output to `output/post.md`.

## Understanding Your Crew

The ms-pb02 Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the {{crew_name}} Crew or crewAI.

- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
