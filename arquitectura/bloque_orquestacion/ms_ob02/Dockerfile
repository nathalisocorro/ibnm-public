# ============================================================
# Etapa 1: builder — resuelve dependencias con uv
# ============================================================
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build

# Copiar solo los archivos de dependencias primero (mejor caché de capas)
COPY pyproject.toml uv.lock ./

# Instalar solo las dependencias (sin el proyecto local todavía)
RUN uv sync --frozen --no-dev --no-install-project

# Copiar el código fuente
COPY src ./src

# Instalar el proyecto local (ahora sí existe src/ms_ob02)
RUN uv sync --frozen --no-dev


# ============================================================
# Etapa 2: imagen final — sin herramientas de build
# ============================================================
FROM python:3.11-slim

# Usuario no-root
RUN useradd -m -u 1000 crewuser

WORKDIR /app

# Copiar el venv ya resuelto y el código desde el builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src ./src
COPY --from=builder /build/pyproject.toml ./pyproject.toml

# Variables de entorno
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Cambiar a usuario no-root
USER crewuser

# Comando de arranque
CMD ["python", "-m", "ms_ob02.main"]
