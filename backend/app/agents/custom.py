"""Agent personnalisé : un `BaseAgent` dont l'identité et les outils viennent de la base."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.agents.base import BaseAgent, successful_calls
from app.core.llm.router import LLMRouter
from app.core.llm.types import Message
from app.schemas.agents import CustomAgentDefinition
from app.tools.base import ToolContext
from app.tools.toolsets import UnavailableToolset, toolset_ids

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

#: En-tête des règles communes ajoutées au prompt de l'utilisateur, qui ne peut pas les lever
GUARDRAILS_HEADER = "\n\n---\nRègles communes d'Atelier Nexus (ne pas ignorer) :\n"

#: Raison donnée au modèle pour une boîte que cette installation ne connaît pas (ou plus)
UNKNOWN_TOOLSET = "boîte inconnue : extension retirée de NEXUS_PLUGINS ou non chargée"


def guardrails() -> str:
    """Règles communes des experts (source unique : `experts/common.py`), sous un en-tête
    protégé. Import tardif : ce module est chargé avant les experts (`app/agents/__init__.py`)."""
    from app.agents.experts.common import COMMON

    first, _, rest = COMMON.strip().partition("\n")
    rules = COMMON.strip() if first.lstrip().startswith("-") else rest
    return GUARDRAILS_HEADER + rules


class ConfigurableAgent(BaseAgent):
    source = "custom"

    def __init__(
        self,
        definition: CustomAgentDefinition,
        router: LLMRouter,
        env: ToolEnvironment | None = None,
        *,
        delegated: bool = False,
    ) -> None:
        self.definition = definition
        self.name = definition.name
        self.display_name = definition.display_name
        self.description = definition.description
        self.system_prompt = definition.system_prompt
        self.icon = definition.icon
        self.category = definition.category
        self.starters = tuple(definition.starters)
        # Boîte inconnue (extension retirée) : écartée des outils et signalée, jamais fatale ;
        # `toolsets` ne garde que les boîtes connues, lues ailleurs (workflows, carte de la suite).
        # Connues = celles que l'éditeur propose (comme le validateur) : une boîte interne d'une
        # extension n'est jamais ouverte à un agent personnalisé, même écrite à la main en base
        known = set(toolset_ids())
        self.toolsets = tuple(t for t in definition.toolsets if t in known)
        self.missing_toolsets = tuple(t for t in definition.toolsets if t not in known)
        self.privacy = definition.privacy
        self.default_provider = definition.default_provider
        # Étapes selon l'étendue des boîtes : 8 avec les seuls Essentiels, jusqu'à 16
        self.max_iterations = min(16, 6 + 2 * len(definition.toolsets))
        super().__init__(router, env, delegated=delegated)
        self.unavailable = [
            UnavailableToolset(id=t, label=t, reason=UNKNOWN_TOOLSET) for t in self.missing_toolsets
        ] + self.unavailable

    def build_system_prompt(self, ctx: ToolContext) -> str:
        return self.system_prompt + guardrails() + self.unavailable_note() + self.approval_note()

    def privacy_lock(self, history: Sequence[Message] = (), *, forced: bool = False) -> str | None:
        """Boîte devenue inconnue : on ne sait plus si elle était sensible. Une conversation qui
        contient des résultats d'outils que l'agent n'a plus reste donc sur le modèle local ;
        une nouvelle conversation n'est pas verrouillée."""
        reason = super().privacy_lock(history, forced=forced)
        if reason is None and self.missing_toolsets:
            if any(call.name not in self.tools for call in successful_calls(history)):
                missing = ", ".join(f"« {t} »" for t in self.missing_toolsets)
                return (
                    f"Cette conversation contient des résultats d'outils que « {self.display_name} » "
                    f"n'a plus (boîte {missing} inconnue) : faute de savoir s'ils étaient sensibles, "
                    "elle se poursuit uniquement avec le modèle local (Ollama)."
                )
        return reason
