"""Stockage des pièces jointes (table `attachments`)."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.attachments.processing import ProcessedAttachment
from app.core.llm.attachments import AttachmentContent
from app.db.models import AttachmentRow
from app.db.repository import StorageError, _storage_message
from app.schemas.attachments import AttachmentInfo

ORPHAN_AFTER = timedelta(hours=24)


def _info(row: AttachmentRow) -> AttachmentInfo:
    return AttachmentInfo(
        id=row.id,
        name=row.name,
        media_type=row.media_type,
        kind=row.kind,
        size=row.size,
        meta=dict(row.meta or {}),
        created_at=row.created_at,
    )


class AttachmentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run(self, fn: Any) -> Any:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc

    async def create(self, item: ProcessedAttachment) -> AttachmentInfo:
        async def op(s: AsyncSession) -> AttachmentInfo:
            row = AttachmentRow(
                id=uuid.uuid4().hex,
                name=item.name,
                media_type=item.media_type,
                kind=item.kind,
                size=len(item.data),
                data=item.data,
                text=item.text,
                meta=item.meta,
                created_at=datetime.now(UTC),
            )
            s.add(row)
            await s.commit()
            return _info(row)

        result: AttachmentInfo = await self._run(op)
        return result

    async def get(self, attachment_id: str) -> tuple[AttachmentInfo, bytes] | None:
        async def op(s: AsyncSession) -> tuple[AttachmentInfo, bytes] | None:
            row = await s.get(AttachmentRow, attachment_id)
            return (_info(row), row.data) if row else None

        result: tuple[AttachmentInfo, bytes] | None = await self._run(op)
        return result

    async def contents(self, ids: Iterable[str]) -> dict[str, AttachmentContent]:
        """Contenu prêt pour le modèle des pièces jointes demandées (les absentes sont omises)."""
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}

        async def op(s: AsyncSession) -> dict[str, AttachmentContent]:
            rows = await s.scalars(select(AttachmentRow).where(AttachmentRow.id.in_(wanted)))
            return {
                row.id: AttachmentContent(
                    name=row.name,
                    kind=row.kind,  # type: ignore[arg-type]
                    media_type=row.media_type,
                    text=row.text,
                    image_base64=base64.b64encode(row.data).decode()
                    if row.kind == "image"
                    else None,
                    meta=dict(row.meta or {}),
                )
                for row in rows
            }

        result: dict[str, AttachmentContent] = await self._run(op)
        return result

    async def delete_unattached(self, attachment_id: str) -> bool | None:
        """Retire une pièce jointe pas encore envoyée. None = introuvable ; False = déjà dans une
        conversation (elle part avec la conversation)."""

        async def op(s: AsyncSession) -> bool | None:
            row = await s.get(AttachmentRow, attachment_id)
            if row is None:
                return None
            if row.conversation_id:
                return False
            await s.delete(row)
            await s.commit()
            return True

        result: bool | None = await self._run(op)
        return result

    async def purge_orphans(self, now: datetime | None = None) -> int:
        """Supprime les pièces jointes jamais rattachées à une conversation depuis 24 h."""
        limit = (now or datetime.now(UTC)) - ORPHAN_AFTER

        async def op(s: AsyncSession) -> int:
            res = await s.execute(
                delete(AttachmentRow).where(
                    and_(AttachmentRow.conversation_id.is_(None), AttachmentRow.created_at < limit)
                )
            )
            await s.commit()
            return int(res.rowcount or 0)  # type: ignore[attr-defined]

        result: int = await self._run(op)
        return result


async def attach_to_conversation(s: AsyncSession, conversation_id: str, ids: list[str]) -> None:
    """Dans la transaction d'enregistrement d'un tour : rattache les pièces jointes citées."""
    if ids:
        await s.execute(
            update(AttachmentRow)
            .where(and_(AttachmentRow.id.in_(ids), AttachmentRow.conversation_id.is_(None)))
            .values(conversation_id=conversation_id)
        )


async def delete_for_conversation(s: AsyncSession, conversation_id: str) -> None:
    await s.execute(delete(AttachmentRow).where(AttachmentRow.conversation_id == conversation_id))
