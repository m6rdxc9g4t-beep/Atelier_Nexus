import pytest

from app.core.config import Settings
from app.core.llm import LLMRouter


def test_empty_env_values_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.anthropic_api_key is None
    assert settings.llm_fallback_provider is None


def test_router_from_settings_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    router = LLMRouter.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    # Sans clé : Ollama répond par défaut (le repli vers lui-même n'a plus de sens)
    assert router.default == "ollama"
    assert router.fallback is None
    assert router.get_provider("ollama").name == "ollama"


def test_router_keeps_claude_by_default_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    router = LLMRouter.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert router.default == "anthropic"
    assert router.fallback == "ollama"
