"""Horodatages : toujours relus avec fuseau UTC, même sur SQLite (bureau, tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import Integer, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.db.models import Base, UtcDateTime


class _Base(DeclarativeBase):
    pass


class _Row(_Base):
    __tablename__ = "dates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


def _roundtrip(value: datetime | None) -> datetime | None:
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_Row(id=1, at=value))
        session.commit()
        return session.scalar(select(_Row.at))


def test_sqlite_returns_aware_utc_datetimes() -> None:
    at = datetime(2026, 10, 22, 8, 10, 4, tzinfo=UTC)
    read = _roundtrip(at)
    assert read == at and read is not None and read.utcoffset() == timedelta(0)
    # Sérialisé pour l'API : le navigateur ne peut plus la lire comme une heure locale.
    assert read.isoformat() == "2026-10-22T08:10:04+00:00"


def test_other_offsets_are_stored_as_utc() -> None:
    paris = timezone(timedelta(hours=2))
    read = _roundtrip(datetime(2026, 10, 22, 10, 10, tzinfo=paris))
    assert read == datetime(2026, 10, 22, 8, 10, tzinfo=UTC)
    assert read is not None and read.tzinfo is not None and read.utcoffset() == timedelta(0)


def test_naive_values_are_taken_as_utc_and_none_stays_none() -> None:
    assert _roundtrip(datetime(2026, 10, 22, 8, 10)) == datetime(2026, 10, 22, 8, 10, tzinfo=UTC)
    assert _roundtrip(None) is None


def test_every_timestamp_column_of_the_models_uses_utc_datetime() -> None:
    columns = [
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.type.python_type is datetime and not isinstance(column.type, UtcDateTime)
    ]
    assert columns == []
