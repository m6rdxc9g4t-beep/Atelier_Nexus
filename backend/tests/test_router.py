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


class CountingProvider(ScriptedProvider):
    """Compte les sondes (`list_models` : `claude auth status`, `models.list`, `ollama list`)."""

    probes = 0
    down = False

    async def list_models(self) -> list[str]:
        self.probes += 1
        if self.down:
            raise ProviderUnavailableError("arrêté", provider=self.name)
        return self.models


async def test_status_is_cached() -> None:
    """L'interface relit l'état toutes les 30 s : les moteurs ne sont sondés qu'une fois par
    minute, une vérification demandée (`refresh`) au plus toutes les 10 s."""
    claude, local = CountingProvider("anthropic"), CountingProvider("ollama")
    router = make_router(claude, local)
    clock = [100.0]
    router._clock = lambda: clock[0]
    first = await router.status()
    assert await router.status() is first and (claude.probes, local.probes) == (1, 1)
    clock[0] += 5
    assert await router.status(refresh=True) is first  # trop tôt : rien n'est relancé
    clock[0] += 10
    await router.status(refresh=True)
    assert (claude.probes, local.probes) == (2, 2)
    clock[0] += 59
    await router.status()
    assert claude.probes == 2
    clock[0] += 2
    await router.status()
    assert claude.probes == 3


async def test_an_unavailable_engine_is_probed_again_sooner() -> None:
    """Ollama qu'on vient de lancer n'attend pas une minute pour être vu."""
    local = CountingProvider("ollama")
    local.down = True
    router = make_router(CountingProvider("anthropic"), local)
    clock = [100.0]
    router._clock = lambda: clock[0]
    assert {s.name: s.available for s in await router.status()} == {
        "anthropic": True,
        "ollama": False,
    }
    local.down = False
    clock[0] += 11
    assert all(s.available for s in await router.status())
    assert local.probes == 2
