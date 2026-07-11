import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings


def test_default_settings_are_suitable_for_local_development() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_default_jwt_secret_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET must be replaced"):
        Settings(app_env="production", _env_file=None)


def test_production_requires_model_configuration() -> None:
    with pytest.raises(ValidationError, match="LLM_API_KEY is required"):
        Settings(
            app_env="production",
            jwt_secret="a-production-secret-with-sufficient-entropy",
            _env_file=None,
        )
