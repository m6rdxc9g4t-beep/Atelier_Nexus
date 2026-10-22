"""Modèles SQLAlchemy (PostgreSQL en production, SQLite accepté en local et en test)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
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
    #: Texte normalisé pour la recherche (app/db/search.py)
    search_text: Mapped[str] = mapped_column(Text, default="")
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


class AttachmentRow(Base):
    """Fichier joint à un message : original (image réduite), texte extrait, méta.

    `conversation_id` est renseigné quand le tour qui le cite est enregistré ; une pièce jointe
    sans conversation après 24 h (envoi abandonné) est supprimée au démarrage."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkflowRow(Base):
    """Workflow rejouable. v1 : étapes (outil + entrée) figées depuis un tour d'agent réussi ;
    v2 : graphe d'étapes outils et actions d'applications (`agent` nul = workflow de suite)."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    agent: Mapped[str | None] = mapped_column(String(41), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    params: Mapped[list[Any]] = mapped_column(JSON, default=list)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, index=True
    )


class WorkflowRunRow(Base):
    """Exécution d'un workflow v2 : avance étape par étape, s'arrête sur chaque écriture.

    `state` (interne, jamais renvoyé par l'API) : définition figée au lancement, ordre,
    décisions de validation, contexte partagé des outils."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    artifacts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    pending: Mapped[list[Any]] = mapped_column(JSON, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
