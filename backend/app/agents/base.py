"""BaseAgent — classe mère de tous les agents Atelier Nexus.

Un agent déclare : un nom, un prompt système et ses outils. La boucle
« modèle → outils → modèle » est commune et passe exclusivement par le
`LLMRouter` : un agent fonctionne donc à l'identique avec Claude ou Ollama.

    @register_agent
    class MonAgent(BaseAgent):
        name = "mon_agent"
        display_name = "Mon agent"
        description = "…"
        system_prompt = "…"

        def default_tools(self) -> list[BaseTool[Any]]:
            return [PublishArtifactTool()]
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm.router import LLMRouter
from app.core.llm.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ProviderName,
    ResponseComplete,
    StopReason,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from app.tools.base import Artifact, BaseTool, ToolContext, ToolOutput

# ─── Résultat & événements ────────────────────────────────────────


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    provider: ProviderName
    model: str
    text: str  # dernière réponse textuelle de l'agent
    stop_reason: StopReason | Literal["max_iterations"]
    iterations: int
    usage: Usage
    artifacts: list[Artifact]
    # Uniquement les messages produits pendant ce tour (à ajouter à l'historique client)
    new_messages: list[Message]


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    id: str
    name: str
    content: str
    is_error: bool


class ArtifactEvent(BaseModel):
    type: Literal["artifact"] = "artifact"
    artifact: Artifact


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    result: AgentResult


AgentEvent = Annotated[
    TextDeltaEvent | ToolCallEvent | ToolResultEvent | ArtifactEvent | DoneEvent,
    Field(discriminator="type"),
]


# ─── Agent ────────────────────────────────────────────────────────


class BaseAgent(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    system_prompt: ClassVar[str]
    max_iterations: ClassVar[int] = 8
    max_tokens: ClassVar[int] = 4096

    def __init__(self, router: LLMRouter, tools: Sequence[BaseTool[Any]] | None = None) -> None:
        self.router = router
        selected = list(tools) if tools is not None else self.default_tools()
        names = [t.name for t in selected]
        if len(names) != len(set(names)):
            raise ValueError(f"{type(self).__name__} : noms d'outils en double {names}")
        self.tools: dict[str, BaseTool[Any]] = {t.name: t for t in selected}

    # Points d'extension ------------------------------------------------

    def default_tools(self) -> list[BaseTool[Any]]:
        """Outils de l'agent. À surcharger : la déclaration doit rester explicite."""
        return []

    def build_system_prompt(self, ctx: ToolContext) -> str:
        return self.system_prompt

    # Exécution ---------------------------------------------------------

    async def run(
        self,
        messages: Sequence[Message],
        *,
        provider: ProviderName | None = None,
        model: str | None = None,
        context: ToolContext | None = None,
    ) -> AgentResult:
        async for event in self.run_stream(
            messages, provider=provider, model=model, context=context
        ):
            if isinstance(event, DoneEvent):
                return event.result
        raise RuntimeError("Le flux de l'agent s'est terminé sans DoneEvent.")

    async def run_stream(
        self,
        messages: Sequence[Message],
        *,
        provider: ProviderName | None = None,
        model: str | None = None,
        context: ToolContext | None = None,
    ) -> AsyncIterator[
        TextDeltaEvent | ToolCallEvent | ToolResultEvent | ArtifactEvent | DoneEvent
    ]:
        if not messages or messages[-1].role != "user":
            raise ValueError("La conversation doit se terminer par un message utilisateur.")
        ctx = context or ToolContext()
        history = list(messages)
        new_messages: list[Message] = []
        artifacts: list[Artifact] = []
        usage = Usage()
        system = self.build_system_prompt(ctx)
        specs = [t.spec() for t in self.tools.values()]
        response: LLMResponse | None = None

        for iteration in range(1, self.max_iterations + 1):
            request = LLMRequest(
                messages=history,
                system=system,
                tools=specs,
                max_tokens=self.max_tokens,
                model=model,
            )
            response = None
            async for chunk in self.router.stream(request, provider=provider):
                if isinstance(chunk, TextDelta):
                    yield TextDeltaEvent(text=chunk.text)
                elif isinstance(chunk, ResponseComplete):
                    response = chunk.response
            if response is None:
                raise RuntimeError("Le provider n'a pas renvoyé de réponse complète.")

            # Repli éventuel du routeur : on reste sur le provider effectivement utilisé
            if response.provider != (provider or self.router.default):
                model = None  # un nom de modèle n'est pas portable entre providers
            provider = response.provider

            usage = usage + response.usage
            assistant_msg = Message(role="assistant", content=response.content)
            history.append(assistant_msg)
            new_messages.append(assistant_msg)

            calls = response.tool_calls
            if response.stop_reason != "tool_use" or not calls:
                yield DoneEvent(
                    result=self._result(
                        response, response.stop_reason, iteration, usage, artifacts, new_messages
                    )
                )
                return

            results: list[ToolResultBlock] = []
            for call in calls:
                yield ToolCallEvent(id=call.id, name=call.name, input=call.input)
                output = await self._execute_tool(call, ctx)
                for artifact in output.artifacts:
                    artifacts.append(artifact)
                    yield ArtifactEvent(artifact=artifact)
                yield ToolResultEvent(
                    id=call.id, name=call.name, content=output.content, is_error=output.is_error
                )
                results.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        tool_name=call.name,
                        content=output.content,
                        is_error=output.is_error,
                    )
                )
            tool_msg = Message(role="user", content=list(results))
            history.append(tool_msg)
            new_messages.append(tool_msg)

        assert response is not None
        yield DoneEvent(
            result=self._result(
                response, "max_iterations", self.max_iterations, usage, artifacts, new_messages
            )
        )

    async def _execute_tool(self, call: ToolUseBlock, ctx: ToolContext) -> ToolOutput:
        tool = self.tools.get(call.name)
        if tool is None:
            available = ", ".join(self.tools) or "aucun"
            return ToolOutput(
                content=f"Outil inconnu « {call.name} ». Outils disponibles : {available}.",
                is_error=True,
            )
        return await tool.invoke(call.input, ctx)

    def _result(
        self,
        response: LLMResponse,
        stop_reason: StopReason | Literal["max_iterations"],
        iterations: int,
        usage: Usage,
        artifacts: list[Artifact],
        new_messages: list[Message],
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            provider=response.provider,
            model=response.model,
            text=response.text,
            stop_reason=stop_reason,
            iterations=iterations,
            usage=usage,
            artifacts=list(artifacts),
            new_messages=list(new_messages),
        )
