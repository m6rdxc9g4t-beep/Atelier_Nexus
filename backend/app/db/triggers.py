"""Accès aux déclencheurs de workflows et aux curseurs d'événements par application.

`mutate` applique une fonction à l'état *frais* d'un déclencheur et l'enregistre dans la même
session : le moteur ne travaille jamais sur une copie périmée. Les modifications par l'API et les
passages de fond d'un même déclencheur sont sérialisés par son verrou (`trigger_lock`) ; un seul
processus Nexus est visé (docs/workflows.md, section Déclencheurs).
"""

from __future__ import annotations

import builtins
import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TriggerCursorRow, WorkflowTriggerRow
from app.db.workflows import _storage
from app.schemas.triggers import (
    EventTrigger,
    EventTriggerFields,
    ScheduleTrigger,
    ScheduleTriggerFields,
    TriggerState,
)

AnyTrigger = ScheduleTrigger | EventTrigger
AnyFields = ScheduleTriggerFields | EventTriggerFields
MAX_TRIGGERS = 500


@dataclass
class StoredTrigger:
    trigger: AnyTrigger
    #: Données du moteur (fenêtre de débit, rafale en attente) : jamais renvoyées par l'API
    internal: dict[str, Any]

    @property
    def id(self) -> str:
        return self.trigger.id


def to_model(row: WorkflowTriggerRow) -> AnyTrigger:
    config = row.config or {}
    base: dict[str, Any] = {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "kind": row.kind,
        "label": row.label,
        "enabled": row.enabled,
        "params": row.params or {},
        "max_runs_per_hour": row.max_runs_per_hour,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "state": row.state or {},
    }
    if row.kind == "schedule":
        return ScheduleTrigger.model_validate(base | {"schedule": config.get("schedule")})
    return EventTrigger.model_validate(
        base
        | {
            "app": row.app,
            "types": config.get("types", []),
            "filters": config.get("filters", []),
            "debounce_seconds": config.get("debounce_seconds", 0),
        }
    )


def _stored(row: WorkflowTriggerRow) -> StoredTrigger:
    return StoredTrigger(to_model(row), copy.deepcopy(row.internal or {}))


def _columns(fields: AnyFields) -> dict[str, Any]:
    """Colonnes d'un corps validé : communes + `config` propre au type."""
    common = {
        "kind": fields.kind,
        "label": fields.label,
        "enabled": fields.enabled,
        "params": dict(fields.params),
        "max_runs_per_hour": fields.max_runs_per_hour,
    }
    if isinstance(fields, ScheduleTriggerFields):
        return common | {
            "app": None,
            "config": {"schedule": fields.schedule.model_dump(mode="json")},
        }
    return common | {
        "app": fields.app,
        "config": {
            "types": list(fields.types),
            "filters": [f.model_dump(mode="json") for f in fields.filters],
            "debounce_seconds": fields.debounce_seconds,
        },
    }


class TriggerRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _run[T](self, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self.sessions() as s:
                return await fn(s)
        except (SQLAlchemyError, OSError) as exc:
            raise _storage(exc) from exc

    async def list(
        self,
        workflow_id: str | None = None,
        *,
        enabled_only: bool = False,
    ) -> builtins.list[StoredTrigger]:
        """Déclencheurs, du plus ancien au plus récent (ordre de distribution stable)."""

        async def op(s: AsyncSession) -> builtins.list[StoredTrigger]:
            query = (
                select(WorkflowTriggerRow)
                .order_by(WorkflowTriggerRow.created_at, WorkflowTriggerRow.id)
                .limit(MAX_TRIGGERS)
            )
            if workflow_id is not None:
                query = query.where(WorkflowTriggerRow.workflow_id == workflow_id)
            if enabled_only:
                query = query.where(WorkflowTriggerRow.enabled.is_(True))
            return [_stored(r) for r in (await s.scalars(query)).all()]

        return await self._run(op)

    async def get(self, trigger_id: str) -> StoredTrigger | None:
        async def op(s: AsyncSession) -> StoredTrigger | None:
            row = await s.get(WorkflowTriggerRow, trigger_id)
            return _stored(row) if row else None

        return await self._run(op)

    async def create(
        self,
        workflow_id: str,
        fields: AnyFields,
        state: TriggerState,
        internal: dict[str, Any],
    ) -> StoredTrigger:
        async def op(s: AsyncSession) -> StoredTrigger:
            now = datetime.now(UTC)
            row = WorkflowTriggerRow(
                workflow_id=workflow_id,
                **_columns(fields),
                state=state.model_dump(mode="json"),
                internal=internal,
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _stored(row)

        return await self._run(op)

    async def update(
        self,
        trigger_id: str,
        fields: AnyFields,
        state: TriggerState,
        internal: dict[str, Any],
    ) -> StoredTrigger | None:
        async def op(s: AsyncSession) -> StoredTrigger | None:
            row = await s.get(WorkflowTriggerRow, trigger_id)
            if row is None:
                return None
            for key, value in _columns(fields).items():
                setattr(row, key, value)
            row.state = state.model_dump(mode="json")
            row.internal = internal
            row.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(row)
            return _stored(row)

        return await self._run(op)

    async def delete(self, trigger_id: str) -> bool:
        async def op(s: AsyncSession) -> bool:
            result = await s.execute(
                delete(WorkflowTriggerRow).where(WorkflowTriggerRow.id == trigger_id)
            )
            await s.commit()
            return bool(getattr(result, "rowcount", 0))

        return await self._run(op)

    async def mutate[T](
        self,
        trigger_id: str,
        fn: Callable[[StoredTrigger, TriggerState, dict[str, Any]], T],
    ) -> T | None:
        """Applique `fn(déclencheur frais, état, données internes)` puis enregistre l'état et les
        données internes (sans toucher `updated_at`, réservé aux modifications par l'API).
        None si le déclencheur n'existe plus."""

        async def op(s: AsyncSession) -> T | None:
            row = await s.get(WorkflowTriggerRow, trigger_id)
            if row is None:
                return None
            stored = _stored(row)
            state = stored.trigger.state.model_copy(deep=True)
            internal = copy.deepcopy(stored.internal)
            result = fn(stored, state, internal)
            await s.execute(
                update(WorkflowTriggerRow)
                .where(WorkflowTriggerRow.id == trigger_id)
                .values(
                    state=state.model_dump(mode="json"),
                    internal=internal,
                    updated_at=row.updated_at,
                )
            )
            await s.commit()
            return result

        return await self._run(op)

    # ─── Curseurs d'événements (un par application) ───────────────

    async def get_cursor(self, app: str) -> int | None:
        async def op(s: AsyncSession) -> int | None:
            row = await s.get(TriggerCursorRow, app)
            return row.seq if row else None

        return await self._run(op)

    async def set_cursor(self, app: str, seq: int) -> None:
        async def op(s: AsyncSession) -> None:
            row = await s.get(TriggerCursorRow, app)
            if row is None:
                s.add(TriggerCursorRow(app=app, seq=seq, updated_at=datetime.now(UTC)))
            elif row.seq != seq:
                row.seq = seq
                row.updated_at = datetime.now(UTC)
            await s.commit()

        await self._run(op)
