"""Délégation : un orchestrateur confie une sous-tâche à un agent spécialisé.

Règles :
- un seul niveau (un sous-agent ne délègue pas, et n'a pas d'outils à valider) ;
- un agent verrouillé en local (finances) n'est appelable que si l'orchestrateur tourne
  lui-même sur le modèle local : sinon sa réponse partirait chez Claude ;
- les artefacts produits par le sous-agent remontent dans le panneau.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from app.core.llm.errors import LLMError
from app.core.llm.types import Message, ToolSpec
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


class DelegateTool(BaseTool[DelegateInput]):
    name = "delegate_to_agent"
    description = "Confie une sous-tâche à un agent spécialisé et renvoie sa réponse."
    input_model = DelegateInput

    def __init__(self, env: ToolEnvironment, roster: list[tuple[str, str, bool]]) -> None:
        self.env = env
        self.roster = roster  # (nom, description, local_only)

    def spec(self) -> ToolSpec:
        lines = [
            f"- {name} : {desc}"
            + (" [données locales : seulement si tu tournes sur Ollama]" if local else "")
            for name, desc, local in self.roster
        ]
        return ToolSpec(
            name=self.name,
            description=(
                "Confie une sous-tâche à un agent spécialisé de la suite Atelier et renvoie sa "
                "réponse finale (ses livrables vont directement dans le panneau Artefacts). "
                "Une délégation par sous-tâche ; donne une consigne autonome.\nAgents disponibles :\n"
                + "\n".join(lines)
            ),
            input_schema=portable_schema(DelegateInput),
        )

    async def run(self, params: DelegateInput, ctx: ToolContext) -> ToolOutput:
        catalog: AgentCatalog | None = getattr(self.env, "catalog", None)
        router: LLMRouter | None = getattr(self.env, "router", None)
        if catalog is None or router is None:
            return ToolOutput(content="Délégation indisponible dans ce contexte.", is_error=True)
        if params.agent not in {name for name, _, _ in self.roster}:
            names = ", ".join(n for n, _, _ in self.roster)
            return ToolOutput(
                content=f"Agent « {params.agent} » indisponible. Choix : {names}.", is_error=True
            )

        target = await catalog.build(params.agent, router, self.env, delegated=True)
        current = ctx.state.get("provider")
        if target.local_only and current != "ollama":
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
                provider=None if target.local_only else current,
                context=ToolContext(conversation_id=ctx.conversation_id, user_id=ctx.user_id),
            )
        except LLMError as exc:
            return ToolOutput(
                content=f"{target.display_name} n'a pas pu répondre : {exc}", is_error=True
            )
        note = f" ({len(result.artifacts)} livrable(s) publié(s))" if result.artifacts else ""
        return ToolOutput(
            content=f"Réponse de {target.display_name}{note} :\n{result.text}",
            artifacts=result.artifacts,
        )


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
