"""Claude par l'abonnement (Claude Code, `claude -p`) : protocole, outils, erreurs, sûreté.

Un faux `claude` (tests/fake_claude_cli.py) est lancé en vrai sous-processus.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.experts.general import AssistantAgent
from app.core.config import Settings
from app.core.llm import LLMRouter
from app.core.llm.errors import ProviderRequestError, ProviderUnavailableError
from app.core.llm.providers.claude_code_provider import (
    ClaudeCodeProvider,
    parse_arguments,
    response_schema,
    transcript,
)
from app.core.llm.providers.ollama_provider import OllamaProvider
from app.core.llm.types import (
    LLMRequest,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from app.tools.environment import ToolEnvironment
from tests.winexe import console_exe

FAKE = console_exe(str(Path(__file__).parent / "fake_claude_cli.py"))


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ClaudeCodeProvider:
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ne-doit-pas-servir")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.exemple")
    return ClaudeCodeProvider(binary=FAKE, default_model="sonnet", timeout=10)


def calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


async def test_plain_answer_and_safe_invocation(
    cli: ClaudeCodeProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text")
    response = await cli.complete(
        LLMRequest(messages=[Message.user("Salut")], system="Tu es concis.")
    )
    assert response.text == "Bonjour !" and response.stop_reason == "end_turn"
    assert response.provider == "anthropic" and response.model == "sonnet"
    assert response.usage.input_tokens == 110 and response.usage.output_tokens == 20
    call = calls(tmp_path)[0]
    args = call["args"]
    for flag in (
        "--tools",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--model") + 1] == "sonnet"
    assert "Tu es concis." in args[args.index("--system-prompt") + 1]
    assert call["env"] == {
        "ANTHROPIC_API_KEY": None,
        "ANTHROPIC_BASE_URL": None,
        "ANTHROPIC_AUTH_TOKEN": None,
    }
    assert call["cwd_empty"] and "## Utilisateur\nSalut" in call["stdin"]


async def test_agent_loop_with_tools(
    cli: ClaudeCodeProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La boucle d'agent ordinaire : appel d'outil, exécution par Nexus, réponse finale."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "tool")
    router = LLMRouter(
        {"anthropic": cli, "ollama": OllamaProvider(base_url="http://x", default_model="m")},
        default="anthropic",
    )
    agent = AssistantAgent(router, ToolEnvironment(Settings()))
    question = [Message.user("Quel jour sommes-nous ?")]
    # APPROVAL_MODE=every_step (défaut) : même la lecture de la date attend « Autoriser »
    waiting = await agent.run(question)
    assert waiting.stop_reason == "awaiting_approval"
    (pending,) = waiting.pending_approvals
    assert pending.name == "current_datetime" and pending.kind == "read"
    result = await agent.run([*question, *waiting.new_messages], approvals={pending.id: True})
    assert result.text == "Nous sommes le 20 octobre." and result.iterations == 1
    first, second = calls(tmp_path)
    schema = json.loads(first["args"][first["args"].index("--json-schema") + 1])
    assert (
        "current_datetime"
        in schema["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"]
    )
    assert "`current_datetime`" in first["args"][first["args"].index("--system-prompt") + 1]
    assert "## Assistant → appel de l'outil `current_datetime`" in second["stdin"]
    assert "## Résultat de `current_datetime`" in second["stdin"]


@pytest.mark.parametrize(
    ("mode", "error", "message"),
    [
        ("login", ProviderRequestError, "pas connecté"),
        ("limit", ProviderUnavailableError, "Limite d'utilisation"),
    ],
)
async def test_errors_are_readable(
    cli: ClaudeCodeProvider,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    error: type[Exception],
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(error, match=message):
        await cli.complete(LLMRequest(messages=[Message.user("?")]))


async def test_timeout_and_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with pytest.raises(ProviderUnavailableError, match="n'a pas répondu"):
        await ClaudeCodeProvider(binary=FAKE, timeout=0.5).complete(
            LLMRequest(messages=[Message.user("?")])
        )
    missing = ClaudeCodeProvider(binary=None)
    assert not missing.is_configured
    with pytest.raises(ProviderRequestError, match="introuvable"):
        await missing.complete(LLMRequest(messages=[Message.user("?")]))


async def test_status_checks_login(
    cli: ClaudeCodeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text")
    assert await cli.list_models() == ["sonnet", "opus", "haiku"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "auth_off")
    with pytest.raises(ProviderUnavailableError, match="pas connecté"):
        await cli.list_models()


async def test_stream_emits_text_then_complete(
    cli: ClaudeCodeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text")
    events = [e async for e in cli.stream(LLMRequest(messages=[Message.user("Salut")]))]
    assert [e.type for e in events] == ["text_delta", "response_complete"]


def test_transcript_schema_and_arguments() -> None:
    messages = [
        Message.user("Point projets"),
        Message(
            role="assistant",
            content=[
                TextBlock(text="Je regarde."),
                ToolUseBlock(id="a1", name="projets_dashboard", input={"project_id": 1}),
            ],
        ),
        Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="a1",
                    tool_name="projets_dashboard",
                    content="x" * 50_000,
                    is_error=True,
                )
            ],
        ),
    ]
    text = transcript(messages)
    assert '## Assistant → appel de l\'outil `projets_dashboard` (id a1)\n{"project_id": 1}' in text
    assert (
        "## Résultat de `projets_dashboard` (id a1) — ERREUR" in text
        and "[… résultat tronqué]" in text
    )
    assert response_schema([])["required"] == ["text"]
    tools = [ToolSpec(name="t", description="d", input_schema={"type": "object"})]
    assert response_schema(tools)["required"] == ["text", "tool_calls"]
    assert parse_arguments('{"a": 1}') == {"a": 1} and parse_arguments({"b": 2}) == {"b": 2}
    assert "_arguments_invalides" in parse_arguments("{pas du json")
    assert parse_arguments("") == {}


def test_router_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: FAKE)
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_MODE"):
        monkeypatch.delenv(key, raising=False)
    auto = LLMRouter.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert (
        isinstance(auto.get_provider("anthropic"), ClaudeCodeProvider)
        and auto.default == "anthropic"
    )
    keyed = LLMRouter.from_settings(Settings(_env_file=None, anthropic_api_key="sk-x"))  # type: ignore[call-arg]
    assert not isinstance(keyed.get_provider("anthropic"), ClaudeCodeProvider)
    forced = LLMRouter.from_settings(
        Settings(_env_file=None, anthropic_api_key="sk-x", claude_mode="cli")
    )  # type: ignore[call-arg]
    assert isinstance(forced.get_provider("anthropic"), ClaudeCodeProvider)
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: None)
    nothing = LLMRouter.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert nothing.default == "ollama"
