"""Agentes locales que cohesionan MS-O02 y MS-O03 dentro de MS-O01."""

import json

from crewai import Agent, Crew, LLM, Process, Task

from ms_ob01.config.settings import settings


llm = LLM(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    temperature=settings.DEEPSEEK_TEMPERATURE,
)

atomic_task_generator = Agent(
    role="Agente generador de tareas atomicas",
    goal=(
        "Descomponer una tarea logica en una tarea atomica ejecutable, con pasos "
        "reversibles, trazabilidad completa y un nivel de criticidad clasificado "
        "segun las reglas del sistema."
    ),
    backstory=(
        "Eres especialista en convertir tareas logicas en operaciones atomicas "
        "para un dispositivo objetivo. Debes producir vendor, platform, "
        "device_targets, steps y rollback_steps. No generas comandos CLI ni XML.\n\n"

        "CRITICALITY — clasifica SIEMPRE la tarea atomica en uno de estos 4 "
        "niveles. Aplica la PRIMERA regla que se cumpla, en orden de precedencia:\n"
        "1. CRITICAL → la tarea afecta a MAS DE UN dispositivo, o a un comodin "
        '("all", "*", "todos", "any") en device_targets. Cualquier operacion '
        "multidispositivo o masiva, incluso si es de solo lectura.\n"
        "2. HIGH → la tarea es una mutacion de configuracion que REQUIERE "
        "rollback (rollback_steps no vacio) y afecta a UN solo dispositivo. "
        "Incluye reloads, commits, cambios de version de OS/firmware, ACLs, "
        "routing, VPN.\n"
        "3. MEDIUM → la tarea es una mutacion de configuracion MENOR sobre UN "
        "solo dispositivo y NO requiere rollback (rollback_steps vacio). "
        "Ejemplos: banner, descripcion de interfaz, hostname, NTP, syslog "
        "server.\n"
        "4. LOW → la tarea es una CONSULTA / LECTURA sin efectos: show, "
        "display, get, ping, traceroute, status, list, describe. No modifica "
        "configuracion.\n"
        "Reglas adicionales de criticality:\n"
        "- Si dudas entre dos niveles, elige el MAS ALTO.\n"
        "- NUNCA uses LOW para nada que escriba, aplique, borre, recargue o "
        "reinicie. Si hay set/config/apply/commit/write/delete/reload/reboot/no "
        "en los steps, como minimo es MEDIUM.\n"
        "- criticality va en el NIVEL SUPERIOR del JSON de salida, no dentro de "
        "atomic_task_json.\n"
        "- Valores permitidos (exactos, mayusculas): LOW | MEDIUM | HIGH | "
        "CRITICAL.\n\n"

        "FORMAT — el canal de ejecucion DEBE emitirse OBLIGATORIAMENTE en el "
        "NIVEL SUPERIOR del JSON de salida. Valores permitidos: cli | "
        "netconf_xml | restconf_json | ansible_yaml.\n"
        "Todos los device_targets comparten vendor, platform y os_version, PERO "
        "pueden requerir formatos distintos entre si. Por eso la tarea atomica "
        "lleva:\n"
        "- format            → formato PRINCIPAL (el que se intenta por defecto).\n"
        "- format_preference → formato ALTERNATIVO valido (el otro que puede "
        "soportar). Es OPCIONAL. Si existe, DEBE ser distinto de format y DEBE "
        "estar soportado por vendor/platform.\n"
        "Reglas de format:\n"
        "- Si task_json.preferred_format existe, usalo como format SIEMPRE que "
        "sea soportado por vendor/platform. Si no lo es → devuelve "
        '{"error":"FORMAT_NOT_SUPPORTED","details":"..."} y no emitas '
        "atomic_task_json.\n"
        "- Si task_json.preferred_formats (plural) existe:\n"
        "  * El primer formato compatible con vendor/platform → format.\n"
        "  * El segundo formato compatible → format_preference.\n"
        "  * Si solo hay uno compatible → format_preference = null.\n"
        "  * Si ninguno es compatible → "
        '{"error":"FORMAT_NOT_SUPPORTED","details":"..."}.\n'
        "- Si no hay preferencia del usuario:\n"
        "  * format = cli (default salvo que la tabla de soporte sugiera otro).\n"
        "  * format_preference = null, salvo que el vendor/platform soporte "
        "netconf_xml o ansible_yaml y el scope lo justifique (multivendor, "
        "orquestacion, despliegue masivo). En ese caso elige como "
        "format_preference el alternativo mas util.\n"
        "- format_preference NUNCA puede ser igual a format.\n"
        "- NUNCA elijas formatos fuera de {cli, netconf_xml, restconf_json, "
        "ansible_yaml}.\n\n"

        "TABLA DE SOPORTE (orientativa; respeta la real de MS-O04):\n"
        "- cisco/ios       → cli\n"
        "- cisco/ios-xe    → cli, netconf_xml, restconf_json\n"
        "- cisco/nxos      → cli, netconf_xml, restconf_json\n"
        "- juniper/junos   → cli, netconf_xml\n"
        "- arista/eos      → cli, restconf_json\n"
        "- huawei/vrp      → cli, netconf_xml\n"
        "- generic/generic → cli, ansible_yaml"
    ),
    llm=llm,
    allow_delegation=False,
    verbose=True,
)

atomic_task_validator = Agent(
    role="Agente validador de tareas atomicas",
    goal=(
        "Validar que la tarea atomica sea completa, coherente, reversible y "
        "compatible con la tarea logica recibida."
    ),
    backstory=(
        "Eres auditor de tareas atomicas. Rechazas tareas sin pasos, rollback, "
        "vendor, plataforma o dispositivos objetivo. No inventas evidencia y "
        "devuelves un resultado JSON estrictamente estructurado."
    ),
    llm=llm,
    allow_delegation=False,
    verbose=True,
)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).removeprefix("json").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("El agente no devolvio un objeto JSON.")
    return payload


async def generate_atomic_task(
    *,
    logical_task: dict,
    device_inventory: dict,
    device_configurations: list[dict],
    version: int,
) -> dict:
    scope = logical_task.get("scope", "")
    task = Task(
        description=(
            "Genera una tarea atomica a partir de la tarea logica. Devuelve solo "
            "JSON valido, sin Markdown. Usa exclusivamente los datos de "
            "INVENTARIO SSoT para vendor, platform, os_version y device_targets; "
            "no los infieras ni uses generic/unknown.\n\n"

            "Esquema obligatorio. criticality, format y format_preference van en "
            "el NIVEL SUPERIOR, junto a atomic_task_json, NO dentro de el:\n"
            '{"task_description":"...",'
            '"criticality":"LOW|MEDIUM|HIGH|CRITICAL",'
            '"format":"cli|netconf_xml|restconf_json|ansible_yaml",'
            '"format_preference":"cli|netconf_xml|restconf_json|ansible_yaml|null",'
            '"atomic_task_json":{'
            '"vendor":"<SSOT>","platform":"<SSOT>","os_version":"<SSOT>",'
            '"device_targets":["..."],'
            '"steps":[{"step":1,"operation":"..."}],'
            '"rollback_steps":[{"step":1,"operation":"..."}]},'
            '"required_capabilities":{},"executor_preference":"AUTO"}\n\n'

            "Ejemplos de criticality (few-shot):\n"
            '  - device_targets=["r1"], steps=["show ip interface brief"], '
            'rollback_steps=[] → criticality="LOW"\n'
            '  - device_targets=["r1"], steps=["configure terminal",'
            '"banner motd ^Hola^"], rollback_steps=[] → criticality="MEDIUM"\n'
            '  - device_targets=["r1"], steps=["configure terminal",'
            '"ip route 0.0.0.0/0 10.0.0.1"], '
            'rollback_steps=["no ip route 0.0.0.0/0 10.0.0.1"] '
            '→ criticality="HIGH"\n'
            '  - device_targets=["r1","r2","r3"], '
            'steps=["copy running-config startup-config"], '
            'rollback_steps=[] → criticality="CRITICAL"\n'
            '  - device_targets=["all"], steps=["show version"], '
            'rollback_steps=[] → criticality="CRITICAL"\n\n'

            "Ejemplos de format y format_preference (few-shot):\n"
            '  - cisco/ios-xe, preferred_formats=["netconf_xml","cli"] '
            '→ format="netconf_xml", format_preference="cli"\n'
            '  - cisco/ios, preferred_formats=["netconf_xml","ansible_yaml"] '
            '→ devuelve {"error":"FORMAT_NOT_SUPPORTED","details":"..."} '
            'sin atomic_task_json\n'
            '  - cisco/ios-xe, sin preferred_formats, scope="multi-device deploy" '
            '→ format="cli", format_preference="ansible_yaml"\n'
            '  - cisco/ios, sin preferred_formats, single device '
            '→ format="cli", format_preference=null\n'
            '  - generic/generic, sin preferred_formats '
            '→ format="cli", format_preference=null\n\n'

            f"INVENTARIO SSoT AUTORITATIVO:\n{_json_dump(device_inventory)}\n\n"
            f"CONFIGURACION OBSERVADA SSoT:\n{_json_dump(device_configurations)}\n\n"
            f"VERSION: {version}\nSCOPE SUGERIDO: {scope}\n"
            f"TAREA LOGICA:\n{_json_dump(logical_task)}"
        ),
        expected_output=(
            "Objeto JSON con task_description, criticality, format y "
            "format_preference en el nivel superior, y atomic_task_json "
            "completo (vendor, platform, os_version, device_targets, steps, "
            "rollback_steps)."
        ),
        agent=atomic_task_generator,
    )
    crew = Crew(
        agents=[atomic_task_generator],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        memory=False,
    )
    return _parse_json((await crew.kickoff_async()).raw)



async def validate_atomic_task(
    *,
    logical_task: dict,
    atomic_task: dict,
    validation_context: dict,
) -> dict:
    task = Task(
        description=(
            "Valida la tarea atomica contra la tarea logica. Devuelve solo JSON "
            "valido con validation_result PASS o INVALID, findings y evidence.\n\n"
            "El resultado es PASS solo si se cumplen TODAS estas condiciones:\n"

            "1. atomic_task_json incluye vendor, platform, os_version, "
            "device_targets y steps no vacios. rollback_steps debe ser una lista "
            "y solo es obligatorio para cambios que requieren reversi\u00f3n.\n"
            "2. Los objetivos son coherentes con el scope de la tarea logica.\n"
            "3. Todos los device_targets comparten vendor/platform/os_version; "
            "si el validador detecta mezcla de vendors o platforms → INVALID "
            'con finding "device_targets heterogeneo no permitido en una tarea '
            'atomica".\n'

            "4. criticality esta presente en el NIVEL SUPERIOR y pertenece a "
            "{LOW, MEDIUM, HIGH, CRITICAL} (mayusculas exactas).\n"
            "5. criticality es COHERENTE con atomic_task_json:\n"
            '   - Si len(device_targets) > 1 o contiene "all"/"*"/"todos"/"any" '
            'y criticality != "CRITICAL" → INVALID con finding '
            '"criticality infravalorado: multidispositivo debe ser CRITICAL".\n'
            "   - Si rollback_steps != [] y device_targets tiene 1 elemento y "
            'criticality not in {"HIGH","CRITICAL"} → INVALID con finding '
            '"criticality infravalorado: mutacion con rollback debe ser al '
            'menos HIGH".\n'
            "   - Si rollback_steps == [] y todos los steps son de lectura "
            "(show/display/get/ping/traceroute/status/list/describe) y "
            'criticality != "LOW" → INVALID con finding '
            '"criticality sobrevalorado: consulta debe ser LOW".\n'

            "6. format esta en el NIVEL SUPERIOR y pertenece a "
            "{cli, netconf_xml, restconf_json, ansible_yaml} (exactos).\n"
            "7. format es compatible con vendor/platform de atomic_task_json "
            "segun la tabla del punto 10. Si no → INVALID con finding "
            '"format <X> no soportado por <vendor>/<platform>".\n'

            "8. format_preference es OPCIONAL:\n"
            "   - Si es null o ausente, se acepta.\n"
            "   - Si esta presente, debe pertenecer al enum "
            "{cli, netconf_xml, restconf_json, ansible_yaml}.\n"
            "   - Debe ser DISTINTO de format; si format == format_preference "
            '→ INVALID con finding "format_preference debe ser distinto de '
            'format".\n'
            "   - Debe estar soportado por vendor/platform; si no → INVALID "
            'con finding "format_preference <X> no soportado por '
            '<vendor>/<platform>".\n'

            "9. Si task_json.preferred_formats (o preferred_format) existe en la "
            "tarea logica:\n"
            "   - format debe estar en la lista solicitada; si no → INVALID "
            'con finding "la crew no respeto preferred_formats".\n'
            "   - Si hay >=2 formatos solicitados y soportados por el "
            "vendor/platform, format_preference debe estar presente y ser el "
            "segundo compatible.\n"
            "   - Si solo hay 1 formato soportado, format_preference debe ser "
            "null.\n"

            "10. Coherencia format/format_preference ↔ vendor/platform "
            "(orientativa; la tabla real es la de MS-O04):\n"
            "   - cisco/ios → solo cli.\n"
            "   - cisco/ios-xe → cli, netconf_xml, restconf_json.\n"
            "   - cisco/nxos → cli, netconf_xml, restconf_json.\n"
            "   - juniper/junos → cli, netconf_xml.\n"
            "   - arista/eos → cli, restconf_json.\n"
            "   - huawei/vrp → cli, netconf_xml.\n"
            "   - generic/generic → cli, ansible_yaml.\n"
            "   - Cualquier format fuera de esa lista para el vendor/platform "
            '→ INVALID con finding "el vendor no soporta ese formato".\n\n'

            'Devuelve exactamente este JSON:\n'
            '{"validation_result":"PASS|INVALID","findings":[],"evidence":[]}\n\n'

            f"TAREA LOGICA:\n{_json_dump(logical_task)}\n\n"
            f"TAREA ATOMICA:\n{_json_dump(atomic_task)}\n\n"
            f"EVIDENCIA SSoT Y VALIDACION DETERMINISTA:\n{_json_dump(validation_context)}"
        ),
        expected_output="Informe JSON de validacion atomica.",
        agent=atomic_task_validator,
    )
    crew = Crew(
        agents=[atomic_task_validator],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        memory=False,
    )
    return _parse_json((await crew.kickoff_async()).raw)
