"""Configuration centralisée, chargée depuis l'environnement ou `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Persistance
    database_url: str = "postgresql+asyncpg://atelier:change-me@localhost:5432/atelier_nexus"
    redis_url: str = "redis://localhost:6379/0"

    # Routeur LLM
    llm_default_provider: Literal["anthropic", "ollama"] = "anthropic"
    # Provider de secours en cas de panne transitoire du provider demandé
    llm_fallback_provider: Literal["anthropic", "ollama"] | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_timeout: float = 120.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: float = 300.0

    # Apps Atelier
    data_via_base_url: str | None = None
    data_via_api_key: SecretStr | None = None

    # GitHub
    github_token: SecretStr | None = None
    github_repo: str | None = Field(default=None, description="owner/repo")

    @field_validator(
        "llm_fallback_provider",
        "anthropic_api_key",
        "data_via_base_url",
        "data_via_api_key",
        "github_token",
        "github_repo",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        # `CLE=` dans un .env doit signifier « non défini », pas chaîne vide
        return None if value == "" else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
