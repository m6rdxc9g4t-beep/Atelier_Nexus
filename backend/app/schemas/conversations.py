"""Conversations enregistrées : historique, artefacts, méta des tours."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm.types import Message, ProviderName, Usage


class TurnMeta(BaseModel):
    provider: ProviderName
    model: str
    usage: Usage
    stop_reason: str
    iterations: int


class StoredArtifact(BaseModel):
    id: str
    agent: str
    kind: str
    title: str
    content: str
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    position: int
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    agent: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    artifact_count: int


class ConversationDetail(ConversationSummary):
    history: list[Message]
    artifacts: list[StoredArtifact]
    #: Index (en chaîne) du message assistant final du tour → méta
    turn_meta: dict[str, TurnMeta]
    pending_approvals: list[dict[str, Any]]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1, max_length=41)
    title: str = Field(default="", max_length=120)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)


def title_from(messages: list[Message]) -> str:
    """Titre par défaut : début de la première question de l'utilisateur."""
    for message in messages:
        if message.role == "user" and message.text.strip():
            text = " ".join(message.text.split())
            return text if len(text) <= 80 else text[:77].rstrip() + "…"
    return "Nouvelle conversation"
