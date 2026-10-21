"""Doubles communs aux tests des workflows v2 et de la carte : trois nœuds simulés, base SQLite
en mémoire, client de l'API avec dépendances remplacées."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents import AgentCatalog
from app.api.deps import get_catalog, get_env_factory, get_workflow_repository
from app.core.llm import get_llm_router
from app.db.models import Base
from app.db.workflows import WorkflowRepository
from main import app
from tests.fakes import make_router
from tests.test_suite_nodes import Suite


@pytest.fixture
def suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Suite:
    return Suite(tmp_path, monkeypatch)


@pytest.fixture
async def repo() -> AsyncIterator[WorkflowRepository]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield WorkflowRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


@pytest.fixture
def client(repo: WorkflowRepository, suite: Suite) -> Iterator[TestClient]:
    router = make_router()
    app.dependency_overrides[get_llm_router] = lambda: router
    app.dependency_overrides[get_catalog] = lambda: AgentCatalog()
    app.dependency_overrides[get_env_factory] = lambda: suite.env
    app.dependency_overrides[get_workflow_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()
