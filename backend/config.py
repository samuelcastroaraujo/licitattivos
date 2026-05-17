"""
Configuração centralizada do backend.
Lê variáveis do .env via pydantic-settings.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = Field(..., validation_alias="SUPABASE_URL")
    supabase_key: str = Field(..., validation_alias="SUPABASE_KEY")
    supabase_service_role_key: str = Field("", validation_alias="SUPABASE_SERVICE_ROLE_KEY")

    # LLMs
    anthropic_api_key: str = Field("", validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", validation_alias="OPENAI_API_KEY")

    # LangSmith
    langchain_tracing_v2: bool = Field(False, validation_alias="LANGCHAIN_TRACING_V2")
    langchain_api_key: str = Field("", validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field("licitattivos", validation_alias="LANGCHAIN_PROJECT")

    # App
    environment: str = Field("development", validation_alias="ENVIRONMENT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    sentry_dsn: str = Field("", validation_alias="SENTRY_DSN")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
