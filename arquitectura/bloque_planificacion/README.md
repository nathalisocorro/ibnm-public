# Bloque de planificacion

El bloque mantiene una implementacion por paquete ejecutable:

- `ms_pb01`: recibe y valida las politicas de intencion.
- `ms_pb02`: concentra la gestion del ciclo de vida, generacion y validacion
  de tareas logicas que corresponden a PB04, PB05 y PB06.

La organizacion interna de `ms_pb02` separa responsabilidades mediante sus
modulos `crews`, `planning`, `db` y `kafka`.
