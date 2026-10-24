"""BaseAgent — classe mère de tous les agents Atelier Nexus.

Un agent déclare : son identité (nom, icône, catégorie, exemples), son prompt système et
ses boîtes à outils (`toolsets`). La boucle « modèle → outils → modèle » est commune et
passe exclusivement par le `LLMRouter` : un agent fonctionne à l'identique avec Claude
ou Ollama.

Garde-fous communs :
- **Confidentialité** : un agent `local_only` (déclaré, ou parce qu'il utilise une boîte
  sensible comme Trésorerie) tourne uniquement sur Ollama, sans repli vers Claude.
- **Validation humaine** : en `APPROVAL_MODE=every_step` (défaut, choix de l'utilisateur),
  AUCUN appel d'outil n'est exécuté directement, lectures comprises ; en `writes_only`,
  seulement les outils `requires_approval`. L'agent s'arrête
  (`stop_reason = "awaiting_approval"`), l'interface affiche « Autoriser / Refuser » pour
  chaque appel, puis le client relance le tour avec `approvals`.

    @register_agent
    class MonAgent(BaseAgent):
        name = "mon_agent"
        display_name = "Mon agent"
        description = "…"
        system_prompt = "…"
        toolsets = ("core", "data_via")
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import ApprovalMode
from app.core.llm.attachments import (
    ATTACHMENTS_NOTE,
    AttachmentContent,
    expand_attachments,
    has_attachments,
)
from app.core.llm.errors import ProviderNotAllowedError
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
from app.tools.toolsets import UnavailableToolset, build_tools, is_sensitive

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

Privacy = Literal["standard", "local_only"]
AgentStopReason = StopReason | Literal["max_iterations", "awaiting_approval"]

REFUSED = "L'utilisateur a refusé cette action : ne la relance pas, propose une alternative."

#: Nature d'un appel montrée sur la carte de validation
CallKind = Literal["read", "write", "delegation"]

# ─── Résultat & événements ────────────────────────────────────────


class PendingCall(BaseModel):
    """Appel d'outil en attente de validation."""

    id: str
    name: str
    input: dict[str, Any]
    summary: str
    #: « Lecture », « Écriture » ou « Délégation » sur la carte (anciens tours : écriture)
    kind: CallKind = "write"


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    provider: ProviderName
    model: str
    text: str  # dernière réponse textuelle de l'agent
    stop_reason: AgentStopReason
    iterations: int
    usage: Usage
    artifacts: list[Artifact]
    # Uniquement les messages produits pendant ce tour (à ajouter à l'historique client)
    new_messages: list[Message]
    pending_approvals: list[PendingCall] = Field(default_factory=list)


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


class ApprovalRequiredEvent(BaseModel):
    type: Literal["approval_required"] = "approval_required"
    calls: list[PendingCall]


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    result: AgentResult


AnyAgentEvent = (
    TextDeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | ArtifactEvent
    | ApprovalRequiredEvent
    | DoneEvent
)
AgentEvent = Annotated[AnyAgentEvent, Field(discriminator="type")]


# ─── Agent ────────────────────────────────────────────────────────


class BaseAgent(ABC):
    # Identité (surchargée par les sous-classes ou, pour un agent personnalisé, par instance)
    name: str
    display_name: str
    description: str
    system_prompt: str
    icon: str = "bot"
    category: str = "Général"
    starters: tuple[str, ...] = ()
    source: Literal["builtin", "custom"] = "builtin"

    # Outils et moteur
    toolsets: tuple[str, ...] = ("core",)
    privacy: Privacy = "standard"
    default_provider: ProviderName | None = None
    max_iterations: int = 8
    max_tokens: int = 4096

    def __init__(
        self,
        router: LLMRouter,
        env: ToolEnvironment | None = None,
        *,
        tools: Sequence[BaseTool[Any]] | None = None,
        delegated: bool = False,
        approval_mode: ApprovalMode | None = None,
    ) -> None:
        self.router = router
        self.env = env
        self.delegated = delegated
        # Réglage APPROVAL_MODE de l'installation ; sans environnement, le plus prudent
        self.approval_mode: ApprovalMode = approval_mode or (
            env.settings.approval_mode if env is not None else "every_step"
        )
        self.unavailable: list[UnavailableToolset] = []
        selected = list(tools) if tools is not None else self.default_tools()
        if delegated:
            # Sous-agent d'un orchestrateur : aucune validation ne peut lui être présentée, pas de
            # délégation en chaîne. En `every_step`, même une lecture attend une validation : le
            # sous-agent n'a donc AUCUN outil et répond à partir de la consigne transmise.
            selected = (
                []
                if self.approval_mode == "every_step"
                else [
                    t
                    for t in selected
                    if not t.requires_approval and not t.name.startswith("delegate")
                ]
            )
        names = [t.name for t in selected]
        if len(names) != len(set(names)):
            raise ValueError(f"{type(self).__name__} : noms d'outils en double {names}")
        self.tools: dict[str, BaseTool[Any]] = {t.name: t for t in selected}

    # Points d'extension ------------------------------------------------

    def default_tools(self) -> list[BaseTool[Any]]:
        """Outils issus des boîtes déclarées (`toolsets`). Sans environnement : aucun outil."""
        if self.env is None:
            return []
        ids = list(self.toolsets)
        locked = self.privacy == "local_only" or is_sensitive(ids)
        tools, self.unavailable = build_tools(ids, self.env, local=locked)
        if not locked and any(t.sensitive for t in tools):
            # Un outil sensible dans une boîte qui ne l'est pas verrouille aussi l'agent
            tools, self.unavailable = build_tools(ids, self.env, local=True)
        return tools

    def build_system_prompt(self, ctx: ToolContext) -> str:
        return self.system_prompt + self.unavailable_note() + self.approval_note()

    def approval_note(self) -> str:
        """Prévient le modèle que chaque appel est validé (ou qu'il n'a pas d'outil en délégation)."""
        if self.approval_mode != "every_step":
            return ""
        if self.delegated:
            return (
                "\n\nTu réponds à une sous-tâche confiée par un orchestrateur, sans aucun outil : "
                "chaque action doit être validée par l'utilisateur, ce qui est impossible ici. "
                "Réponds uniquement à partir de la consigne ; si une donnée te manque, dis "
                "précisément laquelle au lieu de l'inventer."
            )
        if not self.tools:
            return ""
        return (
            "\n\nChaque appel d'outil, lecture comprise, est présenté à l'utilisateur, qui "
            "l'autorise ou le refuse avant son exécution : n'appelle que les outils utiles."
        )

    def needs_approval(self, tool: BaseTool[Any]) -> bool:
        """Vrai si cet outil attend « Autoriser » avant de s'exécuter (réglage APPROVAL_MODE)."""
        return tool.requires_approval or self.approval_mode == "every_step"

    def unavailable_note(self) -> str:
        """Prévient le modèle des boîtes écartées, pour qu'il l'explique au lieu d'improviser."""
        if not self.unavailable:
            return ""
        items = "; ".join(f"{u.label} ({u.reason})" for u in self.unavailable)
        return (
            f"\n\nIndisponible dans cette installation : {items}. Si la demande en dépend, "
            "dis-le et indique la variable à renseigner dans backend/.env."
        )

    # Confidentialité ---------------------------------------------------

    @property
    def local_only(self) -> bool:
        return (
            self.privacy == "local_only"
            or is_sensitive(list(self.toolsets))
            or any(t.sensitive for t in self.tools.values())
        )

    def resolve_provider(self, requested: ProviderName | None) -> ProviderName | None:
        if self.local_only:
            if requested == "anthropic":
                raise ProviderNotAllowedError(
                    f"« {self.display_name} » manipule des données qui ne doivent pas quitter la "
                    "machine : il fonctionne uniquement avec le modèle local (Ollama).",
                    provider="anthropic",
                )
            return "ollama"
        return requested or self.default_provider

    # Exécution ---------------------------------------------------------

    async def run(
        self,
        messages: Sequence[Message],
        *,
        provider: ProviderName | None = None,
        model: str | None = None,
        context: ToolContext | None = None,
        approvals: dict[str, bool] | None = None,
        attachments: Mapping[str, AttachmentContent] | None = None,
    ) -> AgentResult:
        async for event in self.run_stream(
            messages,
            provider=provider,
            model=model,
            context=context,
            approvals=approvals,
            attachments=attachments,
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
        approvals: dict[str, bool] | None = None,
        attachments: Mapping[str, AttachmentContent] | None = None,
    ) -> AsyncIterator[AnyAgentEvent]:
        """`attachments` : contenu des pièces jointes citées (id → texte ou image), substitué
        aux références juste avant chaque appel au modèle ; l'historique garde les références."""
        if not messages:
            raise ValueError("La conversation est vide.")
        last = messages[-1]
        resume_calls = [b for b in last.content if isinstance(b, ToolUseBlock)]
        if last.role == "assistant" and not (resume_calls and approvals is not None):
            raise ValueError(
                "La conversation doit se terminer par un message utilisateur, ou par des appels "
                "d'outils accompagnés de leurs validations (approvals)."
            )

        ctx = context or ToolContext()
        provider = self.resolve_provider(provider)
        allow_fallback = not self.local_only
        history = list(messages)
        new_messages: list[Message] = []
        artifacts: list[Artifact] = []
        usage = Usage()
        system = self.build_system_prompt(ctx)
        if has_attachments(history):
            system += ATTACHMENTS_NOTE
        specs = [t.spec() for t in self.tools.values()]
        response: LLMResponse | None = None
        iteration = 0

        # Reprise après validation : exécuter les appels du dernier message assistant
        pending_calls = resume_calls if last.role == "assistant" else []

        while True:
            if pending_calls:
                waiting = self._awaiting(pending_calls, approvals)
                if waiting:
                    yield ApprovalRequiredEvent(calls=waiting)
                    yield DoneEvent(
                        result=self._result(
                            response,
                            provider,
                            "awaiting_approval",
                            iteration,
                            usage,
                            artifacts,
                            new_messages,
                            pending=waiting,
                        )  # fmt: skip
                    )
                    return
                results: list[ToolResultBlock] = []
                for call in pending_calls:
                    yield ToolCallEvent(id=call.id, name=call.name, input=call.input)
                    output = await self._execute_tool(call, ctx, approvals)
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
                approvals = None  # une validation ne vaut que pour les appels présentés
                pending_calls = []

            if iteration >= self.max_iterations:
                yield DoneEvent(
                    result=self._result(
                        response,
                        provider,
                        "max_iterations",
                        iteration,
                        usage,
                        artifacts,
                        new_messages,
                    )
                )
                return
            iteration += 1

            ctx.state["provider"] = provider or self.router.default
            request = LLMRequest(
                messages=expand_attachments(history, attachments),
                system=system,
                tools=specs,
                max_tokens=self.max_tokens,
                model=model,
            )
            response = None
            async for chunk in self.router.stream(
                request, provider=provider, allow_fallback=allow_fallback
            ):
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
                        response,
                        provider,
                        response.stop_reason,
                        iteration,
                        usage,
                        artifacts,
                        new_messages,
                    )
                )
                return
            pending_calls = calls

    # Outils --------------------------------------------------------------

    def _awaiting(
        self, calls: list[ToolUseBlock], approvals: dict[str, bool] | None
    ) -> list[PendingCall]:
        waiting = []
        for call in calls:
            tool = self.tools.get(call.name)
            if (
                tool is not None
                and self.needs_approval(tool)
                and (approvals is None or call.id not in approvals)
            ):
                waiting.append(
                    PendingCall(
                        id=call.id,
                        name=call.name,
                        input=call.input,
                        summary=tool.summarize(call.input),
                        kind=call_kind(tool),
                    )
                )
        return waiting

    async def _execute_tool(
        self, call: ToolUseBlock, ctx: ToolContext, approvals: dict[str, bool] | None
    ) -> ToolOutput:
        tool = self.tools.get(call.name)
        if tool is None:
            available = ", ".join(self.tools) or "aucun"
            return ToolOutput(
                content=f"Outil inconnu « {call.name} ». Outils disponibles : {available}.",
                is_error=True,
            )
        if self.needs_approval(tool) and not (approvals or {}).get(call.id, False):
            return ToolOutput(content=REFUSED, is_error=True)
        return await tool.invoke(call.input, ctx)

    def _result(
        self,
        response: LLMResponse | None,
        provider: ProviderName | None,
        stop_reason: AgentStopReason,
        iterations: int,
        usage: Usage,
        artifacts: list[Artifact],
        new_messages: list[Message],
        *,
        pending: list[PendingCall] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            provider=response.provider if response else (provider or self.router.default),
            model=response.model if response else "",
            text=response.text if response else "",
            stop_reason=stop_reason,
            iterations=iterations,
            usage=usage,
            artifacts=list(artifacts),
            new_messages=list(new_messages),
            pending_approvals=pending or [],
        )


def call_kind(tool: BaseTool[Any]) -> CallKind:
    """Nature d'un appel pour la carte : écriture, délégation à un agent, ou lecture."""
    if tool.requires_approval:
        return "write"
    if tool.name == "delegate_to_agent":
        return "delegation"
    return "read"
