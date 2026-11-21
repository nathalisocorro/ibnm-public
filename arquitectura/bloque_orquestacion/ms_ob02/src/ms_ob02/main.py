"""
Punto de entrada principal de ms_ob02.
Gestiona la inicialización y ejecución del Consumidor Kafka.
"""

import asyncio
from ms_ob02.kafka.consumer import consume_atomic_tasks
from ms_ob02.execution.consumer import consume_command_sent
from ms_ob02.kafka.producer import kafka_producer
from ms_ob02.db.database import init_db, close_db


async def main():
    """Función principal que ejecuta el Consumidor Kafka."""
    # Inicializar base de datos (crear tablas si no existen)
    await init_db()
    print("Base de datos inicializada")

    # Iniciar producer Kafka
    await kafka_producer.start()
    print("Producer Kafka iniciado")

    print("ms_ob02 iniciado. Esperando eventos Kafka...")

    # Dos consumidores en paralelo:
    #  - consume_atomic_tasks: genera y valida comandos
    #  - consume_command_sent: aplica los comandos en los dispositivos
    try:
        await asyncio.gather(
            consume_atomic_tasks(),
            consume_command_sent(),
        )
    except asyncio.CancelledError:
        print("Consumidores detenidos")
    finally:
        await kafka_producer.stop()
        print("Producer Kafka detenido")
        await close_db()
        print("Conexión a base de datos cerrada")


def kickoff():
    """Wrapper síncrono para crewai run."""
    asyncio.run(main())


def plot():
    """Genera diagrama del Flow."""
    from ms_ob02.flows.main_flow import CommandOrchestrationFlow
    flow = CommandOrchestrationFlow()
    flow.plot()


def run_with_trigger():
    """Ejecuta el Flow con trigger payload."""
    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    from ms_ob02.flows.main_flow import CommandOrchestrationFlow, CommandFlowState

    initial_state = CommandFlowState(
        atomic_task_json=trigger_payload.get("atomic_task_json", {}),
        vendor=trigger_payload.get("vendor", ""),
        platform=trigger_payload.get("platform", ""),
        format=trigger_payload.get("format", "cli"),
        attempt_count=trigger_payload.get("attempt_count", 1),
    )

    flow = CommandOrchestrationFlow()
    result = flow.kickoff(initial_state.model_dump())
    return result


if __name__ == "__main__":
    asyncio.run(main())