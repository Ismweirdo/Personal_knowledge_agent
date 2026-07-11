from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Personal Knowledge Agent"
    app_env: str = "development"
    database_url: str | None = None
    redis_host: str = "localhost"
    redis_password: str | None = None
    jwt_secret: str = "development-only-change-me"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    file_storage_path: str = "uploads"
    web_crawl_user_agent: str = "PersonalKnowledgeAgent/0.1"
    sync_interval_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

