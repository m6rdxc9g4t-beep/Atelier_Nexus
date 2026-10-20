"""Définition d'un agent créé depuis l'interface (stockée en base)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.llm.types import ProviderName

AGENT_NAME = r"^[a-z][a-z0-9_]{2,40}$"

#: Icônes proposées dans l'éditeur (noms Lucide connus du frontend)
ICONS = (
    "bot", "sparkles", "network", "chart-column", "list-checks", "code", "landmark", "receipt",
    "megaphone", "pen-line", "briefcase", "scale", "users", "lightbulb", "graduation-cap",
    "clapperboard", "headset", "shield-check", "calendar-check", "table-2",
)  # fmt: skip

Icon = Literal[
    "bot", "sparkles", "network", "chart-column", "list-checks", "code", "landmark", "receipt",
    "megaphone", "pen-line", "briefcase", "scale", "users", "lightbulb", "graduation-cap",
    "clapperboard", "headset", "shield-check", "calendar-check", "table-2",
]  # fmt: skip


class CustomAgentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=5, max_length=300)
    system_prompt: str = Field(
        min_length=20, max_length=20_000, description="Consignes de l'agent."
    )
    icon: Icon = "bot"
    category: str = Field(default="Mes agents", min_length=2, max_length=40)
    toolsets: list[str] = Field(default_factory=lambda: ["core"], max_length=12)
    privacy: Literal["standard", "local_only"] = "standard"
    default_provider: ProviderName | None = None
    starters: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("toolsets")
    @classmethod
    def _toolsets(cls, value: list[str]) -> list[str]:
        from app.tools.toolsets import toolset_ids

        known = set(toolset_ids())
        unknown = [t for t in value if t not in known]
        if unknown:
            raise ValueError(f"Boîte(s) à outils inconnue(s) : {', '.join(unknown)}")
        ordered = ["core", *[t for t in dict.fromkeys(value) if t != "core"]]
        return ordered  # « Essentiels » toujours présents, en tête

    @field_validator("starters")
    @classmethod
    def _starters(cls, value: list[str]) -> list[str]:
        cleaned = [s.strip() for s in value if s.strip()]
        if any(len(s) > 200 for s in cleaned):
            raise ValueError("Chaque exemple fait au plus 200 caractères.")
        return cleaned


class CustomAgentCreate(CustomAgentFields):
    name: str = Field(pattern=AGENT_NAME, description="Identifiant : minuscules, chiffres, _")


class CustomAgentUpdate(CustomAgentFields):
    pass


class CustomAgentDefinition(CustomAgentCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
