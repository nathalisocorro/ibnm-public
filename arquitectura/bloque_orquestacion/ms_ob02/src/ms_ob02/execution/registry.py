"""
Registro de adaptadores de ejecución.

Permite resolver el adaptador correspondiente a un ExecutionPlan.
"""

from ms_ob02.execution.ansible import AnsibleAdapter
from ms_ob02.execution.base import ExecutionAdapter
from ms_ob02.execution.cli_netmiko import CliNetmikoAdapter
from ms_ob02.execution.decision_models import ExecutionPlan
from ms_ob02.execution.netconf import NetconfAdapter
from ms_ob02.execution.restconf import RestconfAdapter


# Adaptadores disponibles, indexados por formato soportado.
_ADAPTERS: dict[str, type[ExecutionAdapter]] = {
    "cli": CliNetmikoAdapter,
    "netconf_xml": NetconfAdapter,
    "restconf_json": RestconfAdapter,
    "ansible_yaml": AnsibleAdapter,
}


def get_adapter(plan: ExecutionPlan) -> ExecutionAdapter:
    """
    Resuelve el adaptador que corresponde al formato del plan.

    Args:
        plan: Plan de ejecución.

    Returns:
        Instancia del adaptador.

    Raises:
        ValueError: si no hay adaptador para el formato del plan.
    """
    artifact_format = plan.artifact_format.value
    adapter_class = _ADAPTERS.get(artifact_format)

    if adapter_class is None:
        available = ", ".join(sorted(_ADAPTERS.keys()))
        raise ValueError(
            f"no hay adaptador de ejecución para el formato "
            f"'{artifact_format}'. Disponibles: {available}"
        )

    return adapter_class()


def supported_formats() -> list[str]:
    """
    Lista los formatos con adaptador disponible.

    Returns:
        Lista de formatos soportados.
    """
    return sorted(_ADAPTERS.keys())
