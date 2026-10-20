import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.llm import ProviderUnavailableError, get_llm_router
from main import app
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response


@pytest.fixture
def anthropic() -> ScriptedProvider:
    return ScriptedProvider("anthropic")


@pytest.fixture
def client(anthropic: ScriptedProvider) -> Iterator[TestClient]:
    router = make_router(anthropic, ScriptedProvider("ollama", configured=False))
    app.dependency_overrides[get_llm_router] = lambda: router
    yield TestClient(app)
    app.dependency_overrides.clear()


def _body(text: str = "Bonjour", **extra: object) -> dict[str, object]:
    return {"messages": [{"role": "user", "content": [{"type": "text", "text": text}]}], **extra}


def test_list_providers(client: TestClient) -> None:
    data = client.get("/api/llm/providers").json()
    assert {p["name"] for p in data} == {"anthropic", "ollama"}


def test_list_agents(client: TestClient) -> None:
    agents = client.get("/api/agents").json()
    assistant = next(a for a in agents if a["name"] == "assistant")
    assert {t["name"] for t in assistant["tools"]} == {"current_datetime", "publish_artifact"}


def test_run_agent(client: TestClient, anthropic: ScriptedProvider) -> None:
    anthropic.script = [text_response("Salut !")]
    response = client.post("/api/agents/assistant/run", json=_body())
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Salut !"
    assert data["provider"] == "anthropic"


def test_unknown_agent_is_404(client: TestClient) -> None:
    response = client.post("/api/agents/inconnu/run", json=_body())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "agent_not_found"


def test_unconfigured_provider_is_503(client: TestClient) -> None:
    response = client.post("/api/agents/assistant/run", json=_body(provider="ollama"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"


def test_last_message_must_be_user(client: TestClient) -> None:
    body = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "x"}]}]}
    assert client.post("/api/agents/assistant/run", json=body).status_code == 422


def _sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_stream_agent_emits_artifact_and_done(
    client: TestClient, anthropic: ScriptedProvider
) -> None:
    anthropic.script = [
        tool_response("publish_artifact", {"kind": "dax", "title": "CA", "content": "CA = 1"}),
        text_response("Mesure publiée."),
    ]
    with client.stream("POST", "/api/agents/assistant/stream", json=_body()) as response:
        assert response.status_code == 200
        events = _sse(response.read().decode())
    kinds = [kind for kind, _ in events]
    assert kinds[:3] == ["tool_call", "artifact", "tool_result"]
    assert kinds[-1] == "done"
    artifact = next(data for kind, data in events if kind == "artifact")
    assert artifact["artifact"]["kind"] == "dax"  # type: ignore[index]


def test_stream_reports_provider_failure_as_error_event(
    client: TestClient, anthropic: ScriptedProvider
) -> None:
    anthropic.script = [ProviderUnavailableError("down", provider="anthropic")]
    with client.stream("POST", "/api/agents/assistant/stream", json=_body()) as response:
        events = _sse(response.read().decode())
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "provider_unavailable"
