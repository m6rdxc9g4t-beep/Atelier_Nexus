"""Workflows rejouables : capture d'un tour, paramètres, exécution sans modèle, validations, API."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents import AgentCatalog, get_agent_class
from app.api.deps import get_catalog, get_env_factory, get_workflow_repository
from app.core.config import Settings
from app.core.llm import get_llm_router
from app.core.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.db.models import Base
from app.db.workflows import WorkflowRepository
from app.schemas.workflows import WorkflowCreate, WorkflowParam, WorkflowStep
from app.tools.environment import ToolEnvironment
from app.workflows import WorkflowError, capture, resolve_params, run_workflow, substitute
from main import app
from tests.fake_data_via import DATASET_ID, FakeDataVia
from tests.fakes import make_router
from tests.test_connectors import FakeProjets

BACKEND = Path(__file__).resolve().parents[1]


def settings() -> Settings:
    return Settings(
        _env_file=None,
        data_via_base_url="http://viz.test/api",
        projets_base_url="http://projets.test/api",
        tresorerie_base_url=None,
        tab_exports_dir=None,
        github_repo=None,
    )


class Apps:
    def __init__(self) -> None:
        self.viz = FakeDataVia()
        self.projets = FakeProjets()

    def env(self) -> ToolEnvironment:
        return ToolEnvironment(
            settings(),
            transports={
                "data_via": self.viz.transport,
                "projets": httpx.MockTransport(self.projets),
            },
        )


@pytest.fixture
def apps() -> Apps:
    return Apps()


def agent(name: str, apps: Apps) -> Any:
    return get_agent_class(name)(make_router(), apps.env())


# ─── Capture ──────────────────────────────────────────────────────

DESCRIBE = {"dataset_id": DATASET_ID}
QUERY = {
    "dataset_id": DATASET_ID,
    "dimensions": [{"field": "region"}],
    "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
}


def use(call_id: str, name: str, args: dict[str, Any], text: str = "") -> Message:
    blocks: list[Any] = [TextBlock(text=text)] if text else []
    return Message(
        role="assistant", content=[*blocks, ToolUseBlock(id=call_id, name=name, input=args)]
    )


def result(call_id: str, name: str, *, error: bool = False) -> Message:
    return Message(
        role="user",
        content=[ToolResultBlock(tool_use_id=call_id, tool_name=name, content="…", is_error=error)],
    )


def conversation() -> list[Message]:
    return [
        Message.user("Bonjour"),
        use("old", "data_via_list_datasets", {}),
        result("old", "data_via_list_datasets"),
        Message(role="assistant", content=[TextBlock(text="Un jeu : ventes.")]),
        Message.user("Chiffre d'affaires par région, puis la mesure DAX"),
        use("a", "current_datetime", {}),
        result("a", "current_datetime"),
        use("b", "data_via_describe_dataset", DESCRIBE),
        result("b", "data_via_describe_dataset"),
        use("c", "data_via_query", {**QUERY, "dimensions": [{"field": "regiox"}]}),
        result("c", "data_via_query", error=True),
        use("d", "data_via_query", QUERY),
        result("d", "data_via_query"),
        use(
            "e", "publish_artifact", {"kind": "dax", "title": "CA", "content": "CA = SUM ( V[ca] )"}
        ),
        result("e", "publish_artifact"),
        Message(role="assistant", content=[TextBlock(text="Voilà.")]),
    ]


def test_capture_keeps_successful_calls_of_the_last_turn(apps: Apps) -> None:
    draft = capture(agent("data_analyst", apps), conversation())
    assert [s.tool for s in draft.steps] == [
        "data_via_describe_dataset",
        "data_via_query",
        "publish_artifact",
    ]
    assert draft.steps[1].input == QUERY
    assert {(s.tool, s.reason.split(" ")[0]) for s in draft.skipped} == {
        ("current_datetime", "n'apporte"),
        ("data_via_query", "refusé"),
    }
    assert draft.title == "Chiffre d'affaires par région, puis la mesure DAX"
    assert "Data Analyst" in draft.description and draft.writes == []


def test_capture_flags_writes_and_skips_pending_ones(apps: Apps) -> None:
    create = {"story_id": 2, "type": "TASK", "title": "Tests", "estimated_hours": 4}
    messages = [
        Message.user("Crée deux tâches"),
        use("x", "projets_create_work_item", create),
        result("x", "projets_create_work_item"),
        use("y", "projets_create_work_item", {**create, "title": "Autre"}),  # jamais validé
    ]
    draft = capture(agent("chef_de_projet", apps), messages)
    assert [s.input["title"] for s in draft.steps] == ["Tests"] and draft.writes == [1]
    assert draft.skipped[0].reason.startswith("jamais exécuté")


def test_capture_without_any_usable_call_is_refused(apps: Apps) -> None:
    messages = [
        Message.user("Bonjour"),
        Message(role="assistant", content=[TextBlock(text="Salut")]),
    ]
    with pytest.raises(WorkflowError, match="Aucun appel"):
        capture(agent("assistant", apps), messages)


# ─── Paramètres ───────────────────────────────────────────────────


def test_substitute_types_whole_values_and_formats_partial_ones() -> None:
    values = {"jeu": "ds_ventes", "limite": "20", "net": "true", "mois": "2026-03"}
    out = substitute(
        {
            "dataset_id": "{{ jeu }}",
            "limit": "{{limite}}",
            "x": ["{{net}}"],
            "t": "Ventes {{mois}}",
        },
        values,
    )
    assert out == {"dataset_id": "ds_ventes", "limit": 20, "x": [True], "t": "Ventes 2026-03"}


def test_params_use_defaults_and_reject_unknown_or_missing() -> None:
    declared = [WorkflowParam(name="jeu", default="ds"), WorkflowParam(name="mois", label="Mois")]
    assert resolve_params(declared, {"mois": "2026-03"}) == {"jeu": "ds", "mois": "2026-03"}
    with pytest.raises(WorkflowError, match="Renseignez « Mois »"):
        resolve_params(declared, {})
    with pytest.raises(WorkflowError, match="inconnu"):
        resolve_params(declared, {"mois": "x", "pirate": "y"})


def test_placeholders_must_be_declared() -> None:
    with pytest.raises(ValueError, match="non déclaré"):
        WorkflowCreate(
            agent="data_analyst",
            title="x",
            steps=[WorkflowStep(tool="data_via_describe_dataset", input={"dataset_id": "{{jeu}}"})],
        )


# ─── Exécution ────────────────────────────────────────────────────

STEPS = [
    WorkflowStep(tool="data_via_describe_dataset", input={"dataset_id": "{{jeu}}"}),
    WorkflowStep(
        tool="data_via_query", input={**QUERY, "dataset_id": "{{jeu}}", "limit": "{{limite}}"}
    ),
]
PARAMS = [
    WorkflowParam(name="jeu", label="Jeu de données"),
    WorkflowParam(name="limite", default="50"),
]


async def test_run_replays_tools_with_shared_context_and_collects_artifacts(apps: Apps) -> None:
    result = await run_workflow(
        agent("data_analyst", apps), STEPS, PARAMS, {"jeu": DATASET_ID}, None
    )
    assert result.status == "completed", result.message
    assert [s.status for s in result.steps] == ["ok", "ok"]
    assert result.steps[1].input["limit"] == 50
    assert {a.kind for a in result.artifacts} == {"data_preview"}
    assert "2 étape(s) exécutée(s)" in result.message


async def test_run_stops_at_the_first_error(apps: Apps) -> None:
    result = await run_workflow(
        agent("data_analyst", apps), STEPS, PARAMS, {"jeu": "inconnu"}, None
    )
    assert result.status == "failed"
    assert [s.status for s in result.steps] == ["error", "skipped"]
    assert "Arrêt à l'étape 1" in result.message


async def test_invalid_step_is_caught_before_anything_runs(apps: Apps) -> None:
    result = await run_workflow(
        agent("data_analyst", apps), STEPS, PARAMS, {"jeu": DATASET_ID, "limite": "beaucoup"}, None
    )
    assert result.status == "failed" and "Étape 2" in result.message and "limit" in result.message
    assert not result.steps and not apps.viz.requests


async def test_unavailable_tool_is_reported(apps: Apps) -> None:
    steps = [WorkflowStep(tool="tresorerie_dashboard", input={})]
    result = await run_workflow(agent("data_analyst", apps), steps, [], {}, None)
    assert result.status == "failed" and "tresorerie_dashboard" in result.message


async def test_write_steps_wait_for_approval_like_in_the_chat(apps: Apps) -> None:
    chef = agent("chef_de_projet", apps)
    steps = [
        WorkflowStep(tool="projets_dashboard", input={"project_id": 1}),
        WorkflowStep(
            tool="projets_create_work_item",
            input={"story_id": 2, "type": "TASK", "title": "{{titre}}", "estimated_hours": 2},
        ),
    ]
    params = [WorkflowParam(name="titre")]
    posts = lambda: [r for r in apps.projets.requests if r.method == "POST"]  # noqa: E731

    waiting = await run_workflow(chef, steps, params, {"titre": "Relire la PR"}, None)
    assert waiting.status == "awaiting_approval" and not waiting.steps and not apps.projets.requests
    assert waiting.pending[0].index == 2
    assert (
        waiting.pending[0].summary == "Créer la TASK « Relire la PR » dans la story 2, 2 h estimées"
    )

    refused = await run_workflow(chef, steps, params, {"titre": "Relire la PR"}, {"2": False})
    assert refused.status == "completed" and [s.status for s in refused.steps] == ["ok", "refused"]
    assert not posts()

    done = await run_workflow(chef, steps, params, {"titre": "Relire la PR"}, {"2": True})
    assert [s.status for s in done.steps] == ["ok", "ok"] and len(posts()) == 1


# ─── API ──────────────────────────────────────────────────────────


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
def client(repo: WorkflowRepository, apps: Apps) -> Iterator[TestClient]:
    router = make_router()
    app.dependency_overrides[get_llm_router] = lambda: router
    app.dependency_overrides[get_catalog] = lambda: AgentCatalog()
    app.dependency_overrides[get_env_factory] = lambda: apps.env
    app.dependency_overrides[get_workflow_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def payload(**extra: Any) -> dict[str, Any]:
    return {
        "agent": "data_analyst",
        "title": "CA par région",
        "description": "Tous les lundis.",
        "steps": [s.model_dump() for s in STEPS],
        "params": [p.model_dump() for p in PARAMS],
        **extra,
    }


def test_api_capture_then_save_list_run_update_delete(client: TestClient) -> None:
    messages = [m.model_dump(mode="json") for m in conversation()]
    draft = client.post(
        "/api/workflows/capture", json={"agent": "data_analyst", "messages": messages}
    )
    assert draft.status_code == 200, draft.text
    assert len(draft.json()["steps"]) == 3

    created = client.post("/api/workflows", json=payload())
    assert created.status_code == 201, created.text
    wf = created.json()
    assert wf["run_count"] == 0 and wf["last_status"] is None

    assert [
        w["id"] for w in client.get("/api/workflows", params={"agent": "data_analyst"}).json()
    ] == [wf["id"]]
    assert client.get("/api/workflows", params={"agent": "rh"}).json() == []

    ran = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {"jeu": DATASET_ID}})
    assert ran.status_code == 200 and ran.json()["status"] == "completed"
    assert len(ran.json()["artifacts"]) == 2
    again = client.get(f"/api/workflows/{wf['id']}").json()
    assert again["run_count"] == 1 and again["last_status"] == "completed" and again["last_run_at"]

    missing = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {}})
    assert missing.status_code == 422 and "Jeu de données" in missing.text

    renamed = client.put(
        f"/api/workflows/{wf['id']}",
        json={k: v for k, v in payload(title="CA hebdo").items() if k != "agent"},
    )
    assert renamed.status_code == 200 and renamed.json()["title"] == "CA hebdo"

    assert client.delete(f"/api/workflows/{wf['id']}").status_code == 204
    assert client.get(f"/api/workflows/{wf['id']}").status_code == 404
    assert client.post(f"/api/workflows/{wf['id']}/run", json={}).status_code == 404


def test_api_rejects_unknown_tools_agents_and_empty_turns(client: TestClient) -> None:
    bad_tool = payload(steps=[{"tool": "github_commit_files", "input": {}}], params=[])
    assert client.post("/api/workflows", json=bad_tool).status_code == 422
    assert client.post("/api/workflows", json=payload(agent="inconnu")).status_code == 404
    empty = [Message.user("Bonjour").model_dump(mode="json")]
    response = client.post("/api/workflows/capture", json={"agent": "assistant", "messages": empty})
    assert response.status_code == 422 and "Aucun appel" in response.text


def test_migration_creates_the_workflows_table(tmp_path: Path) -> None:
    db = tmp_path / "nexus.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workflows)")}
    assert {"agent", "steps", "params", "run_count", "last_status"} <= columns
    command.downgrade(cfg, "0004_attachments")
    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "workflows" not in tables
