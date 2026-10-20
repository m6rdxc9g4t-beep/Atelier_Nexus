"""Assistant généraliste — agent de référence (et de test) du hub."""

from typing import Any

from app.agents.base import BaseAgent
from app.agents.registry import register_agent
from app.tools import BaseTool, CurrentDateTimeTool, PublishArtifactTool


@register_agent
class AssistantAgent(BaseAgent):
    name = "assistant"
    display_name = "Assistant Atelier"
    description = "Assistant généraliste de la suite Atelier, capable de publier des artefacts."
    system_prompt = (
        "Tu es l'assistant de la suite Atelier (Atelier Nexus). Réponds en français, "
        "de façon concise et précise.\n"
        "- Pour tout code, requête ou document de plus de quelques lignes, appelle "
        "`publish_artifact` puis résume en une ou deux phrases ; n'écris pas le livrable "
        "dans le chat.\n"
        "- Pour toute question qui dépend de la date du jour, appelle `current_datetime`.\n"
        "- Si une information te manque, dis-le plutôt que de l'inventer."
    )

    def default_tools(self) -> list[BaseTool[Any]]:
        return [CurrentDateTimeTool(), PublishArtifactTool()]
