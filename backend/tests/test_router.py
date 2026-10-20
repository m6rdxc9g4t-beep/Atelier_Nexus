import pytest

from app.core.llm import (
    LLMRequest,
    Message,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.core.llm.types import ResponseComplete, TextDelta
from tests.fakes import ScriptedProvider, make_router, text_response

REQUEST = LLMRequest(messages=[Message.user("Bonjour")], model="claude-x")


async def test_uses_default_provider() -> None:
    anthropic = ScriptedProvider("anthropic", [text_response("salut")])
    router = make_router(anthropic)
    response = await router.complete(REQUEST)
    assert response.text == "salut"
    assert response.provider == "anthropic"


async def test_explicit_provider_overrides_default() -> None:
    ollama = ScriptedProvider("ollama", [text_response("local", "ollama")])
    router = make_router(ollama=ollama)
    response = await router.complete(REQUEST, provider="ollama")
    assert response.provider == "ollama"


async def test_unconfigured_provider_raises() -> None:
    router = make_router(ScriptedProvider("anthropic", configured=False))
    with pytest.raises(ProviderNotConfiguredError):
        await router.complete(REQUEST)


async def test_fallback_on_transient_failure_drops_model() -> None:
    anthropic = ScriptedProvider("anthropic", [ProviderUnavailableError("down")])
    ollama = ScriptedProvider("ollama", [text_response("secours", "ollama")])
    router = make_router(anthropic, ollama, fallback="ollama")
    response = await router.complete(REQUEST)
    assert response.provider == "ollama"
    # le nom de modèle Claude ne doit pas être envoyé à Ollama
    assert ollama.requests[0].model is None


async def test_no_fallback_on_request_error() -> None:
    anthropic = ScriptedProvider("anthropic", [ProviderRequestError("400")])
    router = make_router(anthropic, fallback="ollama")
    with pytest.raises(ProviderRequestError):
        await router.complete(REQUEST)


async def test_no_fallback_when_disabled_per_call() -> None:
    anthropic = ScriptedProvider("anthropic", [ProviderUnavailableError("down")])
    router = make_router(anthropic, fallback="ollama")
    with pytest.raises(ProviderUnavailableError):
        await router.complete(REQUEST, allow_fallback=False)


async def test_stream_falls_back_before_first_event() -> None:
    anthropic = ScriptedProvider("anthropic", [ProviderUnavailableError("down")])
    ollama = ScriptedProvider("ollama", [text_response("via ollama", "ollama")])
    router = make_router(anthropic, ollama, fallback="ollama")
    events = [e async for e in router.stream(REQUEST)]
    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], ResponseComplete)
    assert events[-1].response.provider == "ollama"


async def test_status_reports_each_provider() -> None:
    router = make_router(
        ScriptedProvider("anthropic", configured=False),
        ScriptedProvider("ollama", models=["llama3.1:8b"]),
        default="ollama",
    )
    statuses = {s.name: s for s in await router.status()}
    assert statuses["anthropic"].configured is False
    assert statuses["anthropic"].available is False
    assert statuses["ollama"].available is True
    assert statuses["ollama"].is_default is True
    assert statuses["ollama"].models == ["llama3.1:8b"]
