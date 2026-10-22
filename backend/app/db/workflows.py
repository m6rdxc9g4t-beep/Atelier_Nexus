"""Accès aux workflows rejouables (v1 et v2) et aux exécutions des workflows v2."""

from __future__ import annotations

import builtins
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WorkflowRow, WorkflowRunRow, WorkflowTriggerRow
from app.db.repository import StorageError, _storage_message
from app.schemas.workflows import RunStatus, Workflow, WorkflowCreate, WorkflowUpdate
from app.schemas.workflows_v2 import (
    WorkflowRun,
    WorkflowV2,
    WorkflowV2Create,
    WorkflowV2Fields,
    WorkflowV2Update,
)

MAX_LIST = 200
MAX_RUNS = 100

AnyWorkflow = Workflow | WorkflowV2


def _to_model(row: WorkflowRow) -> AnyWorkflow:
    if row.version == 2:
        return WorkflowV2.model_validate(row)
    return Workflow.model_validate(row)


def _storage(exc: Exception) -> StorageError:
    text = str(exc).lower()
    if "no such table" in text or "does not exist" in text or "undefinedtable" in text:
        return StorageError(
            "Table des workflows absente : lancez « alembic upgrade head » dans backend/."
        )
    if "no such column" in text or "undefinedcolumn" in text:
        return StorageError(
            "Base des workflows à mettre à jour : lancez « alembic upgrade head » dans backend/."
        )
    return StorageError(_storage_message(exc))


def run_to_model(row: WorkflowRunRow) -> WorkflowRun:
    return WorkflowRun.model_validate(
        {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "status": row.status,
            "message": row.message,
            "params": row.params,
            "trigger": row.trigger,
            "trigger_id": row.trigger_id,
            "trigger_event": row.trigger_event,
            "steps": row.steps,
            "artifacts": row.artifacts,
            "pending": row.pending,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


class WorkflowRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run[T](self, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise _storage(exc) from exc

    async def list(self, agent: str | None = None) -> list[AnyWorkflow]:
        async def op(s: AsyncSession) -> list[AnyWorkflow]:
            query = select(WorkflowRow).order_by(WorkflowRow.updated_at.desc()).limit(MAX_LIST)
            if agent:
                query = query.where(WorkflowRow.agent == agent)
            return [_to_model(r) for r in (await s.scalars(query)).all()]

        return await self._run(op)

    async def get(self, workflow_id: str) -> AnyWorkflow | None:
        async def op(s: AsyncSession) -> AnyWorkflow | None:
            row = await s.get(WorkflowRow, workflow_id)
            return _to_model(row) if row else None

        return await self._run(op)

    async def create(self, data: WorkflowCreate | WorkflowV2Create) -> AnyWorkflow:
        async def op(s: AsyncSession) -> AnyWorkflow:
            values = data.model_dump(mode="json")
            values["version"] = 2 if isinstance(data, WorkflowV2Create) else 1
            row = WorkflowRow(**values)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def update(
        self, workflow_id: str, data: WorkflowUpdate | WorkflowV2Update
    ) -> AnyWorkflow | None:
        async def op(s: AsyncSession) -> AnyWorkflow | None:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            values = data.model_dump(mode="json", exclude={"source_conversation_id"})
            values.pop("version", None)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def replace_with_v2(self, workflow_id: str, data: WorkflowV2Fields) -> AnyWorkflow | None:
        """Conversion v1 → v2 : même identifiant, compteurs conservés."""

        async def op(s: AsyncSession) -> AnyWorkflow | None:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            row.version = 2
            row.agent = data.agent
            row.title = data.title
            row.description = data.description
            row.steps = [st.model_dump(mode="json") for st in data.steps]
            row.params = [p.model_dump(mode="json") for p in data.params]
            row.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(row)
            return _to_model(row)

        return await self._run(op)

    async def delete(self, workflow_id: str) -> bool:
        """Supprime le workflow et ses déclencheurs (explicitement : SQLite n'applique pas les
        clés étrangères sans PRAGMA). Les exécutions passées restent consultables."""

        async def op(s: AsyncSession) -> bool:
            row = await s.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            await s.execute(
                delete(WorkflowTriggerRow).where(WorkflowTriggerRow.workflow_id == workflow_id)
            )
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

    # ─── Exécutions (v2) ──────────────────────────────────────────

    async def save_run(self, run: WorkflowRun, state: dict[str, Any]) -> WorkflowRun:
        """Crée ou met à jour une exécution (`state` : interne, jamais renvoyé)."""

        async def op(s: AsyncSession) -> WorkflowRun:
            row = await s.get(WorkflowRunRow, run.id)
            values = run.model_dump(mode="json", exclude={"created_at", "updated_at"})
            if row is None:
                row = WorkflowRunRow(**values, state=state, created_at=run.created_at)
                s.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.state = state
            row.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(row)
            return run_to_model(row)

        return await self._run(op)

    async def claim_run(self, run_id: str) -> bool:
        """Passe une exécution en attente à `running`, une seule fois : deux reprises
        simultanées n'exécutent pas deux fois l'action validée."""

        async def op(s: AsyncSession) -> bool:
            result = await s.execute(
                update(WorkflowRunRow)
                .where(WorkflowRunRow.id == run_id, WorkflowRunRow.status == "awaiting_approval")
                .values(status="running", updated_at=datetime.now(UTC))
            )
            await s.commit()
            return bool(getattr(result, "rowcount", 0))

        return await self._run(op)

    async def get_run(self, run_id: str) -> tuple[WorkflowRun, dict[str, Any]] | None:
        async def op(s: AsyncSession) -> tuple[WorkflowRun, dict[str, Any]] | None:
            row = await s.get(WorkflowRunRow, run_id)
            return (run_to_model(row), dict(row.state or {})) if row else None

        return await self._run(op)

    async def list_runs(
        self, workflow_id: str | None, limit: int, status: str | None = None
    ) -> builtins.list[WorkflowRun]:
        """Exécutions récentes d'abord ; filtres facultatifs par workflow et par statut (boîte
        « À valider » : `status="awaiting_approval"`, tous workflows)."""

        async def op(s: AsyncSession) -> builtins.list[WorkflowRun]:
            query = (
                select(WorkflowRunRow)
                .order_by(WorkflowRunRow.created_at.desc())
                .limit(max(1, min(limit, MAX_RUNS)))
            )
            if workflow_id:
                query = query.where(WorkflowRunRow.workflow_id == workflow_id)
            if status:
                query = query.where(WorkflowRunRow.status == status)
            return [run_to_model(r) for r in (await s.scalars(query)).all()]

        return await self._run(op)

    async def count_runs(self, status: str) -> int:
        async def op(s: AsyncSession) -> int:
            query = select(func.count()).select_from(WorkflowRunRow)
            return int(await s.scalar(query.where(WorkflowRunRow.status == status)) or 0)

        return await self._run(op)

    async def has_waiting_run(self, trigger_id: str) -> bool:
        """Une exécution lancée par ce déclencheur (test compris) attend-elle une validation ?
        Si oui, les nouveaux déclenchements sont ignorés : pas de doublons dans « À valider »."""

        async def op(s: AsyncSession) -> bool:
            query = (
                select(WorkflowRunRow.id)
                .where(
                    WorkflowRunRow.trigger_id == trigger_id,
                    WorkflowRunRow.status == "awaiting_approval",
                )
                .limit(1)
            )
            return (await s.scalar(query)) is not None

        return await self._run(op)

    async def run_statuses(self, run_ids: builtins.list[str]) -> dict[str, str]:
        """Statut actuel de quelques exécutions (état des déclencheurs à jour après une reprise)."""
        if not run_ids:
            return {}

        async def op(s: AsyncSession) -> dict[str, str]:
            query = select(WorkflowRunRow.id, WorkflowRunRow.status).where(
                WorkflowRunRow.id.in_(run_ids)
            )
            return {row[0]: row[1] for row in (await s.execute(query)).all()}

        return await self._run(op)
