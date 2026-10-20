"""Pièces jointes : ce que l'API renvoie après l'import d'un fichier."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.core.llm.types import AttachmentKind
from app.schemas.conversations import _utc


class AttachmentInfo(BaseModel):
    id: str
    name: str
    media_type: str
    kind: AttachmentKind
    #: Octets enregistrés (image : après réduction)
    size: int
    #: pages, sheets, rows, chars, width, height, truncated (motif d'une coupure)…
    meta: dict[str, Any]
    created_at: datetime

    _tz = field_validator("created_at")(_utc)
