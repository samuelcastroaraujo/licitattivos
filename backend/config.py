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
    openrouter_api_key: str = Field("", validation_alias="OPENROUTER_API_KEY")
    openai_api_key: str = Field("", validation_alias="OPENAI_API_KEY")

    # LangSmith
    langchain_tracing_v2: bool = Field(False, validation_alias="LANGCHAIN_TRACING_V2")
    langchain_api_key: str = Field("", validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field("licitattivos", validation_alias="LANGCHAIN_PROJECT")

    # Apify
    apify_token: str = Field("", validation_alias="APIFY_TOKEN")
    apify_actor_id: str = Field("", validation_alias="APIFY_ACTOR_ID")
    apify_task_id: str = Field("", validation_alias="APIFY_TASK_ID")
    apify_webhook_secret: str = Field("", validation_alias="APIFY_WEBHOOK_SECRET")

    # Modelo e rotina automática
    llm_provider: str = Field("openrouter", validation_alias="LLM_PROVIDER")  # "gemini" | "openrouter"
    llm_model: str = Field("deepseek/deepseek-v4.1-flash", validation_alias="LLM_MODEL")
    gemini_api_key: str = Field("", validation_alias="GEMINI_API_KEY")
    # O primeiro da lista é o principal; os outros entram quando o Google responde que está sobrecarregado.
    gemini_model: str = Field("gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash", validation_alias="GEMINI_MODEL")
    ingest_ufs: str = Field("", validation_alias="INGEST_UFS")
    ingest_hora: int = Field(6, validation_alias="INGEST_HORA")
    frontend_url: str = Field("", validation_alias="FRONTEND_URL")

    # App
    api_token: str = Field("", validation_alias="API_TOKEN")
    environment: str = Field("development", validation_alias="ENVIRONMENT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    sentry_dsn: str = Field("", validation_alias="SENTRY_DSN")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
