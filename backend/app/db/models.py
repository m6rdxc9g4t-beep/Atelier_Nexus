"""Modèles SQLAlchemy (PostgreSQL en production, SQLite accepté en local et en test)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def _now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Horodatage toujours rendu **avec fuseau UTC**, quelle que soit la base.

    PostgreSQL rend des dates avec fuseau ; SQLite (bureau, tests) les rend naïves. Une date naïve
    sortie telle quelle dans l'API est lue par le navigateur comme une heure locale (décalage de
    deux heures à Paris l'été). Écriture : convertie en UTC ; lecture : une date naïve est de l'UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now, onupdate=_now)


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=_now, onupdate=_now, index=True
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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)

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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)


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
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=_now, onupdate=_now, index=True
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
    #: Déclencheur à l'origine de l'exécution (pas de clé étrangère : l'historique survit au
    #: déclencheur supprimé) et événement sans ses `data`
    trigger_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    trigger_event: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    artifacts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    pending: Mapped[list[Any]] = mapped_column(JSON, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now, onupdate=_now)


class WorkflowTriggerRow(Base):
    """Déclencheur d'un workflow v2 : horaire (`schedule`) ou événement d'une application
    (`event`). `config` : champs propres au type ; `state` : état lu par l'interface ;
    `internal` : données du moteur (rafale en attente, fenêtre de débit), jamais renvoyées."""

    __tablename__ = "workflow_triggers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Application observée (déclencheur événement), pour la distribution
    app: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_runs_per_hour: Mapped[int] = mapped_column(Integer, default=12)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    internal: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now, onupdate=_now)


class TriggerCursorRow(Base):
    """Curseur d'événements par application : dernier `seq` lu par Nexus (un seul lecteur)."""

    __tablename__ = "trigger_cursors"

    app: Mapped[str] = mapped_column(String(20), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now, onupdate=_now)


class ChainRunRow(Base):
    """Exécution d'une chaîne d'agents : demande, étape courante, état et livrable figé de chaque
    étape (chaque étape est une conversation ordinaire avec son agent)."""

    __tablename__ = "chain_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chain: Mapped[str] = mapped_column(String(41), index=True)
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running")
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    stages: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=_now, onupdate=_now, index=True
    )
