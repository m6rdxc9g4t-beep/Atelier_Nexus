"""Mode pas à pas : pause après chaque résultat d'outil, avant que le modèle ne l'interprète.

Continuer, corriger (consigne jointe aux résultats), arrêter (sans appel au modèle) ; API et
enregistrement de la conversation. Aucun réseau ni modèle réel.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents import (
    AgentCatalog,
    ApprovalRequiredEvent,
    DoneEvent,
    ReviewRequiredEvent,
)
from app.agents.base import STOPPED, is_review_point
from app.api.deps import get_catalog, get_conversation_repository, get_custom_repository
from app.core.llm import Message, get_llm_router
from app.core.llm.types import TextBlock, ToolResultBlock
from app.db.conversations import ConversationRepository
from app.db.models import Base
from app.db.repository import CustomAgentRepository
from main import app
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response
from tests.test_approval_mode import HelperAgent, SaveTool, WeatherTool


def helper(router: Any, mode: str = "every_step") -> HelperAgent:
    return HelperAgent(router, tools=[WeatherTool(), SaveTool()], approval_mode=mode)  # type: ignore[arg-type]


async def events(agent: HelperAgent, messages: list[Message], **kw: Any) -> list[Any]:
    return [e async for e in agent.run_stream(messages, **kw)]


def done(evts: list[Any]) -> Any:
    return next(e for e in evts if isinstance(e, DoneEvent)).result


# ─── Boucle d'agent ───────────────────────────────────────────────


async def test_pause_after_each_result_before_the_model_reads_it() -> None:
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response("weather", {"city": "Rennes"}, text="Je regarde la météo."),
            text_response("Il fait 18 °C à Rennes."),
        ],
    )
    agent = helper(make_router(anthropic))
    history = [Message.user("Météo à Rennes ?")]

    # 1. L'appel attend « Autoriser »
    first = done(await events(agent, history, review_results=True))
    assert first.stop_reason == "awaiting_approval"
    history += first.new_messages
    call_id = first.pending_approvals[0].id

    # 2. Autorisé : l'outil s'exécute, puis PAUSE (le modèle n'a pas encore lu le résultat)
    evts = await events(agent, history, approvals={call_id: True}, review_results=True)
    review = next(e for e in evts if isinstance(e, ReviewRequiredEvent))
    second = done(evts)
    assert review.call_ids == [call_id]
    assert second.stop_reason == "awaiting_review"
    assert len(anthropic.requests) == 1  # un seul appel au modèle jusqu'ici
    history += second.new_messages
    assert is_review_point(history[-1])

    # 3. Continuer : le modèle interprète le résultat
    third = done(await events(agent, history, review_results=True, review="continue"))
    assert third.stop_reason == "end_turn" and third.text == "Il fait 18 °C à Rennes."
    assert len(anthropic.requests) == 2


async def test_correction_is_joined_to_the_results_and_read_by_the_model() -> None:
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response("weather", {"city": "Rennes"}),
            text_response("En degrés Fahrenheit : 64 °F."),
        ],
    )
    agent = helper(make_router(anthropic), mode="writes_only")  # lecture directe, revue quand même
    history = [Message.user("Météo à Rennes ?")]
    paused = done(await events(agent, history, review_results=True))
    assert paused.stop_reason == "awaiting_review"
    history += paused.new_messages

    # Correction : consigne de l'utilisateur jointe aux résultats, puis on continue
    results = history[-1]
    history[-1] = Message(
        role="user",
        content=[*results.content, TextBlock(text="Consigne : donne-la en Fahrenheit.")],
    )
    final = done(await events(agent, history, review_results=True, review="continue"))
    assert final.text.startswith("En degrés Fahrenheit")
    sent = anthropic.requests[-1].messages[-1]
    assert any(isinstance(b, ToolResultBlock) for b in sent.content)
    assert sent.content[-1].text == "Consigne : donne-la en Fahrenheit."  # type: ignore[union-attr]


async def test_stop_ends_the_turn_without_calling_the_model() -> None:
    anthropic = ScriptedProvider("anthropic", [tool_response("weather", {"city": "Rennes"})])
    agent = helper(make_router(anthropic), mode="writes_only")
    history = [Message.user("Météo ?")]
    paused = done(await events(agent, history, review_results=True))
    history += paused.new_messages

    stopped = done(await events(agent, history, review_results=True, review="stop"))
    assert stopped.stop_reason == "stopped_by_user" and stopped.text == STOPPED
    assert [m.role for m in stopped.new_messages] == ["assistant"]
    assert len(anthropic.requests) == 1  # aucun nouvel appel


async def test_refused_calls_do_not_pause_the_model_proposes_an_alternative() -> None:
    anthropic = ScriptedProvider(
        "anthropic",
        [tool_response("save_note", {"text": "x"}), text_response("Je n'enregistre rien.")],
    )
    agent = helper(make_router(anthropic))
    history = [Message.user("Note x")]
    first = done(await events(agent, history, review_results=True))
    history += first.new_messages
    evts = await events(
        agent, history, approvals={first.pending_approvals[0].id: False}, review_results=True
    )
    assert not any(isinstance(e, ReviewRequiredEvent) for e in evts)
    assert done(evts).stop_reason == "end_turn"


async def test_without_review_results_nothing_changes() -> None:
    anthropic = ScriptedProvider(
        "anthropic", [tool_response("weather", {"city": "Brest"}), text_response("Il pleut.")]
    )
    agent = helper(make_router(anthropic), mode="writes_only")
    result = done(await events(agent, [Message.user("Météo ?")]))
    assert result.stop_reason == "end_turn" and result.text == "Il pleut."


async def test_review_requires_a_review_point() -> None:
    agent = helper(make_router())
    with pytest.raises(ValueError, match="Rien à revoir"):
        await events(agent, [Message.user("Bonjour")], review="stop")


async def test_approval_still_comes_before_execution_in_step_mode() -> None:
    anthropic = ScriptedProvider("anthropic", [tool_response("save_note", {"text": "x"})])
    tool = SaveTool()
    agent = HelperAgent(
        make_router(anthropic), tools=[WeatherTool(), tool], approval_mode="every_step"
    )
    evts = await events(agent, [Message.user("Note x")], review_results=True)
    assert any(isinstance(e, ApprovalRequiredEvent) for e in evts) and not tool.saved


# ─── API et historique ────────────────────────────────────────────


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


def user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def test_api_pause_review_and_saved_history(
    client: TestClient, anthropic: ScriptedProvider
) -> None:
    anthropic.script = [
        tool_response("current_datetime", {}, call_id="t1"),
        text_response("Nous sommes jeudi."),
    ]
    conv = client.post("/api/conversations", json={"agent": "assistant"}).json()["id"]
    history = [user("Quel jour sommes-nous ?")]
    body = {"messages": history, "conversation_id": conv, "review_results": True}

    asked = client.post("/api/agents/assistant/run", json=body).json()
    assert asked["stop_reason"] == "awaiting_approval"
    history += asked["new_messages"]

    paused = client.post(
        "/api/agents/assistant/run", json={**body, "messages": history, "approvals": {"t1": True}}
    ).json()
    assert paused["stop_reason"] == "awaiting_review"
    history += paused["new_messages"]
    saved = client.get(f"/api/conversations/{conv}").json()
    assert saved["history"][-1]["content"][0]["type"] == "tool_result"  # pause enregistrée

    final = client.post(
        "/api/agents/assistant/run", json={**body, "messages": history, "review": "continue"}
    ).json()
    assert final["text"] == "Nous sommes jeudi."


def test_api_rejects_review_without_results(client: TestClient) -> None:
    response = client.post(
        "/api/agents/assistant/run", json={"messages": [user("Bonjour")], "review": "stop"}
    )
    assert response.status_code == 422
