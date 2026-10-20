"""Étape 6 : historique des conversations et de leurs artefacts."""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents import AgentCatalog
from app.api.deps import get_catalog, get_conversation_repository, get_custom_repository
from app.core.llm import get_llm_router
from app.db.conversations import ConversationRepository
from app.db.models import Base
from app.db.repository import CustomAgentRepository, StorageError
from main import app
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker]:  # type: ignore[type-arg]
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def anthropic() -> ScriptedProvider:
    return ScriptedProvider("anthropic")


@pytest.fixture
def client(sessions: async_sessionmaker, anthropic: ScriptedProvider) -> Iterator[TestClient]:  # type: ignore[type-arg]
    router = make_router(anthropic)
    custom = CustomAgentRepository(sessions)
    app.dependency_overrides[get_llm_router] = lambda: router
    app.dependency_overrides[get_custom_repository] = lambda: custom
    app.dependency_overrides[get_catalog] = lambda: AgentCatalog(custom)
    app.dependency_overrides[get_conversation_repository] = lambda: ConversationRepository(sessions)
    yield TestClient(app)
    app.dependency_overrides.clear()


def user(text: str) -> dict[str, object]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_conversation_lifecycle(client: TestClient, anthropic: ScriptedProvider) -> None:
    created = client.post("/api/conversations", json={"agent": "assistant"})
    assert created.status_code == 201
    cid = created.json()["id"]

    anthropic.script = [
        tool_response(
            "publish_artifact",
            {"kind": "markdown", "title": "Plan", "content": "# Plan"},
            call_id="p1",
        ),
        text_response("Le plan est publié."),
    ]
    with client.stream(
        "POST",
        "/api/agents/assistant/stream",
        json={"messages": [user("Fais-moi un plan de lancement")], "conversation_id": cid},
    ) as r:
        events = sse(r.read().decode())
    assert [k for k, _ in events][-2:] == ["done", "saved"]

    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["title"] == "Fais-moi un plan de lancement"
    roles = [m["role"] for m in detail["history"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert detail["artifacts"][0]["title"] == "Plan" and detail["artifacts"][0]["position"] == 4
    assert detail["turn_meta"]["3"]["provider"] == "anthropic"
    # Dates explicitement en UTC (SQLite les rend sans fuseau)
    assert detail["updated_at"].endswith("Z") and detail["artifacts"][0]["created_at"].endswith("Z")

    # Deuxième tour : l'historique s'allonge, le titre ne change pas
    anthropic.script = [text_response("Avec plaisir.")]
    history = [*detail["history"], user("Merci")]
    run = client.post(
        "/api/agents/assistant/run", json={"messages": history, "conversation_id": cid}
    )
    assert run.status_code == 200
    summaries = client.get("/api/conversations", params={"agent": "assistant"}).json()
    assert summaries[0]["id"] == cid
    assert summaries[0]["message_count"] == 6 and summaries[0]["artifact_count"] == 1

    renamed = client.patch(f"/api/conversations/{cid}", json={"title": "Lancement"})
    assert renamed.json()["title"] == "Lancement"
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_pending_approval_is_saved_and_cleared(
    client: TestClient, anthropic: ScriptedProvider
) -> None:
    from app.agents import BaseAgent, register_agent
    from app.tools import BaseTool, ToolContext, ToolInput, ToolOutput

    class In(ToolInput):
        text: str

    class Write(BaseTool[In]):
        name = "write_note"
        description = "écrit"
        input_model = In
        requires_approval = True

        async def run(self, params: In, ctx: ToolContext) -> ToolOutput:
            return ToolOutput(content="écrit")

    @register_agent
    class NoteTaker(BaseAgent):
        name = "note_taker_test"
        display_name = "Notes"
        description = "test"
        system_prompt = "test"

        def default_tools(self) -> list[BaseTool]:  # type: ignore[type-arg]
            return [Write()]

    from app.agents import registry

    try:
        _run_pending_scenario(client, anthropic)
    finally:
        registry._REGISTRY.pop("note_taker_test", None)  # ne pas polluer les autres tests


def _run_pending_scenario(client: TestClient, anthropic: ScriptedProvider) -> None:
    cid = client.post("/api/conversations", json={"agent": "note_taker_test"}).json()["id"]
    anthropic.script = [
        tool_response("write_note", {"text": "x"}, call_id="w1"),
        text_response("Fait."),
    ]
    first = client.post(
        "/api/agents/note_taker_test/run", json={"messages": [user("Note")], "conversation_id": cid}
    ).json()
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["pending_approvals"][0]["id"] == "w1"

    history = [user("Note"), *first["new_messages"]]
    client.post(
        "/api/agents/note_taker_test/run",
        json={"messages": history, "conversation_id": cid, "approvals": {"w1": True}},
    )
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["pending_approvals"] == []
    assert [m["role"] for m in detail["history"]] == ["user", "assistant", "user", "assistant"]


def test_conversation_must_belong_to_the_agent(client: TestClient) -> None:
    cid = client.post("/api/conversations", json={"agent": "assistant"}).json()["id"]
    response = client.post(
        "/api/agents/redacteur/run", json={"messages": [user("?")], "conversation_id": cid}
    )
    assert response.status_code == 409
    missing = client.post(
        "/api/agents/assistant/run", json={"messages": [user("?")], "conversation_id": "inconnue"}
    )
    assert missing.status_code == 404


def test_unknown_agent_cannot_get_a_conversation(client: TestClient) -> None:
    assert client.post("/api/conversations", json={"agent": "fantome"}).status_code == 404


def test_storage_down_does_not_block_the_agent(anthropic: ScriptedProvider) -> None:
    class Broken(ConversationRepository):
        def __init__(self) -> None:
            pass

        async def agent_of(self, conversation_id: str) -> str | None:
            raise StorageError("Base de données indisponible")

    app.dependency_overrides[get_llm_router] = lambda: make_router(anthropic)
    app.dependency_overrides[get_conversation_repository] = lambda: Broken()
    try:
        anthropic.script = [text_response("Réponse quand même.")]
        response = TestClient(app).post(
            "/api/agents/assistant/run", json={"messages": [user("?")], "conversation_id": "x"}
        )
        assert response.status_code == 200 and response.json()["text"] == "Réponse quand même."
    finally:
        app.dependency_overrides.clear()
