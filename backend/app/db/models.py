"""Modèles SQLAlchemy (PostgreSQL en production, SQLite accepté en local et en test)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class CustomAgentRow(Base):
    __tablename__ = "custom_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(41), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(300))
    system_prompt: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(40), default="bot")
    category: Mapped[str] = mapped_column(String(40), default="Mes agents")
    toolsets: Mapped[list[str]] = mapped_column(JSON, default=list)
    privacy: Mapped[str] = mapped_column(String(20), default="standard")
    default_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    starters: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ConversationRow(Base):
    """Conversation avec un agent : historique au format neutre (liste de `Message`)."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent: Mapped[str] = mapped_column(String(41), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    history: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: Méta par tour : index du message assistant final → moteur, modèle, jetons, arrêt
    turn_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Appels en attente de validation à la fin du dernier tour
    pending: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, index=True
    )

    artifacts: Mapped[list[ArtifactRow]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ArtifactRow.created_at",
    )


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(41))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # « metadata » est réservé par SQLAlchemy : colonne nommée « meta »
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Longueur de l'historique à la fin du tour qui a produit l'artefact
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[ConversationRow] = relationship(back_populates="artifacts")
