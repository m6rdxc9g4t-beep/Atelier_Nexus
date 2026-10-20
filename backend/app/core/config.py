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
    # Accès à Claude : clé API, ou abonnement Claude par Claude Code (`claude -p`, sans clé).
    # auto = la clé si elle est définie, sinon Claude Code s'il est installé.
    claude_mode: Literal["auto", "api", "cli"] = "auto"
    claude_cli_model: str = "sonnet"
    #: Chemin de `claude` si introuvable automatiquement (jamais modifiable depuis l'interface)
    claude_cli_path: str | None = None
    claude_cli_timeout: float = Field(default=300.0, gt=0, le=1800)
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
    #: ATELIER_IMPORT_TOKEN d'Atelier Projets, si l'import depuis Atelier Tab est protégé
    projets_import_token: SecretStr | None = None
    apps_timeout: float = 20.0

    # Application de bureau : interface compilée (frontend/out) servie par le backend
    frontend_dist: str | None = None

    # Atelier Ciné (Express, 4000 ; app Mac : 47321). Atelier Savoir (Flask) écoute par défaut
    # sur 5050 comme Trésorerie : on le lance avec ATELIER_PORT=5051 (docs/apps/savoir.md).
    cine_base_url: str | None = "http://127.0.0.1:4000/api"
    savoir_base_url: str | None = "http://127.0.0.1:5051/api"
    # Atelier Tab n'a pas d'API : on lit les instantanés que l'app de bureau publie
    tab_exports_dir: str | None = "~/Atelier_Tab/exports"
    tab_max_snapshot_mb: int = Field(default=50, ge=1, le=2000)
    # Écriture : serveur MCP de Tab (app Mac : /Applications/Atelier_Tab.app/Contents/Resources/
    # atelier-mcp ; dépôt : « node <atelier-tab>/dist-desktop/atelier-mcp.mjs »). Vide = lecture seule.
    tab_mcp_command: str | None = None
    #: Dossier de données de Tab passé au serveur MCP (ATELIER_TAB_DATA) ; vide = ~/Atelier_Tab
    tab_data_dir: str | None = None
    tab_mcp_timeout: float = Field(default=30.0, gt=0, le=600)

    # GitHub (agent Développeur) : dépôt par défaut + liste blanche, séparés par des virgules
    github_token: SecretStr | None = None
    github_repo: str | None = Field(default=None, description="owner/repo")
    github_allowed_repos: str = ""
    github_api_url: str = "https://api.github.com"

    @field_validator(
        "llm_fallback_provider",
        "anthropic_api_key",
        "claude_cli_path",
        "data_via_base_url",
        "data_via_api_key",
        "projets_base_url",
        "projets_import_token",
        "tresorerie_base_url",
        "cine_base_url",
        "savoir_base_url",
        "tab_exports_dir",
        "tab_mcp_command",
        "frontend_dist",
        "tab_data_dir",
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
