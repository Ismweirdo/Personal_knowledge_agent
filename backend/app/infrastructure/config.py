from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Personal Knowledge Agent"
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/knowledge_agent"
    redis_host: str = "localhost"
    redis_password: str | None = None
    jwt_secret: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-chat"
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_dimensions: int = 1536
    file_storage_path: str = "uploads"
    max_upload_bytes: int = 20 * 1024 * 1024
    web_crawl_user_agent: str = "PersonalKnowledgeAgent/0.1"
    sync_interval_minutes: int = 30
    git_import_root: str | None = None

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env.lower() == "production" and self.jwt_secret == "development-only-change-me":
            raise ValueError("JWT_SECRET must be replaced in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
