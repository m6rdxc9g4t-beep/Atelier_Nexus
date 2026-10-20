"""Provider Anthropic (Claude) — seul module autorisé à importer le SDK `anthropic`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import anthropic
from anthropic.types import Message as AnthropicMessage

from app.core.llm.errors import ProviderRequestError, ProviderUnavailableError
from app.core.llm.providers.base import LLMProvider
from app.core.llm.types import (
    AttachmentBlock,
    ContentBlock,
    ImageBlock,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    Message,
    ResponseComplete,
    StopReason,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
    "refusal": "refusal",
}

# Pannes transitoires → repli possible vers un autre provider
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,  # inclut APITimeoutError
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
    anthropic.ServiceUnavailableError,
)


# ─── Conversions neutre ⇄ Anthropic (fonctions pures, testées) ────


def to_anthropic_tool(spec: ToolSpec) -> dict[str, Any]:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}


def _to_anthropic_block(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, ImageBlock):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
        }
    if isinstance(block, AttachmentBlock):
        # Normalement remplacée en amont (expand_attachments) : jamais de référence brute au modèle
        return {"type": "text", "text": f"[Pièce jointe « {block.name} » non chargée.]"}
    raise TypeError(f"Bloc non supporté : {type(block).__name__}")


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    return [
        {"role": m.role, "content": [_to_anthropic_block(b) for b in m.content]} for m in messages
    ]


def from_anthropic_message(message: AnthropicMessage) -> LLMResponse:
    content: list[ContentBlock] = []
    for block in message.content:
        if block.type == "text":
            content.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            content.append(ToolUseBlock(id=block.id, name=block.name, input=dict(block.input)))
        # Les autres blocs (thinking, outils serveur…) ne sont pas exposés aux agents.
    return LLMResponse(
        provider="anthropic",
        model=message.model,
        content=content,
        stop_reason=_STOP_REASONS.get(message.stop_reason or "", "other"),
        usage=Usage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        ),
    )


# ─── Provider ─────────────────────────────────────────────────────


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        default_model: str,
        timeout: float = 120.0,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(default_model)
        if client is not None:
            self._client: anthropic.AsyncAnthropic | None = client
        elif api_key:
            self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        else:
            self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _require_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            raise ProviderRequestError("ANTHROPIC_API_KEY n'est pas défini.", provider=self.name)
        return self._client

    def _params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.resolve_model(request),
            "max_tokens": request.max_tokens,
            "messages": to_anthropic_messages(request.messages),
        }
        if request.system:
            params["system"] = request.system
        if request.tools:
            params["tools"] = [to_anthropic_tool(t) for t in request.tools]
        return params

    @contextmanager
    def _translate_errors(self) -> Iterator[None]:
        try:
            yield
        except _TRANSIENT_ERRORS as exc:
            raise ProviderUnavailableError(
                f"Anthropic indisponible : {exc}", provider=self.name
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderRequestError(
                "Clé API refusée par Anthropic (401) : vérifiez-la dans les Réglages.",
                provider=self.name,
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderRequestError(
                "Accès refusé par Anthropic (403) : la clé n'a pas les droits nécessaires.",
                provider=self.name,
            ) from exc
        except anthropic.APIError as exc:
            raise ProviderRequestError(
                f"Requête Anthropic refusée : {exc}", provider=self.name
            ) from exc

    async def complete(self, request: LLMRequest) -> LLMResponse:
        client = self._require_client()
        with self._translate_errors():
            message = await client.messages.create(**self._params(request))
        return from_anthropic_message(message)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        client = self._require_client()
        with self._translate_errors():
            async with client.messages.stream(**self._params(request)) as stream:
                async for event in stream:
                    if event.type == "text" and event.text:
                        yield TextDelta(text=event.text)
                final = await stream.get_final_message()
        yield ResponseComplete(response=from_anthropic_message(final))

    async def list_models(self) -> list[str]:
        client = self._require_client()
        with self._translate_errors():
            page = await client.models.list(limit=100)
        return [m.id for m in page.data]
