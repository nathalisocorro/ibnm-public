
"""Configuración de MS-OB01."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    # PostgreSQL
    POSTGRES_USER: str = "ibnm"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ibnm"
    DATABASE_URL: str | None = None

    # SSoT - MS-V03
    SSOT_BASE_URL: str = "http://127.0.0.1:6303"
    SSOT_TIMEOUT_SECONDS: float = 30.0

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    DEEPSEEK_TEMPERATURE: float = 0.0

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_LOGICAL_TASK_PROPOSED: str = "ibnn.logical_task_proposed"
    KAFKA_TOPIC_ATOMIC_TASK_PROPOSED: str = "ibnn.atomic_task_proposed"
    KAFKA_TOPIC_LOGICAL_TASK_FAULT: str = "ibnn.logical_task_fault"
    KAFKA_TOPIC_ATOMIC_TASK_FAULT: str = "ibnn.atomic_task_fault"
    KAFKA_GROUP_ID: str = "ms-ob01-consumer-group"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"

    # Ciclo de generación y regeneración
    MAX_GENERATION_VERSIONS: int = 3
    MAX_REGENERATION_TRIES: int = 3

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
