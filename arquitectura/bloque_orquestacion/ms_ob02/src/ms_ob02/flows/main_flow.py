"""
Flow de orquestación que gestiona el ciclo de vida completo de la generación
y validación de comandos. Utiliza el Crew definido en crew.py como unidad de trabajo.
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import uuid4

from crewai.flow.flow import Flow, listen, start

from ms_ob02.crews.content_crew.crew import run_command_crew


# =============================================================================
# ESTADO DEL FLOW (Pydantic Model)
# =============================================================================

class CommandFlowState(BaseModel):
    """
    Estado que persiste a lo largo del Flow.
    Almacena los datos de entrada, los resultados intermedios y el resultado final.
    """
    # Entrada
    atomic_task_json: dict = Field(default_factory=dict)
    vendor: str = ""
    platform: str = ""
    format: str = "cli"
    attempt_count: int = 1

    # Resultados intermedios
    generation_result: Optional[dict] = None

    # Resultado final
    final_result: Optional[dict] = None

    # Metadatos del flow
    flow_id: str = Field(default_factory=lambda: str(uuid4()))
    status: str = "initialized"


# =============================================================================
# FLOW: Orquestación del proceso completo
# =============================================================================

class CommandOrchestrationFlow(Flow[CommandFlowState]):
    """
    Flow que orquesta el proceso de generación y validación de comandos.
    """

    @start()
    def receive_input(self):
        """Paso 1: Recibir los datos de entrada."""
        print(f" Iniciando Flow {self.state.flow_id}")
        print(f"   Vendor: {self.state.vendor}, Platform: {self.state.platform}")
        self.state.status = "input_received"
        return "Input received"

    @listen(receive_input)
    async def execute_crew(self, _):     # ← async añadido
        """Paso 2: Ejecutar el Crew con los datos del estado."""
        print(" Ejecutando Crew de generación y validación...")

        # Ahora sí funciona el await
        result = await run_command_crew(
            atomic_task_json=self.state.atomic_task_json,
            vendor=self.state.vendor,
            platform=self.state.platform,
            format=self.state.format,
            attempt_count=self.state.attempt_count,
        )

        # Almacenar el resultado crudo en el estado
        self.state.generation_result = result.raw
        self.state.status = "crew_executed"

        print(" Crew ejecutado. Resultado almacenado.")
        return "Crew executed"

    @listen(execute_crew)
    async def finalize(self, _):         
        """Paso 3: Finalizar el Flow, almacenando el resultado final."""
        print(" Finalizando Flow...")
        self.state.final_result = {
            "flow_id": self.state.flow_id,
            "status": "completed",
            "result": self.state.generation_result,
        }
        self.state.status = "completed"
        return self.state.final_result