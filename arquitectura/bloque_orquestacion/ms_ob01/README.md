# MS-OB01 - AtomicTaskManagement

MS-OB01 gestiona el estado `new_atomic_task` del bloque de orquestacion. No
traduce tareas a comandos ni ejecuta dispositivos; esas responsabilidades
pertenecen a los agentes y servicios posteriores.

## Responsabilidades

- consumir `LOGICAL_TASK_PROPOSED`;
- crear y actualizar `atomic_tasks`;
- ejecutar localmente el agente generador que representa MS-O02;
- ejecutar localmente el agente validador que representa MS-O03;
- registrar el ciclo de vida en `atomic_task_registry`;
- publicar `ATOMIC_TASK_PROPOSED` para MS-OB02;
- publicar `LOGICAL_TASK_FAULT` cuando se agotan tres versiones.

La carpeta es autocontenida siguiendo el patron de `ms_ob02`, pero el servicio
mantiene la responsabilidad de gestion definida para MS-O01.

## Configuracion

Copia las variables necesarias en `.env`:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ibnm
POSTGRES_USER=ibnm
POSTGRES_PASSWORD=...

DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TEMPERATURE=0.0

KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC_LOGICAL_TASK_PROPOSED=ibnn.logical_task_proposed
KAFKA_TOPIC_ATOMIC_TASK_PROPOSED=ibnn.atomic_task_proposed
KAFKA_TOPIC_LOGICAL_TASK_FAULT=ibnn.logical_task_fault
KAFKA_GROUP_ID=ms-ob01-consumer-group
```

## Ejecucion

```bash
uv sync
uv run ms-ob01
```

El consumidor confirma el offset solo despues de completar la coordinacion y
publicar el resultado. Si ocurre un error, el mensaje queda disponible para
reintento.

## Agentes cohesionados

Para mantener la estructura de carpetas reducida, MS-O02 y MS-O03 viven dentro
del paquete de MS-O01 como agentes CrewAI locales:

- `crews/atomic_task_crew.py`: generador y validador;
- `orchestration/manager.py`: coordinacion y ciclo de vida.

El generador debe incluir en `atomic_task_json` `vendor`, `platform`,
`device_targets`, `steps` y `rollback_steps`. El validador devuelve
`validation_result` igual a `PASS` para aceptar la tarea.

## Flujo

```text
LOGICAL_TASK_PROPOSED
  -> atomic_tasks = PENDING
  -> agente MS-O02 local: generate
  -> agente MS-O03 local: validate
  -> atomic_tasks = COMPLETED
  -> ATOMIC_TASK_PROPOSED
```

Si las tres versiones fallan:

```text
atomic_tasks = FAILED
  -> LOGICAL_TASK_FAULT
```
