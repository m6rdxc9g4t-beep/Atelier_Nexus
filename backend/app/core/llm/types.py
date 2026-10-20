"""Format de conversation neutre, commun à tous les fournisseurs LLM.

Les agents et l'API ne manipulent QUE ces types. Chaque provider les convertit
vers le format natif (Anthropic Messages API, Ollama chat) et inversement.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["anthropic", "ollama"]

StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─── Blocs de contenu ─────────────────────────────────────────────


class TextBlock(_Strict):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(_Strict):
    """Demande d'appel d'outil émise par le modèle."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(_Strict):
    """Résultat d'un outil, renvoyé au modèle dans un message `user`."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    tool_name: str  # requis par Ollama, qui n'identifie pas les appels
    content: str
    is_error: bool = False


ContentBlock = Annotated[TextBlock | ToolUseBlock | ToolResultBlock, Field(discriminator="type")]


class Message(_Strict):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role="assistant", content=[TextBlock(text=text)])

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


# ─── Outils ───────────────────────────────────────────────────────


class ToolSpec(_Strict):
    """Déclaration d'outil portable : JSON Schema accepté par Anthropic ET Ollama."""

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str
    input_schema: dict[str, Any]


# ─── Requête / réponse ────────────────────────────────────────────


class LLMRequest(_Strict):
    messages: list[Message] = Field(min_length=1)
    system: str | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    max_tokens: int = Field(default=4096, gt=0)
    # Modèle propre au provider ciblé ; None = modèle par défaut du provider
    model: str | None = None


class Usage(_Strict):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class LLMResponse(_Strict):
    provider: ProviderName
    model: str
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


# ─── Streaming ────────────────────────────────────────────────────


class TextDelta(_Strict):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ResponseComplete(_Strict):
    """Dernier événement d'un stream : la réponse complète, outils inclus."""

    type: Literal["response_complete"] = "response_complete"
    response: LLMResponse


LLMStreamEvent = Annotated[TextDelta | ResponseComplete, Field(discriminator="type")]
