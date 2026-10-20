"""Accès aux conversations et à leurs artefacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.agents.base import AgentResult
from app.core.llm.attachments import referenced_ids
from app.core.llm.types import Message
from app.db.attachments import attach_to_conversation, delete_for_conversation
from app.db.models import ArtifactRow, ConversationRow
from app.db.repository import StorageError, _storage_message
from app.db.search import like_pattern, message_texts, search_text, snippet, terms
from app.schemas.conversations import (
    ConversationDetail,
    ConversationSummary,
    SearchHit,
    StoredArtifact,
    TurnMeta,
    title_from,
)

MAX_LIST = 200


def _summary(row: ConversationRow, artifact_count: int) -> ConversationSummary:
    return ConversationSummary(
        id=row.id,
        agent=row.agent,
        title=row.title or "Nouvelle conversation",
        created_at=row.created_at,
        updated_at=row.updated_at,
        message_count=len(row.history or []),
        artifact_count=artifact_count,
    )


def _detail(row: ConversationRow) -> ConversationDetail:
    return ConversationDetail(
        **_summary(row, len(row.artifacts)).model_dump(),
        history=[Message.model_validate(m) for m in row.history or []],
        artifacts=[
            StoredArtifact(
                id=a.id,
                agent=a.agent,
                kind=a.kind,
                title=a.title,
                content=a.content,
                language=a.language,
                metadata=a.meta or {},
                position=a.position,
                created_at=a.created_at,
            )
            for a in row.artifacts
        ],
        turn_meta={k: TurnMeta.model_validate(v) for k, v in (row.turn_meta or {}).items()},
        pending_approvals=list(row.pending or []),
    )


class ConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run(self, fn: Any) -> Any:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc

    async def create(self, agent: str, title: str = "") -> ConversationDetail:
        async def op(s: AsyncSession) -> ConversationDetail:
            row = ConversationRow(agent=agent, title=title, history=[], turn_meta={}, pending=[])
            s.add(row)
            await s.commit()
            await s.refresh(row, ["artifacts"])
            return _detail(row)

        result: ConversationDetail = await self._run(op)
        return result

    async def recent(self, agent: str | None = None, limit: int = 50) -> list[ConversationSummary]:
        async def op(s: AsyncSession) -> list[ConversationSummary]:
            counts = (
                select(ArtifactRow.conversation_id, func.count().label("n"))
                .group_by(ArtifactRow.conversation_id)
                .subquery()
            )
            query = (
                select(ConversationRow, func.coalesce(counts.c.n, 0))
                .outerjoin(counts, counts.c.conversation_id == ConversationRow.id)
                .order_by(ConversationRow.updated_at.desc())
                .limit(min(limit, MAX_LIST))
            )
            if agent:
                query = query.where(ConversationRow.agent == agent)
            rows = (await s.execute(query)).all()
            return [_summary(row, int(n)) for row, n in rows]

        result: list[ConversationSummary] = await self._run(op)
        return result

    @staticmethod
    async def _artifacts_of(s: AsyncSession, conversation_id: str) -> list[ArtifactRow]:
        rows = await s.scalars(
            select(ArtifactRow).where(ArtifactRow.conversation_id == conversation_id)
        )
        return list(rows)

    async def search(
        self, query: str, agent: str | None = None, limit: int = 30
    ) -> list[SearchHit]:
        """Conversations contenant TOUS les mots (sans accents ni casse), les plus récentes d'abord."""
        words = terms(query)
        if not words:
            return []

        async def op(s: AsyncSession) -> list[SearchHit]:
            counts = (
                select(ArtifactRow.conversation_id, func.count().label("n"))
                .group_by(ArtifactRow.conversation_id)
                .subquery()
            )
            condition = and_(
                *(ConversationRow.search_text.like(like_pattern(w), escape="\\") for w in words)
            )
            q = (
                select(ConversationRow, func.coalesce(counts.c.n, 0))
                .outerjoin(counts, counts.c.conversation_id == ConversationRow.id)
                .where(condition)
                .order_by(ConversationRow.updated_at.desc())
                .limit(min(limit, MAX_LIST))
            )
            if agent:
                q = q.where(ConversationRow.agent == agent)
            hits = []
            for row, n in (await s.execute(q)).all():
                arts = await self._artifacts_of(s, row.id)
                texts = [
                    *message_texts(row.history or []),
                    *(f"{a.title} : {a.content}" for a in arts),
                ]
                hits.append(
                    SearchHit(**_summary(row, int(n)).model_dump(), snippet=snippet(texts, words))
                )
            return hits

        result: list[SearchHit] = await self._run(op)
        return result

    async def get(self, conversation_id: str) -> ConversationDetail | None:
        async def op(s: AsyncSession) -> ConversationDetail | None:
            row = await s.scalar(
                select(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .options(selectinload(ConversationRow.artifacts))
            )
            return _detail(row) if row else None

        result: ConversationDetail | None = await self._run(op)
        return result

    async def agent_of(self, conversation_id: str) -> str | None:
        async def op(s: AsyncSession) -> str | None:
            agent: str | None = await s.scalar(
                select(ConversationRow.agent).where(ConversationRow.id == conversation_id)
            )
            return agent

        result: str | None = await self._run(op)
        return result

    async def save_turn(
        self, conversation_id: str, sent: list[Message], result: AgentResult
    ) -> None:
        """Après un tour : historique complet, méta du tour, artefacts, validations en attente."""

        async def op(s: AsyncSession) -> None:
            row = await s.get(ConversationRow, conversation_id)
            if row is None:
                return
            history = [*sent, *result.new_messages]
            row.history = [m.model_dump(mode="json") for m in history]
            if not row.title:
                row.title = title_from(history)
            meta = dict(row.turn_meta or {})
            if result.new_messages:
                meta[str(len(history) - 1)] = TurnMeta(
                    provider=result.provider,
                    model=result.model,
                    usage=result.usage,
                    stop_reason=result.stop_reason,
                    iterations=result.iterations,
                ).model_dump(mode="json")
            row.turn_meta = meta
            row.pending = [p.model_dump(mode="json") for p in result.pending_approvals]
            pieces = [(a.title, a.content) for a in await self._artifacts_of(s, row.id)]
            pieces += [(a.title, a.content) for a in result.artifacts]
            row.search_text = search_text(row.title, row.history, pieces)
            await attach_to_conversation(s, row.id, referenced_ids(history))
            for artifact in result.artifacts:
                s.add(
                    ArtifactRow(
                        conversation_id=row.id,
                        agent=result.agent,
                        kind=artifact.kind,
                        title=artifact.title,
                        content=artifact.content,
                        language=artifact.language,
                        meta=artifact.metadata,
                        position=len(history),
                    )
                )
            await s.commit()

        await self._run(op)

    async def rename(self, conversation_id: str, title: str) -> ConversationDetail | None:
        async def op(s: AsyncSession) -> bool:
            row = await s.get(ConversationRow, conversation_id)
            if row is None:
                return False
            row.title = title
            pieces = [(a.title, a.content) for a in await self._artifacts_of(s, row.id)]
            row.search_text = search_text(title, row.history or [], pieces)
            await s.commit()
            return True

        return await self.get(conversation_id) if await self._run(op) else None

    async def delete(self, conversation_id: str) -> bool:
        async def op(s: AsyncSession) -> bool:
            await s.execute(
                delete(ArtifactRow).where(ArtifactRow.conversation_id == conversation_id)
            )
            await delete_for_conversation(s, conversation_id)
            res = await s.execute(
                delete(ConversationRow).where(ConversationRow.id == conversation_id)
            )
            await s.commit()
            return bool(res.rowcount)  # type: ignore[attr-defined]

        result: bool = await self._run(op)
        return result
