"""Configuration centralisée, chargée depuis l'environnement ou `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Persistance
    database_url: str = "postgresql+asyncpg://atelier:change-me@localhost:5432/atelier_hub"
    redis_url: str = "redis://localhost:6379/0"

    # Routeur LLM
    llm_default_provider: Literal["anthropic", "ollama"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Apps Atelier
    data_via_base_url: str | None = None
    data_via_api_key: SecretStr | None = None

    # GitHub
    github_token: SecretStr | None = None
    github_repo: str | None = Field(default=None, description="owner/repo")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
