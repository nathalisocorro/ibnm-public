from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    """Configuración de la aplicación ms_ob02."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_TEMPERATURE: float = 0.2
    DEEPSEEK_MAX_TOKENS: int = 2048
    DEEPSEEK_TIMEOUT_SECONDS: int = 120

    # PostgreSQL
    POSTGRES_USER: str = "ibn_user"
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = "localhost"      
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ibn_db"

    # Kafka - Conexión
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT"

    # Kafka - Topics
    KAFKA_TOPIC_ATOMIC_TASK_PROPOSED: str = "ibnn.atomic_task_proposed"
    KAFKA_TOPIC_COMMAND_SENT: str = "ibnn.command_sent"
    KAFKA_TOPIC_ATOMIC_TASK_FAULT: str = "ibnn.atomic_task_fault"
    KAFKA_TOPIC_COMMAND_EXECUTION_COMPLETED: str = "ibnn.command_execution_completed"
    KAFKA_TOPIC_COMMAND_EXECUTION_FAILED: str = "ibnn.command_execution_failed"

    # Kafka - Consumer
    KAFKA_GROUP_ID: str = "ms-ob02-consumer-group"
    KAFKA_EXECUTOR_GROUP_ID: str = "ms-ob02-executor-group"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_CLIENT_ID: str = "ms-ob02"
    KAFKA_CONSUMER_TIMEOUT_MS: int = 1000
    KAFKA_CONSUMER_MAX_POLL_RECORDS: int = 500

    # Kafka - Producer
    KAFKA_PRODUCER_ACKS: str = "all"
    KAFKA_PRODUCER_RETRIES: int = 3

    #OLLAMA
    OLLAMA_BASE_URL: str = "http://localhost:11434"   
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # Ejecución
    MAX_CONCURRENT_EXECUTIONS: int = 3

    DEVICE_CREDENTIALS: Optional[str] = None

    # Ejecución - Credenciales (resueltas desde variables de entorno)
    NETMIKO_USERNAME: str = ""
    NETMIKO_PASSWORD: str = ""
    NETMIKO_PORT: int = 22
    NETMIKO_TIMEOUT: int = 60
    NETMIKO_CONN_TIMEOUT: int = 30
    NETMIKO_SECRET: str = ""
    NETMIKO_DEVICE_TYPE: str = "cisco_ios"
    # Overrides por hostname:
    # NETMIKO_DEVICE_CREDENTIALS='{"router-01": {"username": "u", "password": "p", "device_type": "huawei_vrp"}}'
    NETMIKO_DEVICE_CREDENTIALS: dict = {}

    # Ejecución - NETCONF
    NETCONF_USERNAME: str = ""
    NETCONF_PASSWORD: str = ""
    NETCONF_PORT: int = 830
    NETCONF_TIMEOUT: int = 60
    NETCONF_SECRET: str = ""
    NETCONF_DEVICE_TYPE: str = ""
    NETCONF_HOST_KEY_VALIDATION: bool = True
    # Overrides por hostname (JSON)
    NETCONF_DEVICE_CREDENTIALS: dict = {}

    # Ejecución - RESTCONF
    RESTCONF_USERNAME: str = ""
    RESTCONF_PASSWORD: str = ""
    RESTCONF_PORT: int = 443
    RESTCONF_BASE_PATH: str = "/restconf"
    RESTCONF_VERIFY_TLS: bool = True
    RESTCONF_TIMEOUT: int = 30
    # Overrides por hostname (JSON)
    RESTCONF_DEVICE_CREDENTIALS: dict = {}

    # Ejecución - Ansible
    ANSIBLE_TIMEOUT: int = 600
    ANSIBLE_PRIVATE_KEY_FILE: str = ""
    ANSIBLE_INVENTORY_DIR: str = "./inventory"
    # Overrides por hostname (JSON)
    ANSIBLE_DEVICE_CREDENTIALS: dict = {}


# Instancia singleton de settings
settings = Settings()
