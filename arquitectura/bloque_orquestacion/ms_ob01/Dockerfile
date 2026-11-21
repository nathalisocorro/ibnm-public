FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.11-slim
RUN useradd -m -u 1000 crewuser
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src ./src
COPY --from=builder /build/pyproject.toml ./pyproject.toml
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER crewuser
CMD ["python", "-m", "ms_ob01.main"]
