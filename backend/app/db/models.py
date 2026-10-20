"""Modèles SQLAlchemy (PostgreSQL en production, SQLite accepté en local et en test)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


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
