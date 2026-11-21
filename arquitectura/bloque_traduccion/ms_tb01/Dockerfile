# Dockerfile — MS-TB01 (CrewAI headless, consume/publica eventos por Kafka)
# Contexto de build: MS-TB01/  →  las rutas COPY son relativas a esta carpeta.

# ---------- Etapa 1: resolver dependencias con uv ----------
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build

# Copiar solo los archivos de dependencias primero: si el código cambia pero
# pyproject.toml/uv.lock no, Docker reutiliza esta capa y el build es mucho más rápido.
COPY pyproject.toml uv.lock ./

# Ahora sí, el código fuente
COPY src ./src


# Instalar las dependencias (sin el paquete del proyecto)
RUN uv sync --frozen --no-dev --no-install-project

# Instalar el paquete del proyecto en modo NO editable
RUN uv pip install --no-deps --no-cache .

# ---------- Etapa 2: imagen final, sin herramientas de build ----------
FROM python:3.11-slim

RUN useradd -m -u 1000 crewuser
WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src ./src
COPY --from=builder /build/pyproject.toml ./pyproject.toml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Crear carpeta output con permisos
RUN mkdir -p /app/output && chown -R crewuser:crewuser /app/output

# NUNCA copiar .env aquí — se inyecta por Kubernetes.
USER crewuser

EXPOSE 4001

CMD ["python", "-m", "uvicorn", "ms_tb01.main:app", "--host", "0.0.0.0", "--port", "4001"]