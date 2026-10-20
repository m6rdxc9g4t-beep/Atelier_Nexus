"""Accès aux agents personnalisés."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CustomAgentRow
from app.schemas.agents import CustomAgentCreate, CustomAgentDefinition, CustomAgentUpdate


class StorageError(Exception):
    """Base de données indisponible ou schéma absent (migration non appliquée)."""


class DuplicateAgentError(Exception):
    pass


def _to_definition(row: CustomAgentRow) -> CustomAgentDefinition:
    return CustomAgentDefinition.model_validate(row)


class CustomAgentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def list(self) -> list[CustomAgentDefinition]:
        try:
            async with self.sessions() as s:
                rows = (
                    await s.scalars(select(CustomAgentRow).order_by(CustomAgentRow.display_name))
                ).all()
                return [_to_definition(r) for r in rows]
        except SQLAlchemyError as exc:
            raise StorageError(_storage_message(exc)) from exc
        except OSError as exc:
            raise StorageError(f"Base de données injoignable : {exc}") from exc

    async def get(self, name: str) -> CustomAgentDefinition | None:
        try:
            async with self.sessions() as s:
                row = await s.scalar(select(CustomAgentRow).where(CustomAgentRow.name == name))
                return _to_definition(row) if row else None
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc

    async def create(self, data: CustomAgentCreate) -> CustomAgentDefinition:
        try:
            async with self.sessions() as s:
                row = CustomAgentRow(**data.model_dump())
                s.add(row)
                await s.commit()
                await s.refresh(row)
                return _to_definition(row)
        except IntegrityError as exc:
            raise DuplicateAgentError(data.name) from exc
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc

    async def update(self, name: str, data: CustomAgentUpdate) -> CustomAgentDefinition | None:
        try:
            async with self.sessions() as s:
                row = await s.scalar(select(CustomAgentRow).where(CustomAgentRow.name == name))
                if row is None:
                    return None
                for key, value in data.model_dump().items():
                    setattr(row, key, value)
                await s.commit()
                await s.refresh(row)
                return _to_definition(row)
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc

    async def delete(self, name: str) -> bool:
        try:
            async with self.sessions() as s:
                row = await s.scalar(select(CustomAgentRow).where(CustomAgentRow.name == name))
                if row is None:
                    return False
                await s.delete(row)
                await s.commit()
                return True
        except (SQLAlchemyError, OSError) as exc:
            raise StorageError(_storage_message(exc)) from exc


def _storage_message(exc: Exception) -> str:
    text = str(exc).lower()
    if "no such table" in text or "does not exist" in text or "undefinedtable" in text:
        return "Table des agents absente : lancez « alembic upgrade head » dans backend/."
    return "Base de données indisponible : vérifiez DATABASE_URL et que PostgreSQL tourne."
