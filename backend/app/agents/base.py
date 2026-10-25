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
  chaque appel, puis le client relance le tour avec `approvals`. Chaque reprise est une
  nouvelle requête : le contexte des outils (`ctx.state`) est reconstruit d'après l'historique
  (`BaseTool.restore`), et le nombre d'étapes compte tout le tour.
- **Conversation verrouillée** : une réponse d'un agent 100 % local (délégation, réponse
  partielle comprise) présente dans l'historique impose Ollama, sans repli, pour toute la suite
  de la conversation.

    @register_agent
    class MonAgent(BaseAgent):
        name = "mon_agent"
        display_name = "Mon agent"
        description = "…"
        system_prompt = "…"
        toolsets = ("core", "data_via")
"""

from __future__ import annotations

import json
from abc import ABC
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import ApprovalMode
from app.core.llm.attachments import (
    ATTACHMENTS_NOTE,
    AttachmentContent,
    expand_attachments,
    has_attachments,
)
from app.core.llm.errors import ProviderNotAllowedError, ProviderNotConfiguredError
from app.core.llm.router import LLMRouter
from app.core.llm.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ProviderName,
    ResponseComplete,
    StopReason,
    TextBlock,
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

#: Outil de délégation (app/agents/delegation.py) : carte « Délégation », verrou local
DELEGATE_TOOL = "delegate_to_agent"

#: Clés de `ToolContext.state` tenues par la boucle (lues par la délégation)
STATE_PROVIDER = "provider"  # moteur réellement utilisé : posé avant la reprise, suivi après repli
STATE_MODEL = "model"  # modèle demandé ; None après un repli (nom non portable)
STATE_LOCAL_LOCK = "local_lock"  # conversation verrouillée sur le modèle local
STATE_USAGE = "usage"  # jetons consommés par les outils (sous-agents), ajoutés à ceux du tour
STATE_FALLBACK = "fallback"  # moteur de repli possible du prochain appel (None : aucun)

#: Introduit la réponse partielle d'un sous-agent arrêté avant la fin (résultat en erreur) : venue
#: d'un agent 100 % local, elle verrouille la conversation comme une réponse complète
PARTIAL_ANSWER = "Réponse partielle :"

#: Ajouté au prompt du dernier appel quand le nombre d'étapes maximal est atteint
LIMIT_NOTE = (
    "\n\nNombre d'étapes maximal atteint pour ce tour : n'appelle plus aucun outil. Fais la "
    "synthèse de ce qui a été obtenu, puis dis ce qui reste à faire et comment le reprendre."
)
LIMIT_FALLBACK = (
    "Nombre d'étapes maximal atteint pour ce tour : la tâche n'est pas terminée. Relancez-moi "
    "avec une demande plus ciblée pour la poursuivre."
)

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
    # Étapes (appels au modèle) depuis le dernier message de l'utilisateur, reprises après
    # validation comprises ; la synthèse au plafond (`max_iterations`) n'en ajoute pas
    iterations: int
    # Jetons de ce tour (ceux des sous-agents compris)
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
        tools, self.unavailable = build_tools(list(self.toolsets), self.env)
        return tools

    def build_system_prompt(self, ctx: ToolContext) -> str:
        return self.system_prompt + self.unavailable_note() + self.approval_note()

    def approval_note(self) -> str:
        """Prévient le modèle que chaque appel est validé (ou qu'il n'a pas d'outil en délégation)."""
        if self.approval_mode != "every_step":
            return ""
        if self.delegated:
            # Les règles communes citent `publish_artifact` et `current_datetime` : sans outil, le
            # livrable revient en texte et c'est l'orchestrateur qui le publie
            return (
                "\n\nTu réponds à une sous-tâche confiée par un orchestrateur, sans aucun outil : "
                "chaque action doit être validée par l'utilisateur, ce qui est impossible ici. "
                "N'appelle aucun outil : les consignes qui citent `publish_artifact` ou "
                "`current_datetime` ne s'appliquent pas. Rends le livrable COMPLET dans ta "
                "réponse (Markdown), sans le résumer : l'orchestrateur le publiera. Réponds "
                "uniquement à partir de la consigne ; si une donnée te manque (la date du jour "
                "comprise), dis précisément laquelle au lieu de l'inventer."
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
        if not self.unavailable or (self.delegated and self.approval_mode == "every_step"):
            return ""  # sous-agent sans aucun outil : la note n'a pas d'objet
        # Une ligne par boîte : un libellé contient déjà des parenthèses (« Data Via (Atelier
        # Viz) ») et une raison peut contenir « ; » (clés à renseigner à deux endroits)
        items = "\n".join(f"- {u.label} : {u.reason}" for u in self.unavailable)
        return (
            f"\n\nIndisponible dans cette installation :\n{items}\nSi la demande en dépend, "
            "dis-le et reprends l'indication de la ligne (quoi renseigner, et où) ; "
            "n'invente aucun autre nom de réglage, chemin ou commande."
        )

    # Confidentialité ---------------------------------------------------

    @property
    def local_only(self) -> bool:
        return (
            self.privacy == "local_only"
            or is_sensitive(list(self.toolsets))
            or any(t.sensitive for t in self.tools.values())
        )

    def privacy_lock(self, history: Sequence[Message] = (), *, forced: bool = False) -> str | None:
        """Raison du verrou sur le modèle local, ou None.

        Verrouillé : un agent `local_only` ; une conversation dont l'historique contient la
        réponse d'un agent 100 % local (délégation réussie : la renvoyer à Claude la ferait
        sortir de la machine) ; un sous-agent d'une conversation verrouillée (`forced`)."""
        if self.local_only:
            return (
                f"« {self.display_name} » manipule des données qui ne doivent pas quitter la "
                "machine : il fonctionne uniquement avec le modèle local (Ollama)."
            )
        source = self._local_answer(history)
        if source is not None:
            return (
                f"Cette conversation contient une réponse de {source} : elle se poursuit "
                "uniquement avec le modèle local (Ollama)."
            )
        if forced:
            return "Sous-tâche d'une conversation 100 % locale : modèle local (Ollama) uniquement."
        return None

    def resolve_provider(
        self,
        requested: ProviderName | None,
        history: Sequence[Message] = (),
        *,
        forced: bool = False,
    ) -> ProviderName | None:
        """Moteur du tour ; ProviderNotAllowedError (403) si Claude est demandé malgré un verrou."""
        lock = self.privacy_lock(history, forced=forced)
        if lock is not None:
            if requested == "anthropic":
                raise ProviderNotAllowedError(lock, provider="anthropic")
            return "ollama"
        return requested or self.default_provider

    def _local_agents(self) -> dict[str, str]:
        """Agents 100 % locaux joignables par délégation (nom → nom affiché)."""
        roster: list[tuple[str, str, bool]] = getattr(self.env, "delegation_roster", None) or []
        names: dict[str, str] = getattr(self.env, "delegation_names", None) or {}
        return {name: names.get(name, name) for name, _, local in roster if local}

    def _local_answer(self, history: Sequence[Message]) -> str | None:
        """Source (pour le message du verrou) de la première réponse d'un agent 100 % local de
        l'historique : réponse complète, ou partielle d'un sous-agent arrêté avant la fin
        (résultat en erreur, mais ses données y sont). Un refus avant exécution (moteur en
        ligne…) ne compte pas. Un agent qui n'existe plus (supprimé, extension retirée) compte
        comme local : on ne sait plus s'il l'était."""
        names: dict[str, str] = getattr(self.env, "delegation_names", None) or {}
        if not names:
            return None  # environnement sans délégation (workflows, tests) : rien à vérifier
        local = self._local_agents()
        for call, result in call_results(history):
            agent = call.input.get("agent")
            if call.name != DELEGATE_TOOL or not isinstance(agent, str):
                continue
            if agent in names and agent not in local:
                continue  # agent connu, qui n'est pas local
            if result.is_error and PARTIAL_ANSWER not in result.content:
                continue  # refus ou panne avant toute réponse : rien de l'agent dans l'historique
            if agent in local:
                return f"« {local[agent]} », agent 100 % local"
            return f"« {agent} », agent qui n'existe plus (faute de savoir s'il était local)"
        return None

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
        # Verrou local : agent sensible, réponse d'un agent local dans l'historique, ou sous-tâche
        # d'une conversation verrouillée (posé par la délégation dans le contexte du sous-agent)
        forced = bool(ctx.state.get(STATE_LOCAL_LOCK))
        provider = self.resolve_provider(provider, messages, forced=forced)
        locked = self.privacy_lock(messages, forced=forced) is not None
        allow_fallback = not locked
        # Moteur et modèle posés AVANT la reprise : une délégation validée s'exécute juste après
        ctx.state[STATE_PROVIDER] = provider or self.router.default
        ctx.state[STATE_MODEL] = model
        ctx.state[STATE_LOCAL_LOCK] = locked
        history = list(messages)
        new_messages: list[Message] = []
        artifacts: list[Artifact] = []
        usage = Usage()
        system = self.build_system_prompt(ctx)
        if has_attachments(history):
            system += ATTACHMENTS_NOTE
        response: LLMResponse | None = None
        # Étapes comptées sur tout le tour : une reprise après validation ne remet pas à zéro
        iteration = turn_iterations(messages)
        restored = False

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
                    if not restored and self._needs_restore(call, approvals):
                        # Nouvelle requête, contexte vide : rejouer d'abord l'historique, juste
                        # avant le premier outil qui en dépend (relecture déjà autorisée)
                        await self._restore(messages, ctx)
                        restored = True
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
                usage = usage + self._tool_usage(ctx)
                tool_msg = Message(role="user", content=list(results))
                history.append(tool_msg)
                new_messages.append(tool_msg)
                approvals = None  # une validation ne vaut que pour les appels présentés
                pending_calls = []
                if not locked and self._local_answer(history) is not None:
                    # Réponse d'un agent local entrée dans l'historique : plus rien ne part en
                    # ligne, ni repli vers Claude, ni sous-agent hors d'Ollama
                    locked, allow_fallback = True, False
                    if (provider or self.router.default) != "ollama":
                        model = None
                    provider = "ollama"
                    ctx.state[STATE_PROVIDER], ctx.state[STATE_MODEL] = provider, model
                    ctx.state[STATE_LOCAL_LOCK] = True

            # Au plafond : un dernier appel, sans exécuter d'outil, pour une synthèse plutôt
            # qu'un texte vide
            closing = iteration >= self.max_iterations
            if not closing:
                iteration += 1
            # Le routeur renvoie la MÊME requête au moteur de repli : une spécification qui en
            # dépend (agents joignables) doit rester vraie sur les deux (`spec_for`)
            ctx.state[STATE_FALLBACK] = self._backup(provider, allow_fallback)
            request = LLMRequest(
                messages=expand_attachments(history, attachments),
                system=system + (LIMIT_NOTE if closing else ""),
                tools=[t.spec_for(ctx) for t in self.tools.values()],
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

            # Repli éventuel du routeur : on reste sur le provider effectivement utilisé, et la
            # délégation le voit (un agent local n'est joignable que sur Ollama)
            if response.provider != (provider or self.router.default):
                model = None  # un nom de modèle n'est pas portable entre providers
            provider = response.provider
            ctx.state[STATE_PROVIDER], ctx.state[STATE_MODEL] = provider, model

            usage = usage + response.usage
            if closing:
                closed = without_tool_calls(response)
                if closed.text != response.text:  # texte par défaut : affiché comme le reste
                    yield TextDeltaEvent(text=LIMIT_FALLBACK)
                response = closed
            assistant_msg = Message(role="assistant", content=response.content)
            history.append(assistant_msg)
            new_messages.append(assistant_msg)

            calls = response.tool_calls
            if closing or response.stop_reason != "tool_use" or not calls:
                yield DoneEvent(
                    result=self._result(
                        response,
                        provider,
                        "max_iterations" if closing else response.stop_reason,
                        iteration,
                        usage,
                        artifacts,
                        new_messages,
                    )
                )
                return
            pending_calls = calls

    # Outils --------------------------------------------------------------

    def _will_run(self, call: ToolUseBlock, approvals: dict[str, bool] | None) -> bool:
        """Vrai si cet appel va réellement s'exécuter (outil connu, validé si nécessaire)."""
        tool = self.tools.get(call.name)
        if tool is None:
            return False
        return not self.needs_approval(tool) or (approvals or {}).get(call.id, False)

    def _needs_restore(self, call: ToolUseBlock, approvals: dict[str, bool] | None) -> bool:
        """Vrai si cet appel va s'exécuter ET lit le contexte reconstruit (ex. data_via_query)."""
        tool = self.tools.get(call.name)
        return tool is not None and tool.uses_restored_state and self._will_run(call, approvals)

    async def _restore(self, history: Sequence[Message], ctx: ToolContext) -> None:
        """Reconstruit `ctx.state`, perdu d'une requête à l'autre : chaque appel réussi de
        l'historique est rejoué par le crochet `restore` de son outil, une fois par entrée."""
        seen: set[str] = set()
        for call in successful_calls(history):
            tool = self.tools.get(call.name)
            key = call.name + json.dumps(call.input, sort_keys=True, default=str)
            if tool is None or key in seen:
                continue
            seen.add(key)
            await tool.replay(call.input, ctx)

    def _backup(self, provider: ProviderName | None, allow_fallback: bool) -> ProviderName | None:
        """Moteur vers lequel le routeur peut se replier au prochain appel (None : aucun)."""
        backup = self.router.fallback if allow_fallback else None
        if backup is None or backup == (provider or self.router.default):
            return None
        try:
            self.router.get_provider(backup)  # repli vers un moteur non configuré : aucun
        except ProviderNotConfiguredError:
            return None
        return backup

    @staticmethod
    def _tool_usage(ctx: ToolContext) -> Usage:
        """Jetons consommés par les outils (sous-agents) depuis le dernier relevé."""
        extra = ctx.state.pop(STATE_USAGE, None)
        return extra if isinstance(extra, Usage) else Usage()

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
    if tool.name == DELEGATE_TOOL:
        return "delegation"
    return "read"


# ─── Lecture de l'historique ──────────────────────────────────────


def call_results(history: Sequence[Message]) -> Iterator[tuple[ToolUseBlock, ToolResultBlock]]:
    """Appels d'outils de l'historique avec leur résultat : chaque message assistant est
    apparié au message utilisateur qui le suit, qui porte ses résultats."""
    for i, message in enumerate(history[:-1]):
        following = history[i + 1]
        if message.role != "assistant" or following.role != "user":
            continue
        results = {b.tool_use_id: b for b in following.content if isinstance(b, ToolResultBlock)}
        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.id in results:
                yield block, results[block.id]


def successful_calls(history: Sequence[Message]) -> Iterator[ToolUseBlock]:
    """Appels d'outils de l'historique exécutés sans erreur (ni refus)."""
    for call, result in call_results(history):
        if not result.is_error:
            yield call


def turn_iterations(history: Sequence[Message]) -> int:
    """Appels au modèle déjà faits dans le tour : messages assistant depuis le dernier message
    de l'utilisateur qui n'est pas seulement un retour d'outils."""
    count = 0
    for message in reversed(history):
        if message.role == "assistant":
            count += 1
        elif any(not isinstance(b, ToolResultBlock) for b in message.content):
            break
    return count


def without_tool_calls(response: LLMResponse) -> LLMResponse:
    """Réponse de clôture : appels d'outils retirés (jamais exécutés, ils resteraient sans
    résultat dans l'historique) ; un texte par défaut si le modèle n'a rien écrit."""
    content = [b for b in response.content if not isinstance(b, ToolUseBlock)]
    if not any(isinstance(b, TextBlock) and b.text.strip() for b in content):
        content = [*content, TextBlock(text=LIMIT_FALLBACK)]
    return response.model_copy(update={"content": content})
