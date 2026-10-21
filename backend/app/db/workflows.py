"""Accès aux workflows rejouables."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WorkflowRow
from app.db.repository import StorageError, _storage_message
from app.schemas.workflows import RunStatus, Workflow, WorkflowCreate, WorkflowUpdate

MAX_LIST = 200


def _to_model(row: WorkflowRow) -> Workflow:
    return Workflow.model_validate(row)


def _storage(exc: Exception) -> StorageError:
    message = _storage_message(exc)
    if "agents absente" in message:
        message = "Table des workflows absente : lancez « alembic upgrade head » dans backend/."
    return StorageError(message)


class WorkflowRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run[T](self, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise _storage(exc) from exc

    async def list(self, agent: str | None = None) -> list[Workflow]:
        async def op(s: AsyncSession) -> list[Workflow]:
            query = select(WorkflowRow).order_by(WorkflowRow.updated_at.desc()).limit(MAX_LIST)
            if agent:
                query = query.where(WorkflowRow.agent == agent)
            return [_to_model(r) for r in (await s.scalars(query)).all()]

        return await self._run(op)

    async def get(self, workflow_id: str) -> Workflow | None:
        async def op(s: AsyncSession) -> Workflow | None:
            row = await s.get(WorkflowRow, workflow_id)
            return _to_model(row) if row else None

        return await self._run(op)

    async def create(self, data: WorkflowCreate) -> Workflow:
        async def op(s: AsyncSession) -> Workflow:
            row = WorkflowRow(**data.model_dump(mode="json"))
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def update(self, workflow_id: str, data: WorkflowUpdate) -> Workflow | None:
        async def op(s: AsyncSession) -> Workflow | None:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            for key, value in data.model_dump(mode="json").items():
                setattr(row, key, value)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def delete(self, workflow_id: str) -> bool:
        async def op(s: AsyncSession) -> bool:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True

        return await self._run(op)

    async def record_run(self, workflow_id: str, status: RunStatus) -> None:
        """Compteur et dernier résultat ; le workflow remonte en tête de liste."""

        async def op(s: AsyncSession) -> None:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return
            row.run_count += 1
            row.last_run_at = datetime.now(UTC)
            row.last_status = status
            await s.commit()

        await self._run(op)
