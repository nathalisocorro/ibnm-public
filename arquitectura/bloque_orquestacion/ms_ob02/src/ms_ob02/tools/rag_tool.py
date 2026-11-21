"""
Herramienta RAG personalizada para búsqueda en la base de conocimiento de red.

Usa el engine dedicado con NullPool para evitar el error
"Future attached to a different loop".
"""

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional


class NetworkKnowledgeToolInput(BaseModel):
    """Esquema de argumentos para NetworkKnowledgeTool."""
    query: str = Field(..., description="Texto a buscar")
    vendor: str = Field(..., description="Fabricante del dispositivo")
    platform: str = Field(..., description="Plataforma del dispositivo")
    technology: Optional[str] = Field(None, description="Tecnología opcional")


class NetworkKnowledgeTool(BaseTool):
    """
    Herramienta para buscar en la base de conocimiento de red.
    """

    name: str = "network_knowledge_search"
    description: str = (
        "Busca en la base de conocimiento de red para recuperar "
        "ejemplos de comandos, plantillas y reglas de cumplimiento "
        "para un fabricante y plataforma específicos. "
        "Úsala cuando necesites información específica sobre un fabricante "
        "o plataforma, o cuando no estés seguro de la sintaxis correcta. "
        "Si no encuentras resultados, genera los comandos basado en tus "
        "conocimientos. Si hay un error de conexión, intenta generar los "
        "comandos con tu conocimiento actual."
    )

    args_schema: type[BaseModel] = NetworkKnowledgeToolInput

    def _run(
        self,
        query: str,
        vendor: str,
        platform: str,
        technology: Optional[str] = None,
    ) -> str:
        """Método síncrono requerido por CrewAI."""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._arun(query, vendor, platform, technology)
                )
            finally:
                loop.close()
        except Exception as e:
            return (
                f"Error al buscar en la base de conocimiento: {str(e)}. "
                "Usa tus conocimientos para generar los comandos."
            )

    async def _arun(
        self,
        query: str,
        vendor: str,
        platform: str,
        technology: Optional[str] = None,
    ) -> str:
        """Busca en la base de conocimiento de forma async."""
        from ms_ob02.db.database import search_knowledge_base_tool

        try:
            results = await search_knowledge_base_tool(
                query=query,
                vendor=vendor,
                platform=platform,
                technology=technology,
            )

            if not results:
                return (
                    "No se encontraron resultados en la base de conocimiento "
                    "para esta consulta. Usa tus conocimientos para generar "
                    "los comandos."
                )

            return self._format_results(results)

        except Exception as e:
            return (
                f"Error al buscar en la base de conocimiento: {str(e)}. "
                "Usa tus conocimientos para generar los comandos."
            )

    def _format_results(self, results: list) -> str:
        """Formatea los resultados para el LLM."""
        output = ["=== Resultados de la base de conocimiento ===\n"]

        for i, result in enumerate(results, 1):
            output.append(f"--- Resultado {i} (score: {result['score']:.3f}) ---")
            output.append(f"Fuente: {result['source']}")
            if result.get("vendor"):
                output.append(f"Vendor: {result['vendor']}")
            if result.get("platform"):
                output.append(f"Plataforma: {result['platform']}")
            if result.get("technology"):
                output.append(f"Tecnología: {result['technology']}")
            output.append(f"Contenido:\n{result['chunk_text']}")
            output.append("")

        return "\n".join(output)