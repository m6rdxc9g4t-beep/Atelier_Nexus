"""Provider Ollama (modèles locaux) — seul module autorisé à importer le SDK `ollama`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import httpx
import ollama

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
from app.core.net import use_env_proxy

# ─── Conversions neutre ⇄ Ollama (fonctions pures, testées) ───────


def to_ollama_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema,
        },
    }


def to_ollama_messages(system: str | None, messages: list[Message]) -> list[dict[str, Any]]:
    """Ollama n'a pas de blocs : un message `user` porteur de résultats d'outils
    est éclaté en messages `tool` (un par résultat), suivis du texte éventuel."""
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text}
            calls = [b for b in m.content if isinstance(b, ToolUseBlock)]
            if calls:
                msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.input}} for c in calls
                ]
            out.append(msg)
            continue
        images: list[str] = []
        for block in m.content:
            if isinstance(block, ToolResultBlock):
                content = f"[ERREUR] {block.content}" if block.is_error else block.content
                out.append({"role": "tool", "tool_name": block.tool_name, "content": content})
            elif isinstance(block, ImageBlock):
                images.append(block.data)
            elif isinstance(block, AttachmentBlock):
                images_note = f"[Pièce jointe « {block.name} » non chargée.]"
                out.append({"role": "user", "content": images_note})
        if m.text or images:
            user: dict[str, Any] = {"role": "user", "content": m.text}
            if images:
                user["images"] = images  # modèle de vision requis (gemma3, qwen2.5vl, llava…)
            out.append(user)
    return out


def _new_call_id() -> str:
    # Ollama n'identifie pas les appels d'outils : on génère des ids stables côté hub.
    return f"call_{uuid.uuid4().hex[:16]}"


def _build_response(
    *,
    model: str,
    text: str,
    tool_calls: list[ToolUseBlock],
    done_reason: str | None,
    usage: Usage,
) -> LLMResponse:
    content: list[ContentBlock] = []
    if text:
        content.append(TextBlock(text=text))
    content.extend(tool_calls)
    stop: StopReason
    if tool_calls:
        stop = "tool_use"
    elif done_reason == "length":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    return LLMResponse(
        provider="ollama", model=model, content=content, stop_reason=stop, usage=usage
    )


def _tool_uses(calls: Sequence[ollama.Message.ToolCall] | None) -> list[ToolUseBlock]:
    return [
        ToolUseBlock(id=_new_call_id(), name=c.function.name, input=dict(c.function.arguments))
        for c in calls or []
    ]


def from_ollama_response(response: ollama.ChatResponse, model: str) -> LLMResponse:
    return _build_response(
        model=response.model or model,
        text=response.message.content or "",
        tool_calls=_tool_uses(response.message.tool_calls),
        done_reason=response.done_reason,
        usage=Usage(
            input_tokens=response.prompt_eval_count or 0,
            output_tokens=response.eval_count or 0,
        ),
    )


# ─── Provider ─────────────────────────────────────────────────────


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        timeout: float = 300.0,
        client: ollama.AsyncClient | None = None,
    ) -> None:
        super().__init__(default_model)
        self.base_url = base_url
        self._client = client or ollama.AsyncClient(
            host=base_url,
            timeout=timeout,
            trust_env=use_env_proxy(base_url),  # Ollama local : jamais via le proxy système
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    @contextmanager
    def _translate_errors(self, model: str) -> Iterator[None]:
        try:
            yield
        except (ConnectionError, httpx.TransportError) as exc:
            raise ProviderUnavailableError(
                f"Ollama injoignable sur {self.base_url} : {exc}", provider=self.name
            ) from exc
        except ollama.ResponseError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailableError(f"Ollama : {exc.error}", provider=self.name) from exc
            if "image" in (exc.error or "").lower() or "vision" in (exc.error or "").lower():
                raise ProviderRequestError(
                    f"Le modèle local « {model} » ne lit pas les images. Installez un modèle de "
                    "vision (par exemple : ollama pull gemma3) et choisissez-le dans les Réglages, "
                    "ou retirez l'image.",
                    provider=self.name,
                ) from exc
            hint = f" (essayer : ollama pull {model})" if exc.status_code == 404 else ""
            raise ProviderRequestError(f"Ollama : {exc.error}{hint}", provider=self.name) from exc

    def _params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.resolve_model(request),
            "messages": to_ollama_messages(request.system, request.messages),
            "options": {"num_predict": request.max_tokens},
        }
        if request.tools:
            params["tools"] = [to_ollama_tool(t) for t in request.tools]
        return params

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.resolve_model(request)
        with self._translate_errors(model):
            response = await self._client.chat(**self._params(request), stream=False)
        return from_ollama_response(response, model)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        model = self.resolve_model(request)
        text_parts: list[str] = []
        tool_calls: list[ToolUseBlock] = []
        done_reason: str | None = None
        usage = Usage()
        with self._translate_errors(model):
            chunks = await self._client.chat(**self._params(request), stream=True)
            async for chunk in chunks:
                if chunk.message.content:
                    text_parts.append(chunk.message.content)
                    yield TextDelta(text=chunk.message.content)
                tool_calls.extend(_tool_uses(chunk.message.tool_calls))
                if chunk.done:
                    done_reason = chunk.done_reason
                    usage = Usage(
                        input_tokens=chunk.prompt_eval_count or 0,
                        output_tokens=chunk.eval_count or 0,
                    )
        yield ResponseComplete(
            response=_build_response(
                model=model,
                text="".join(text_parts),
                tool_calls=tool_calls,
                done_reason=done_reason,
                usage=usage,
            )
        )

    async def list_models(self) -> list[str]:
        with self._translate_errors(self.default_model):
            listing = await self._client.list()
        return [m.model for m in listing.models if m.model]
