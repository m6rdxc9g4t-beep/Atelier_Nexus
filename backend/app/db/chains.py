"""Accès aux exécutions de chaînes d'agents."""

from __future__ import annotations

import builtins
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChainRunRow
from app.db.repository import StorageError, _storage_message
from app.schemas.chains import ChainRun, RunStatus, StageState

MAX_LIST = 100


def _to_model(row: ChainRunRow) -> ChainRun:
    return ChainRun.model_validate(row)


def _storage(exc: Exception) -> StorageError:
    text = str(exc).lower()
    if "no such table" in text or "does not exist" in text or "undefinedtable" in text:
        return StorageError(
            "Table des chaînes absente : lancez « alembic upgrade head » dans backend/."
        )
    return StorageError(_storage_message(exc))


class ChainRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run[T](self, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise _storage(exc) from exc

    async def create(self, chain: str, request: str, stages: list[StageState]) -> ChainRun:
        async def op(s: AsyncSession) -> ChainRun:
            row = ChainRunRow(
                chain=chain,
                request=request,
                status="running",
                stage_index=0,
                stages=[st.model_dump(mode="json") for st in stages],
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def get(self, run_id: str) -> ChainRun | None:
        async def op(s: AsyncSession) -> ChainRun | None:
            row = await s.get(ChainRunRow, run_id)
            return _to_model(row) if row else None

        return await self._run(op)

    async def list(self, chain: str | None = None) -> builtins.list[ChainRun]:
        async def op(s: AsyncSession) -> builtins.list[ChainRun]:
            q = select(ChainRunRow).order_by(ChainRunRow.updated_at.desc()).limit(MAX_LIST)
            if chain:
                q = q.where(ChainRunRow.chain == chain)
            return [_to_model(r) for r in (await s.scalars(q)).all()]

        return await self._run(op)

    async def save(
        self,
        run_id: str,
        *,
        status: RunStatus,
        stage_index: int,
        stages: builtins.list[StageState],
        expect_index: int,
    ) -> ChainRun | None:
        """Enregistre une transition SEULEMENT si la chaîne est toujours en cours à l'étape
        `expect_index` (sinon None) : deux validations simultanées, ou une validation après un
        arrêt, ne peuvent pas s'écraser."""

        async def op(s: AsyncSession) -> ChainRun | None:
            result = await s.execute(
                update(ChainRunRow)
                .where(
                    ChainRunRow.id == run_id,
                    ChainRunRow.status == "running",
                    ChainRunRow.stage_index == expect_index,
                )
                .values(
                    status=status,
                    stage_index=stage_index,
                    stages=[st.model_dump(mode="json") for st in stages],
                    updated_at=datetime.now(UTC),
                )
            )
            await s.commit()
            if not getattr(result, "rowcount", 0):
                return None
            row = await s.get(ChainRunRow, run_id, populate_existing=True)
            return _to_model(row) if row else None

        return await self._run(op)
