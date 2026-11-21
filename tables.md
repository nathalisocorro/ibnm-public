# Estructura de la base de datos `ibnm_test`

Convenciones:

- **PK** = Primary Key · **FK** = Foreign Key · **UQ** = UNIQUE · **CK** = CHECK
- Todas las columnas `uuid` son `uuid` de PostgreSQL (sin default, se generan en aplicación)
- Todos los timestamps son `timestamp with time zone` (timestamptz)

---

## Índice

| #   | Tabla                                                     | Rol                           |
| --- | --------------------------------------------------------- | ----------------------------- |
| 1   | [`intents`](#1-intents)                                   | Estado · Bloque Traducción    |
| 2   | [`policies`](#2-policies)                                 | Estado · Bloque Planificación |
| 3   | [`logical_tasks`](#3-logical_tasks)                       | Estado · Bloque Planificación |
| 4   | [`atomic_tasks`](#4-atomic_tasks)                         | Estado · Bloque Orquestación  |
| 5   | [`policy_registry`](#5-policy_registry)                   | Registro append-only          |
| 6   | [`logical_task_registry`](#6-logical_task_registry)       | Registro append-only          |
| 7   | [`atomic_task_registry`](#7-atomic_task_registry)         | Registro append-only          |
| 8   | [`policy_validations`](#8-policy_validations)             | Validación 5 capas            |
| 9   | [`logical_task_validations`](#9-logical_task_validations) | Validación 5 capas            |
| 10  | [`network_devices`](#10-network_devices)                  | SSoT                          |
| 11  | [`compliance_rules`](#11-compliance_rules)                | SSoT                          |
| 12  | [`task_documents`](#12-task_documents)                    | Catálogo RAG                  |
| 13  | [`task_examples`](#13-task_examples)                      | Catálogo RAG                  |
| 14  | [`users`](#14-users)                                      | Autenticación                 |
| 15  | [`roles`](#15-roles)                                      | Autorización                  |

---

## Bloque A — Tablas de estado (ciclo de vida)

### 1. `intents`

Una fila por intención del operador. Actualizable.

| #   | Columna           | Tipo         | Nullable | Default       |
| --- | ----------------- | ------------ | -------- | ------------- |
| 1   | `intent_id`       | uuid         | NOT NULL | —             |
| 2   | `user_id`         | uuid         | NOT NULL | —             |
| 3   | `action`          | varchar(100) | NOT NULL | —             |
| 4   | `object`          | varchar(255) | NOT NULL | —             |
| 5   | `technology`      | varchar(100) | NOT NULL | —             |
| 6   | `mechanism`       | text         | NULL     | —             |
| 7   | `condition`       | text         | NULL     | —             |
| 8   | `parameters`      | jsonb        | NOT NULL | `'{}'::jsonb` |
| 9   | `raw_text`        | text         | NOT NULL | —             |
| 10  | `json_translated` | jsonb        | NULL     | —             |
| 11  | `status`          | varchar(30)  | NOT NULL | `'DRAFT'`     |
| 12  | `priority_level`  | integer      | NOT NULL | —             |
| 13  | `scope_level`     | varchar(20)  | NOT NULL | —             |
| 14  | `created_at`      | timestamptz  | NOT NULL | `now()`       |
| 15  | `sent_at`         | timestamptz  | NULL     | —             |
| 16  | `tmf_intent_type` | varchar(100) | NULL     | —             |

**PK:** `intents_pkey (intent_id)`

**FK salientes:**

- `intents_user_id_fkey` → `users(user_id)`

**FK entrantes:**

- `policy_registry_intent_id_fkey` → `intents(intent_id)`
- `policies.intent_id` (índice sin FK física)

**CHECK:**
| Constraint | Definición |
|---|---|
| `intents_priority_level_check` | `priority_level BETWEEN 1 AND 5` |
| `intents_scope_level_check` | `scope_level IN ('ELEMENT','SUBNETWORK','NETWORK')` |
| `intents_status_check` | `status IN ('DRAFT','PENDING_VALIDATION','SENT','ACTIVE','CANCELLED','FAILED','ROLLED_BACK')` |

**Índices:** solo PK.

---

### 2. `policies`

Estado de una política derivada de una intención. Actualizable.

| #   | Columna                 | Tipo        | Nullable | Default       |
| --- | ----------------------- | ----------- | -------- | ------------- |
| 1   | `policy_id`             | uuid        | NOT NULL | —             |
| 2   | `intent_id`             | uuid        | NOT NULL | —             |
| 3   | `version`               | integer     | NOT NULL | `0`           |
| 4   | `policy_description`    | text        | NULL     | —             |
| 5   | `policy_json`           | jsonb       | NOT NULL | `'{}'::jsonb` |
| 6   | `parameters_to_monitor` | jsonb       | NOT NULL | `'{}'::jsonb` |
| 7   | `status`                | varchar(30) | NOT NULL | `'PROPOSED'`  |
| 8   | `generated_by`          | varchar(50) | NOT NULL | `'AGENT_AI3'` |
| 9   | `generated_at`          | timestamptz | NOT NULL | `now()`       |
| 10  | `sent_at`               | timestamptz | NULL     | —             |
| 11  | `try`                   | integer     | NOT NULL | `1`           |

**PK:** `policies_pkey (policy_id)`

**FK salientes:** ninguna (`intent_id` sin constraint).

**FK entrantes:**

- `policy_registry_policy_id_fkey` → `policies(policy_id)`
- `policy_validations_policy_id_fkey` → `policies(policy_id)`
- `policy_validations_conflicting_policy_id_fkey` → `policies(policy_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `policies_generated_by_check` | `generated_by = 'AGENT_AI3'` |
| `policies_status_check` | `status IN ('PROPOSED','VALIDATED','INVALID','CANCELLED','SENT','FAILED')` |
| `policies_try_range` | `try BETWEEN 1 AND 3` |
| `policies_version_check` | `version >= 1` |
| `policies_version_range` | `version BETWEEN 0 AND 3` |

## **Índices:** `idx_policies_intent_id (intent_id)`, `idx_policies_status (status)`

### 3. `logical_tasks`

Estado de una tarea lógica (vendor-agnostic). Actualizable.

| #   | Columna            | Tipo         | Nullable | Default       |
| --- | ------------------ | ------------ | -------- | ------------- |
| 1   | `task_id`          | uuid         | NOT NULL | —             |
| 2   | `policy_id`        | uuid         | NOT NULL | —             |
| 3   | `intent_id`        | uuid         | NOT NULL | —             |
| 4   | `task_order`       | integer      | NULL     | —             |
| 5   | `task_description` | text         | NULL     | —             |
| 6   | `task_json`        | jsonb        | NULL     | —             |
| 7   | `status`           | varchar(20)  | NOT NULL | `'PROPOSED'`  |
| 8   | `generated_by`     | varchar(100) | NOT NULL | `'AGENT_AI3'` |
| 9   | `generated_at`     | timestamptz  | NOT NULL | `now()`       |
| 10  | `sent_at`          | timestamptz  | NULL     | —             |
| 11  | `try`              | integer      | NOT NULL | `1`           |
| 12  | `version`          | integer      | NOT NULL | `0`           |

**PK:** `logical_tasks_pkey (task_id)`

**FK salientes:** ninguna (`policy_id`, `intent_id` sin constraint).

**FK entrantes:**

- `logical_task_registry_task_id_fkey` → `logical_tasks(task_id)`
- `logical_task_validations_task_id_fkey` → `logical_tasks(task_id)`
- `atomic_tasks.logical_task_id` (índice sin FK física)

**CHECK:**
| Constraint | Definición |
|---|---|
| `logical_tasks_status_check` | `status IN ('PROPOSED','VALIDATED','SENT','FAILED','CANCELLED','CANCELED')` |
| `logical_tasks_try_range` | `try BETWEEN 1 AND 3` |
| `logical_tasks_version_range` | `version BETWEEN 0 AND 3` |

**Índices:** `idx_logical_tasks_intent_id`, `idx_logical_tasks_policy_id`, `idx_logical_tasks_status`

---

### 4. `atomic_tasks`

Estado de una tarea atómica. Actualizable.

| #   | Columna                 | Tipo         | Nullable | Default       |
| --- | ----------------------- | ------------ | -------- | ------------- |
| 1   | `atomic_task_id`        | uuid         | NOT NULL | —             |
| 2   | `logical_task_id`       | uuid         | NOT NULL | —             |
| 3   | `policy_id`             | uuid         | NOT NULL | —             |
| 4   | `intent_id`             | uuid         | NOT NULL | —             |
| 5   | `status`                | varchar(20)  | NOT NULL | `'PENDING'`   |
| 6   | `try`                   | integer      | NOT NULL | `1`           |
| 7   | `generated_by`          | varchar(100) | NOT NULL | `'AGENT_AI5'` |
| 8   | `generated_at`          | timestamptz  | NOT NULL | `now()`       |
| 9   | `last_updated`          | timestamptz  | NOT NULL | `now()`       |
| 10  | `task_json`             | jsonb        | NOT NULL | `'{}'::jsonb` |
| 11  | `required_capabilities` | jsonb        | NOT NULL | `'{}'::jsonb` |
| 12  | `task_description`      | text         | NULL     | —             |
| 13  | `version`               | integer      | NOT NULL | `0`           |

**PK:** `atomic_tasks_pkey (atomic_task_id)`

**FK salientes:** ninguna.

**FK entrantes:**

- `atomic_task_registry_atomic_task_id_fkey` → `atomic_tasks(atomic_task_id) ON DELETE CASCADE`

**CHECK:**
| Constraint | Definición |
|---|---|
| `atomic_tasks_attempt_count_check` | `try >= 1` _(remanente del rename, redundante)_ |
| `atomic_tasks_try_range` | `try BETWEEN 1 AND 3` |
| `atomic_tasks_version_range` | `version BETWEEN 0 AND 3` |
| `atomic_tasks_status_check` | `status IN ('PENDING','SENT','VALIDATED','FAILED','RETRYING','COMPLETED','CANCELLED')` |

**Índices:** `idx_atomic_tasks_intent_id`, `idx_atomic_tasks_logical_task_id`, `idx_atomic_tasks_policy_id`

---

## Bloque B — Registros append-only

> Solo INSERT, nunca UPDATE ni DELETE. Nunca.

### 5. `policy_registry`

Historial de transiciones de una política.

| #   | Columna           | Tipo        | Nullable | Default |
| --- | ----------------- | ----------- | -------- | ------- |
| 1   | `registry_id`     | uuid        | NOT NULL | —       |
| 2   | `policy_id`       | uuid        | NOT NULL | —       |
| 3   | `intent_id`       | uuid        | NOT NULL | —       |
| 4   | `event_type`      | varchar(30) | NOT NULL | —       |
| 5   | `policy_snapshot` | jsonb       | NOT NULL | —       |
| 6   | `recorded_at`     | timestamptz | NOT NULL | `now()` |

**PK:** `policy_registry_pkey (registry_id)`

**FK salientes:**

- `policy_registry_policy_id_fkey` → `policies(policy_id)`
- `policy_registry_intent_id_fkey` → `intents(intent_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `policy_registry_event_type_check` | `event_type IN ('PROPOSED','VALIDATED','INVALID','SENT','CANCELLED','FAILED')` |

**Índices:** `idx_policy_registry_policy_id`

---

### 6. `logical_task_registry`

Historial de transiciones de una tarea lógica.

| #   | Columna         | Tipo        | Nullable | Default |
| --- | --------------- | ----------- | -------- | ------- |
| 1   | `registry_id`   | uuid        | NOT NULL | —       |
| 2   | `task_id`       | uuid        | NOT NULL | —       |
| 3   | `event_type`    | varchar(20) | NOT NULL | —       |
| 4   | `task_snapshot` | jsonb       | NOT NULL | —       |
| 5   | `recorded_at`   | timestamptz | NOT NULL | `now()` |

**PK:** `logical_task_registry_pkey (registry_id)`

**FK salientes:**

- `logical_task_registry_task_id_fkey` → `logical_tasks(task_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `logical_task_registry_event_type_check` | `event_type IN ('PROPOSED','VALIDATED','SENT','FAILED','CANCELLED')` |

**Índices:** `idx_logical_task_registry_task_id`

---

### 7. `atomic_task_registry`

Historial de transiciones de una tarea atómica.

| #   | Columna          | Tipo        | Nullable | Default       |
| --- | ---------------- | ----------- | -------- | ------------- |
| 1   | `registry_id`    | uuid        | NOT NULL | —             |
| 2   | `atomic_task_id` | uuid        | NOT NULL | —             |
| 3   | `event_type`     | varchar(30) | NOT NULL | —             |
| 4   | `task_snapshot`  | jsonb       | NOT NULL | `'{}'::jsonb` |
| 5   | `recorded_at`    | timestamptz | NOT NULL | `now()`       |

**PK:** `atomic_task_registry_pkey (registry_id)`

**FK salientes:**

- `atomic_task_registry_atomic_task_id_fkey` → `atomic_tasks(atomic_task_id) **ON DELETE CASCADE**`

**CHECK:**
| Constraint | Definición |
|---|---|
| `atomic_task_registry_event_type_check` | `event_type IN ('PROPOSED','SENT','VALIDATED','FAILED','RETRYING','COMPLETED','CANCELLED')` |

**Índices:** `idx_atomic_task_registry_atomic_task_id`, `idx_atomic_task_registry_event_type`, `idx_atomic_task_registry_recorded_at DESC`

---

## Bloque C — Validaciones de 5 capas

### 8. `policy_validations`

Resultado de cada capa de validación de una política.

| #   | Columna                 | Tipo        | Nullable | Default |
| --- | ----------------------- | ----------- | -------- | ------- |
| 1   | `validation_id`         | uuid        | NOT NULL | —       |
| 2   | `policy_id`             | uuid        | NOT NULL | —       |
| 3   | `validation_step`       | varchar(30) | NOT NULL | —       |
| 4   | `result`                | varchar(20) | NOT NULL | —       |
| 5   | `error_detail`          | text        | NULL     | —       |
| 6   | `conflicting_policy_id` | uuid        | NULL     | —       |
| 7   | `user_resolution`       | varchar(20) | NULL     | —       |
| 8   | `validated_at`          | timestamptz | NOT NULL | `now()` |

**PK:** `policy_validations_pkey (validation_id)`

**FK salientes:**

- `policy_validations_policy_id_fkey` → `policies(policy_id)`
- `policy_validations_conflicting_policy_id_fkey` → `policies(policy_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `policy_validations_result_check` | `result IN ('PASS','FAIL','PENDING_USER')` |
| `policy_validations_user_resolution_check` | `user_resolution IS NULL OR user_resolution IN ('CONFIRMED','CANCELLED','PENDING')` |
| `policy_validations_validation_step_check` | `validation_step IN ('SEMANTIC','CONSISTENCY','OVERLAP','RESOURCE_CAPACITY','SECURITY_COMPLIANCE','SCOPE')` |

**Índices:** solo PK.

---

### 9. `logical_task_validations`

Resultado de cada capa de validación de una tarea lógica.

| #   | Columna           | Tipo         | Nullable     | Default |
| --- | ----------------- | ------------ | ------------ | ------- |
| 1   | `validation_id`   | uuid         | NOT NULL     | —       |
| 2   | `task_id`         | uuid         | NOT NULL     | —       |
| 3   | `validation_step` | varchar(50)  | NOT NULL     | —       |
| 4   | `result`          | varchar(30)  | NOT NULL     | —       |
| 5   | `error_detail`    | text         | NULL         | —       |
| 6   | `validated_at`    | timestamptz  | NOT NULL     | `now()` |
| 7   | `validated_by`    | varchar(100) | **NOT NULL** | —       |

**PK:** `logical_task_validations_pkey (validation_id)`

**FK salientes:**

- `logical_task_validations_task_id_fkey` → `logical_tasks(task_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `logical_task_validations_result_check` | `result IN ('PASS','FAIL','NOT_EVALUATED')` |
| `logical_task_validations_step_check` | `validation_step IN ('SEMANTIC','CONSISTENCY','OVERLAP','RESOURCE_CAPACITY','SECURITY_COMPLIANCE')` |

**Índices:** solo PK.

---

## Bloque D — SSoT y catálogos

### 10. `network_devices`

Inventario de dispositivos del SSoT.

| #   | Columna          | Tipo         | Nullable | Default       |
| --- | ---------------- | ------------ | -------- | ------------- |
| 1   | `device_id`      | uuid         | NOT NULL | —             |
| 2   | `hostname`       | varchar(255) | NOT NULL | —             |
| 3   | `status`         | varchar(50)  | NOT NULL | —             |
| 4   | `current_config` | jsonb        | NOT NULL | `'{}'::jsonb` |

**PK:** `network_devices_pkey (device_id)`

**UNIQUE:**

- `network_devices_hostname_key (hostname)`

**FK:** ninguna (es raíz del SSoT).

**CHECK:** ninguno (ni siquiera sobre `status`).

**Índices:** solo PK + UNIQUE.

**Observación:** solo 4 columnas. No hay `vendor`, `platform`, `os_version`, `capabilities`.

---

### 11. `compliance_rules`

Reglas de cumplimiento del SSoT.

| #   | Columna           | Tipo         | Nullable | Default       |
| --- | ----------------- | ------------ | -------- | ------------- |
| 1   | `rule_id`         | uuid         | NOT NULL | —             |
| 2   | `rule_type`       | varchar(100) | NOT NULL | —             |
| 3   | `description`     | text         | NOT NULL | —             |
| 4   | `rule_expression` | jsonb        | NOT NULL | `'{}'::jsonb` |
| 5   | `severity`        | varchar(50)  | NOT NULL | —             |
| 6   | `is_active`       | boolean      | NOT NULL | `true`        |

**PK:** `compliance_rules_pkey (rule_id)`

**FK:** ninguna.

**CHECK:** ninguno.

**Índices:** solo PK.

---

### 12. `task_documents`

Documentación RAG para la crew de tareas lógicas.

| #   | Columna       | Tipo        | Nullable | Default                                     |
| --- | ------------- | ----------- | -------- | ------------------------------------------- |
| 1   | `document_id` | bigint      | NOT NULL | `nextval('task_documents_document_id_seq')` |
| 2   | `title`       | text        | NOT NULL | —                                           |
| 3   | `content`     | text        | NOT NULL | —                                           |
| 4   | `category`    | text        | NULL     | —                                           |
| 5   | `is_active`   | boolean     | NOT NULL | `true`                                      |
| 6   | `created_at`  | timestamptz | NOT NULL | `now()`                                     |

**PK:** `task_documents_pkey (document_id)`

**FK:** ninguna.

**CHECK:** ninguno.

**Índices:** `idx_task_documents_active (is_active)`

---

### 13. `task_examples`

Ejemplos RAG para la crew de tareas lógicas.

| #   | Columna                     | Tipo        | Nullable | Default                                   |
| --- | --------------------------- | ----------- | -------- | ----------------------------------------- |
| 1   | `example_id`                | bigint      | NOT NULL | `nextval('task_examples_example_id_seq')` |
| 2   | `intent_type`               | text        | NULL     | —                                         |
| 3   | `description`               | text        | NOT NULL | —                                         |
| 4   | `policy_json_example`       | jsonb       | NOT NULL | —                                         |
| 5   | `logical_task_json_example` | jsonb       | NOT NULL | —                                         |
| 6   | `is_active`                 | boolean     | NOT NULL | `true`                                    |
| 7   | `created_at`                | timestamptz | NOT NULL | `now()`                                   |

**PK:** `task_examples_pkey (example_id)`

**FK:** ninguna.

**CHECK:** ninguno.

**Índices:** `idx_task_examples_active_type (is_active, intent_type)`

---

## Bloque E — Autenticación / Autorización

### 14. `users`

| #   | Columna             | Tipo         | Nullable | Default |
| --- | ------------------- | ------------ | -------- | ------- |
| 1   | `user_id`           | uuid         | NOT NULL | —       |
| 2   | `name`              | varchar(255) | NOT NULL | —       |
| 3   | `email`             | varchar(255) | NOT NULL | —       |
| 4   | `password_hash`     | varchar(255) | NOT NULL | —       |
| 5   | `role_id`           | uuid         | NOT NULL | —       |
| 6   | `organization_unit` | varchar(255) | NULL     | —       |
| 7   | `is_active`         | boolean      | NOT NULL | `true`  |
| 8   | `created_at`        | timestamptz  | NOT NULL | `now()` |
| 9   | `last_login`        | timestamptz  | NULL     | —       |

**PK:** `users_pkey (user_id)`

**UNIQUE:** `users_email_key (email)`

**FK salientes:**

- `users_role_id_fkey` → `roles(role_id)`

**FK entrantes:**

- `intents_user_id_fkey` → `users(user_id)`

**Índices:** PK + UNIQUE.

---

### 15. `roles`

| #   | Columna          | Tipo         | Nullable | Default |
| --- | ---------------- | ------------ | -------- | ------- |
| 1   | `role_id`        | uuid         | NOT NULL | —       |
| 2   | `role_name`      | varchar(100) | NOT NULL | —       |
| 3   | `priority_level` | integer      | NOT NULL | —       |
| 4   | `max_scope`      | varchar(20)  | NOT NULL | —       |
| 5   | `description`    | text         | NULL     | —       |

**PK:** `roles_pkey (role_id)`

**UNIQUE:** `roles_role_name_key (role_name)`

**FK entrantes:**

- `users_role_id_fkey` → `roles(role_id)`

**CHECK:**
| Constraint | Definición |
|---|---|
| `roles_max_scope_check` | `max_scope IN ('ELEMENT','SUBNETWORK','NETWORK')` |
| `roles_priority_level_check` | `priority_level BETWEEN 1 AND 5` |

**Índices:** PK + UNIQUE.

---

## Diagrama de FKs físicas
