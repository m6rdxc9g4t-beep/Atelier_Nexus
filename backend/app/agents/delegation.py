"""Délégation : un orchestrateur confie une sous-tâche à un agent spécialisé.

Règles :
- en `APPROVAL_MODE=every_step` (défaut), la délégation attend la validation de l'utilisateur
  (résumé : agent + consigne), comme tout appel d'outil ; en `writes_only`, elle part
  directement : elle ne modifie rien, et le sous-agent n'a que des lectures ;
- un seul niveau (un sous-agent ne délègue pas, et n'a pas d'outils à valider) ; en
  `every_step`, même ses lectures devraient être validées, ce qui ne peut pas lui être
  présenté : il n'a alors AUCUN outil, répond à partir de la consigne seule et rend son
  livrable en texte, que l'orchestrateur publie ;
- le sous-agent tourne sur le moteur réellement utilisé par l'orchestrateur (posé par la boucle
  avant la reprise, suivi après un repli), avec le même modèle ; moteur inconnu → refus ;
- liste fermée (`enum`) des agents proposés, selon le moteur ; jamais l'Assistant, ni un agent
  doté lui-même de la délégation (`prepare_environment`) ; chaque agent y signale ses boîtes
  indisponibles (`roster_entry`) ;
- un agent verrouillé en local (finances, Savoir) n'est proposé et joignable que si
  l'orchestrateur tourne lui-même sur le modèle local : sinon sa réponse partirait chez Claude.
  Une fois sa réponse dans l'historique, toute la conversation reste sur le modèle local
  (`BaseAgent.privacy_lock`), sous-agents compris. Un repli Ollama → Claude reçoit la même
  requête (spécification construite pour Ollama, qui l'annonce alors) : rien de local n'y figure
  (une conversation verrouillée ne se replie jamais) et `run` refuse l'agent local, le moteur
  étant mis à jour après la réponse ;
- les artefacts produits par le sous-agent remontent dans le panneau, ses jetons dans l'usage
  du tour ; un sous-agent arrêté avant la fin (étapes, longueur) est signalé comme une erreur,
  réponse partielle jointe (`PARTIAL_ANSWER`) : venue d'un agent local, elle verrouille aussi la
  conversation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from pydantic import Field

from app.agents.base import (
    DELEGATE_TOOL,
    PARTIAL_ANSWER,
    STATE_FALLBACK,
    STATE_LOCAL_LOCK,
    STATE_MODEL,
    STATE_PROVIDER,
    STATE_USAGE,
    BaseAgent,
)
from app.core.llm.errors import LLMError
from app.core.llm.types import Message, ProviderName, ToolSpec, Usage
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput, portable_schema
from app.tools.toolsets import Toolset, register_toolset

if TYPE_CHECKING:
    from app.agents.catalog import AgentCatalog
    from app.core.llm.router import LLMRouter
    from app.tools.environment import ToolEnvironment


class DelegateInput(ToolInput):
    agent: str = Field(description="Identifiant de l'agent spécialisé (liste dans la description).")
    task: str = Field(
        min_length=10,
        max_length=8000,
        description="Consigne complète et autonome : contexte, données utiles, livrable attendu.",
    )


#: Longueur de la consigne montrée sur la carte de validation
TASK_SHOWN = 600

#: Jamais proposé : l'Assistant généraliste n'apporte rien à une sous-tâche
NOT_DELEGABLE = frozenset({"assistant"})

PROVIDERS: frozenset[str] = frozenset(get_args(ProviderName))

#: Arrêts d'un sous-agent qui laissent la sous-tâche inachevée
UNFINISHED = {
    "max_iterations": "nombre d'étapes maximal atteint",
    "max_tokens": "réponse coupée, trop longue",
    "refusal": "le modèle a refusé de répondre",
    "awaiting_approval": "une action attendait une validation",
    "tool_use": "il attendait encore un outil",
}


class DelegateTool(BaseTool[DelegateInput]):
    name = DELEGATE_TOOL
    description = "Confie une sous-tâche à un agent spécialisé et renvoie sa réponse."
    input_model = DelegateInput

    def __init__(self, env: ToolEnvironment, roster: list[tuple[str, str, bool]]) -> None:
        self.env = env
        self.roster = roster  # (nom, description, local_only)

    @property
    def without_tools(self) -> bool:
        """Vrai en `every_step` : le sous-agent répond sans aucun outil."""
        return bool(self.env.settings.approval_mode == "every_step")

    def _names(self) -> dict[str, str]:
        names: dict[str, str] = getattr(self.env, "delegation_names", {})
        return names

    def agents(self, provider: str | None = None) -> list[tuple[str, str, bool]]:
        """Agents proposés. Moteur connu : les agents 100 % locaux seulement sur Ollama."""
        return [
            (name, desc, local)
            for name, desc, local in self.roster
            if name not in NOT_DELEGABLE and (provider is None or not local or provider == "ollama")
        ]

    def approval_summary(self, params: DelegateInput) -> str:
        who = self._names().get(params.agent, params.agent)
        task = " ".join(params.task.split())
        task = task if len(task) <= TASK_SHOWN else task[: TASK_SHOWN - 1] + "…"
        summary = f"Confier à « {who} » : « {task} »"
        if self.without_tools:
            summary += " — il répondra sans outil, à partir de cette consigne seulement"
        return summary

    def spec(self) -> ToolSpec:
        """Sans contexte (catalogues, métadonnées) : tous les agents, locaux signalés."""
        return self._spec(None)

    def spec_for(self, ctx: ToolContext) -> ToolSpec:
        """Pendant un tour : la liste suit le moteur réellement utilisé (repli compris).

        Le routeur renvoie la même requête au moteur de repli : sur Ollama avec un repli possible
        vers Claude, la description le dit (un agent local y serait refusé par `run`)."""
        provider = ctx.state.get(STATE_PROVIDER)
        backup = ctx.state.get(STATE_FALLBACK)
        return self._spec(
            provider if provider in PROVIDERS else None,
            backup=backup in PROVIDERS and backup != provider,
        )

    def _spec(self, provider: str | None, *, backup: bool = False) -> ToolSpec:
        agents = self.agents(provider)
        lines = [
            f"- {name} : {desc}" + (" [données locales]" if local else "")
            for name, desc, local in agents
        ]
        hidden = [
            self._names().get(name, name)
            for name, _, local in self.agents()
            if local and name not in {n for n, _, _ in agents}
        ]
        if provider == "ollama" and backup:
            engine = (
                "Tu tournes sur le modèle local (Ollama), avec un repli possible sur un modèle en "
                "ligne en cas de panne : un agent [données locales] n'est joignable que sur le "
                "modèle local (sinon, la délégation est refusée)."
            )
        elif provider == "ollama":
            engine = (
                "Tu tournes sur le modèle local (Ollama) : les agents [données locales] sont "
                "joignables."
            )
        elif provider is not None:
            engine = (
                f"Tu tournes sur un modèle en ligne : les agents 100 % locaux ({', '.join(hidden)}) "
                "ne sont pas proposés ; si la demande en relève, propose à l'utilisateur de les "
                "ouvrir directement."
                if hidden
                else "Tu tournes sur un modèle en ligne."
            )
        else:
            engine = (
                "Les agents [données locales] ne sont joignables que si tu tournes sur le modèle "
                "local (Ollama)."
            )
        schema = portable_schema(DelegateInput)
        if agents:  # liste fermée : le modèle ne peut pas inventer un identifiant
            schema["properties"]["agent"]["enum"] = [name for name, _, _ in agents]
        return ToolSpec(
            name=self.name,
            description=(
                "Confie une sous-tâche à un agent spécialisé de la suite Atelier et renvoie sa "
                + (
                    "réponse finale (texte). Le sous-agent n'a AUCUN outil (chaque action doit "
                    "être validée par l'utilisateur) : mets dans la consigne toutes les données "
                    "dont il a besoin. Il rend son livrable en texte : publie-le ensuite avec "
                    "`publish_artifact`."
                    if self.without_tools
                    else "réponse finale (ses livrables vont directement dans le panneau Artefacts)."
                )
                + " Une délégation par sous-tâche ; donne une consigne autonome. "
                + engine
                + "\nAgents disponibles :\n"
                + "\n".join(lines)
            ),
            input_schema=schema,
        )

    async def run(self, params: DelegateInput, ctx: ToolContext) -> ToolOutput:
        catalog: AgentCatalog | None = getattr(self.env, "catalog", None)
        router: LLMRouter | None = getattr(self.env, "router", None)
        if catalog is None or router is None:
            return ToolOutput(content="Délégation indisponible dans ce contexte.", is_error=True)
        current = ctx.state.get(STATE_PROVIDER)
        if params.agent not in {name for name, _, _ in self.agents()}:
            choices = ", ".join(n for n, _, _ in self.agents(current)) or "aucun"
            return ToolOutput(
                content=f"Agent « {params.agent} » indisponible. Choix : {choices}.", is_error=True
            )
        if current not in PROVIDERS:
            # Jamais de moteur « par défaut » pour un sous-agent : il pourrait partir en ligne
            # alors que l'utilisateur a choisi le modèle local
            return ToolOutput(
                content="Délégation refusée : le moteur de l'orchestrateur est inconnu ici.",
                is_error=True,
            )

        target = await catalog.build(params.agent, router, self.env, delegated=True)
        locked = bool(ctx.state.get(STATE_LOCAL_LOCK))
        if (target.local_only or locked) and current != "ollama":
            return ToolOutput(
                content=(
                    f"Refusé : « {target.display_name} » manipule des données qui ne doivent pas quitter "
                    "la machine, et tu tournes sur un modèle en ligne. Propose à l'utilisateur d'ouvrir "
                    f"directement l'agent « {target.display_name} »."
                ),
                is_error=True,
            )
        try:
            result = await target.run(
                [Message.user(params.task)],
                provider=current,  # vérifié ci-dessus : un moteur connu
                model=ctx.state.get(STATE_MODEL),
                context=ToolContext(
                    conversation_id=ctx.conversation_id,
                    user_id=ctx.user_id,
                    # Conversation verrouillée : la consigne peut citer des données locales
                    state={STATE_LOCAL_LOCK: True} if locked else {},
                ),
            )
        except LLMError as exc:
            return ToolOutput(
                content=f"{target.display_name} n'a pas pu répondre : {exc}", is_error=True
            )
        previous = ctx.state.get(STATE_USAGE)
        ctx.state[STATE_USAGE] = (
            previous if isinstance(previous, Usage) else Usage()
        ) + result.usage

        text = result.text.strip()
        if result.stop_reason in UNFINISHED or not (text or result.artifacts):
            why = UNFINISHED.get(result.stop_reason, "réponse vide")
            content = (
                f"{target.display_name} s'est arrêté avant la fin ({why}) : reformule la consigne "
                "ou découpe la sous-tâche."
            )
            if text:  # repère lu par le verrou local (`BaseAgent._local_answer`)
                content += f"\n{PARTIAL_ANSWER}\n{text}"
            return ToolOutput(content=content, is_error=True, artifacts=result.artifacts)

        note = f" ({len(result.artifacts)} livrable(s) publié(s))" if result.artifacts else ""
        content = f"Réponse de {target.display_name}{note} :\n{result.text}"
        if self.without_tools:
            content += (
                "\n\n(Sous-agent sans outil : s'il y a un livrable ci-dessus, publie-le avec "
                "`publish_artifact`, puis résume.)"
            )
        return ToolOutput(content=content, artifacts=result.artifacts)


def roster_entry(agent: BaseAgent) -> tuple[str, str, bool]:
    """Ligne du roster (nom, description, 100 % local), lue par la délégation et par l'annuaire
    de l'Assistant. La description signale les boîtes indisponibles ici (application non
    configurée, extension retirée) : l'orchestrateur ne confie pas sans le savoir une sous-tâche à
    un agent privé de ses données, l'Assistant le dit en orientant."""
    labels = list(dict.fromkeys(u.label for u in agent.unavailable))
    note = f" [indisponible ici : {', '.join(labels)}]" if labels else ""
    return agent.name, agent.description + note, agent.local_only


def _build(env: ToolEnvironment) -> list[BaseTool[Any]]:
    roster: list[tuple[str, str, bool]] = getattr(env, "delegation_roster", [])
    return [DelegateTool(env, roster)]


register_toolset(
    Toolset(
        id="delegation",
        label="Délégation aux agents",
        description="Confier des sous-tâches aux autres agents (orchestration).",
        build=_build,
    )
)
