"""Providers testés contre les vrais SDK, avec un transport HTTP simulé."""

import json
from typing import Any

import anthropic
import httpx
import httpx2
import ollama
import pytest

from app.core.llm import (
    LLMRequest,
    Message,
    ProviderRequestError,
    ProviderUnavailableError,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from app.core.llm.providers import AnthropicProvider, OllamaProvider
from app.core.llm.providers.anthropic_provider import to_anthropic_messages
from app.core.llm.providers.ollama_provider import to_ollama_messages
from app.core.llm.types import ResponseComplete, TextDelta

TOOL = ToolSpec(
    name="add",
    description="Additionne",
    input_schema={"type": "object", "properties": {"a": {"type": "integer"}}},
)

CONVERSATION = [
    Message.user("2+3 ?"),
    Message(
        role="assistant",
        content=[
            TextBlock(text="Je calcule."),
            ToolUseBlock(id="toolu_1", name="add", input={"a": 2}),
        ],
    ),
    Message(
        role="user",
        content=[
            ToolResultBlock(tool_use_id="toolu_1", tool_name="add", content="boom", is_error=True)
        ],
    ),
]


# ─── Conversions ──────────────────────────────────────────────────


def test_to_anthropic_messages_round_trip_shape() -> None:
    out = to_anthropic_messages(CONVERSATION)
    assert out[1]["content"][1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "add",
        "input": {"a": 2},
    }
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][0]["is_error"] is True


def test_to_ollama_messages_flattens_blocks() -> None:
    out = to_ollama_messages("Système", CONVERSATION)
    assert out[0] == {"role": "system", "content": "Système"}
    assert out[2]["tool_calls"] == [{"function": {"name": "add", "arguments": {"a": 2}}}]
    assert out[3] == {"role": "tool", "tool_name": "add", "content": "[ERREUR] boom"}


# ─── Anthropic ────────────────────────────────────────────────────


def _anthropic(handler: Any) -> AnthropicProvider:
    client = anthropic.AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProvider(api_key="test", default_model="claude-test", client=client)


def test_anthropic_without_key_is_not_configured() -> None:
    assert AnthropicProvider(api_key=None, default_model="m").is_configured is False


async def test_anthropic_complete_parses_tool_use() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [
                    {"type": "text", "text": "Je calcule."},
                    {"type": "tool_use", "id": "toolu_9", "name": "add", "input": {"a": 1}},
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    provider = _anthropic(handler)
    response = await provider.complete(
        LLMRequest(messages=CONVERSATION[:1], system="Sys", tools=[TOOL])
    )
    assert sent["model"] == "claude-test"
    assert sent["system"] == "Sys"
    assert sent["tools"][0]["input_schema"]["type"] == "object"
    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].id == "toolu_9"
    assert response.usage.output_tokens == 7


async def test_anthropic_stream() -> None:
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-test",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "Bon"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "jour"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2}}),
        ("message_stop", {"type": "message_stop"}),
    ]  # fmt: skip
    body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = _anthropic(handler)
    out = [e async for e in provider.stream(LLMRequest(messages=CONVERSATION[:1]))]
    deltas = [e.text for e in out if isinstance(e, TextDelta)]
    assert deltas == ["Bon", "jour"]
    final = out[-1]
    assert isinstance(final, ResponseComplete)
    assert final.response.text == "Bonjour"
    assert final.response.stop_reason == "end_turn"


@pytest.mark.parametrize(
    ("status", "error"),
    [(529, ProviderUnavailableError), (500, ProviderUnavailableError), (400, ProviderRequestError)],
)
async def test_anthropic_error_translation(status: int, error: type[Exception]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "nope"}}
        )

    with pytest.raises(error):
        await _anthropic(handler).complete(LLMRequest(messages=CONVERSATION[:1]))


async def test_anthropic_rejected_key_has_a_readable_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "invalid x-api-key"},
            },
        )

    with pytest.raises(ProviderRequestError, match="Clé API refusée par Anthropic"):
        await _anthropic(handler).list_models()


# ─── Ollama ───────────────────────────────────────────────────────


def _ollama(handler: Any, *, num_ctx: int | None = None) -> OllamaProvider:
    client = ollama.AsyncClient(host="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaProvider(
        base_url="http://ollama.test", default_model="llama-test", num_ctx=num_ctx, client=client
    )


async def test_ollama_complete_generates_tool_call_ids() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "llama-test",
                "created_at": "2026-10-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "add", "arguments": {"a": 4}}}],
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 30,
                "eval_count": 8,
            },
        )

    provider = _ollama(handler)
    response = await provider.complete(LLMRequest(messages=CONVERSATION, tools=[TOOL]))
    assert sent["tools"][0]["function"]["name"] == "add"
    assert sent["options"]["num_predict"] == 4096
    assert response.stop_reason == "tool_use"
    call = response.tool_calls[0]
    assert call.id.startswith("call_") and call.input == {"a": 4}
    assert response.usage.input_tokens == 30


async def test_ollama_stream() -> None:
    lines = [
        {"model": "llama-test", "message": {"role": "assistant", "content": "Sa"}, "done": False},
        {"model": "llama-test", "message": {"role": "assistant", "content": "lut"}, "done": False},
        {
            "model": "llama-test",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "length",
            "prompt_eval_count": 3,
            "eval_count": 2,
        },
    ]
    body = "\n".join(json.dumps(line) for line in lines)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    out = [e async for e in _ollama(handler).stream(LLMRequest(messages=CONVERSATION[:1]))]
    assert [e.text for e in out if isinstance(e, TextDelta)] == ["Sa", "lut"]
    final = out[-1]
    assert isinstance(final, ResponseComplete)
    assert final.response.text == "Salut"
    assert final.response.stop_reason == "max_tokens"


async def test_ollama_unreachable_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError):
        await _ollama(handler).complete(LLMRequest(messages=CONVERSATION[:1]))


async def test_ollama_missing_model_suggests_pull() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'llama-test' not found"})

    with pytest.raises(ProviderRequestError, match="ollama pull llama-test"):
        await _ollama(handler).complete(LLMRequest(messages=CONVERSATION[:1]))


def _ollama_echo(sent: list[dict[str, Any]]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "llama-test",
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
            },
        )

    return handler


async def test_ollama_context_window_is_requested_when_configured() -> None:
    """OLLAMA_NUM_CTX : sans fenêtre demandée, Ollama tronque en silence le début des longues
    conversations outillées (consignes, résultats d'outils) ; 0 ou vide = celle du serveur."""
    sent: list[dict[str, Any]] = []
    provider = _ollama(_ollama_echo(sent), num_ctx=16384)
    await provider.complete(LLMRequest(messages=CONVERSATION, tools=[TOOL]))
    await provider.complete(LLMRequest(messages=CONVERSATION[:1], max_tokens=512))
    assert [s["options"] for s in sent] == [
        {"num_predict": 4096, "num_ctx": 16384},
        {"num_predict": 512, "num_ctx": 16384},  # toujours la même fenêtre : pas de rechargement
    ]

    sent.clear()
    for value in (None, 0):
        await _ollama(_ollama_echo(sent), num_ctx=value).complete(
            LLMRequest(messages=CONVERSATION[:1])
        )
    assert [s["options"] for s in sent] == [{"num_predict": 4096}] * 2


async def test_ollama_stream_sends_the_same_context_window() -> None:
    sent: list[dict[str, Any]] = []
    out = [
        e
        async for e in _ollama(_ollama_echo(sent), num_ctx=8192).stream(
            LLMRequest(messages=CONVERSATION[:1])
        )
    ]
    assert isinstance(out[-1], ResponseComplete)
    assert sent[0]["options"] == {"num_predict": 4096, "num_ctx": 8192}


def test_ollama_num_ctx_setting_has_a_reasonable_default() -> None:
    from app.core.config import Settings

    assert Settings(_env_file=None).ollama_num_ctx == 8192  # type: ignore[call-arg]
    blank = Settings(_env_file=None, ollama_num_ctx="")  # type: ignore[call-arg]
    assert blank.ollama_num_ctx is None  # « OLLAMA_NUM_CTX= » : fenêtre du serveur
    assert Settings(_env_file=None, ollama_num_ctx=0).ollama_num_ctx == 0  # type: ignore[call-arg]
    for wrong in (-1, 1000):  # 1000 : consignes et outils d'un agent local ne tiennent plus
        with pytest.raises(ValueError):
            Settings(_env_file=None, ollama_num_ctx=wrong)  # type: ignore[call-arg]


def test_ollama_num_ctx_is_editable_and_checked_in_settings() -> None:
    from app.core.config import Settings
    from app.core.settings_editor import BY_KEY, SettingsError, SettingsUpdate, validate_changes

    assert BY_KEY["OLLAMA_NUM_CTX"].group == "Modèles"
    current = Settings(_env_file=None)  # type: ignore[call-arg]
    for value, saved in (("16384", "16384"), ("0", "0"), ("", None)):
        update = SettingsUpdate(values={"OLLAMA_NUM_CTX": value})
        assert validate_changes(update, current) == {"OLLAMA_NUM_CTX": saved}
    for wrong in ("beaucoup", "-5", "1024", "999999"):
        with pytest.raises(SettingsError) as refused:
            validate_changes(SettingsUpdate(values={"OLLAMA_NUM_CTX": wrong}), current)
        assert "OLLAMA_NUM_CTX" in refused.value.fields


def test_router_passes_the_ollama_context_window() -> None:
    """OLLAMA_NUM_CTX arrive jusqu'au fournisseur construit par le routeur (sinon Ollama garde
    sa petite fenêtre par défaut et tronque les consignes des agents locaux)."""
    from app.core.config import Settings
    from app.core.llm.router import LLMRouter

    def ollama_of(settings: Settings) -> OllamaProvider:
        provider = LLMRouter.from_settings(settings)._providers["ollama"]
        assert isinstance(provider, OllamaProvider)
        return provider

    assert ollama_of(Settings(_env_file=None, ollama_num_ctx=16384)).num_ctx == 16384  # type: ignore[call-arg]
    assert ollama_of(Settings(_env_file=None, ollama_num_ctx="")).num_ctx is None  # type: ignore[call-arg]
