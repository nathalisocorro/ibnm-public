"""Configuración centralizada de MS-PB02."""

from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    LOG_LEVEL: str = "INFO"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek/deepseek-chat"
    DEEPSEEK_TEMPERATURE: float = 0.0
    SSOT_BASE_URL: str = "http://localhost:6303"
    SSOT_TIMEOUT_SECONDS: float = 30.0

    POSTGRES_USER: str = "ibnm"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ibnm"
    DATABASE_URL: str | None = None

    KAFKA_BOOTSTRAP_SERVERS: str = "172.19.0.1:9092"
    KAFKA_TOPIC_POLICY_PROPOSED: str = "ibnn.policy_proposed"
    KAFKA_TOPIC_LOGICAL_TASK_PROPOSED: str = "ibnn.logical_task_proposed"
    KAFKA_TOPIC_LOGICAL_TASK_FAULT: str = "ibnn.logical_task_fault"
    KAFKA_TOPIC_POLICY_FAULT: str = "ibnn.policy_fault"
    KAFKA_GROUP_ID: str = "ms-pb02-consumer-group"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"

    MAX_GENERATION_VERSIONS: int = 3
    MAX_REGENERATION_TRIES: int = 3

    @field_validator("*", mode="before")
    @classmethod
    def strip_environment_values(cls, value: Any) -> Any:
        """Evita que archivos .env con CRLF inyecten \r en los valores."""
        return value.strip() if isinstance(value, str) else value

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            "postgresql+asyncpg://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
