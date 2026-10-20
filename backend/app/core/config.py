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
    # Ports Nexus : 3100 (UI) / 8100 (API) — 3000 et 8000 sont pris par Projets et Viz
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    # Persistance
    database_url: str = "postgresql+asyncpg://atelier:change-me@localhost:5432/atelier_nexus"
    redis_url: str = "redis://localhost:6379/0"
    # Applique les migrations au démarrage (agents personnalisés) ; sans base, l'API reste utilisable
    db_auto_migrate: bool = True

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

    # Apps Atelier — Data Via = API d'Atelier Viz (docs/SUITE.md : port 8000)
    data_via_base_url: str | None = "http://127.0.0.1:8000/api"
    data_via_api_key: SecretStr | None = None
    data_via_timeout: float = 30.0

    # Atelier Projets (SUITE.md : API sur 3000) et Atelier Trésorerie (5050)
    projets_base_url: str | None = "http://127.0.0.1:3000/api"
    tresorerie_base_url: str | None = "http://127.0.0.1:5050/api"
    apps_timeout: float = 20.0

    # GitHub (agent Développeur) : dépôt par défaut + liste blanche, séparés par des virgules
    github_token: SecretStr | None = None
    github_repo: str | None = Field(default=None, description="owner/repo")
    github_allowed_repos: str = ""
    github_api_url: str = "https://api.github.com"

    @field_validator(
        "llm_fallback_provider",
        "anthropic_api_key",
        "data_via_base_url",
        "data_via_api_key",
        "projets_base_url",
        "tresorerie_base_url",
        "github_token",
        "github_repo",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        # `CLE=` dans un .env doit signifier « non défini », pas chaîne vide
        return None if value == "" else value

    @property
    def github_repo_list(self) -> list[str]:
        """Dépôts autorisés, le dépôt par défaut en premier, sans doublon."""
        repos = [self.github_repo or ""] + self.github_allowed_repos.split(",")
        seen: list[str] = []
        for repo in (r.strip() for r in repos):
            if repo and repo.lower() not in (s.lower() for s in seen):
                seen.append(repo)
        return seen

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
