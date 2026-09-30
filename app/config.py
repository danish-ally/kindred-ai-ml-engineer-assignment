from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://kindred:kindred@localhost:5432/kindred"
    embed_dim: int = 16
    payment_timeout_trigger_cents: int = 999999
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_attempts: int = 3
    llm_retry_base_seconds: float = 0.5


settings = Settings()
