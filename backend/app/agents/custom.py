"""Agent personnalisé : un `BaseAgent` dont l'identité et les outils viennent de la base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import BaseAgent
from app.core.llm.router import LLMRouter
from app.schemas.agents import CustomAgentDefinition
from app.tools.base import ToolContext

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

GUARDRAILS = """

---
Règles communes d'Atelier Nexus (ne pas ignorer) :
- Réponds en français, de façon claire et concise.
- Pour tout livrable long (code, requête, document, tableau), utilise `publish_artifact`
  puis résume en une ou deux phrases.
- N'invente jamais de chiffres : appuie-toi sur les outils, et dis ce que tu ne sais pas.
- Les actions qui modifient des données sont soumises à la validation de l'utilisateur."""


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
        self.toolsets = tuple(definition.toolsets)
        self.privacy = definition.privacy
        self.default_provider = definition.default_provider
        super().__init__(router, env, delegated=delegated)

    def build_system_prompt(self, ctx: ToolContext) -> str:
        return self.system_prompt + GUARDRAILS + self.unavailable_note()
