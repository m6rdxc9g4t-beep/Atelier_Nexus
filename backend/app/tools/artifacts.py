"""Publication de livrables vers le panneau Artefacts du frontend.

Plutôt que de noyer le chat sous une requête SQL ou une mesure DAX, l'agent
appelle `publish_artifact` : le livrable part dans `useArtifactStore` et le
modèle ne reçoit qu'un accusé de réception.
"""

from typing import Any

from pydantic import Field

from app.tools.base import Artifact, ArtifactKind, BaseTool, ToolContext, ToolInput, ToolOutput


class PublishArtifactInput(ToolInput):
    kind: ArtifactKind = Field(description="Type de livrable.")
    title: str = Field(min_length=1, max_length=200, description="Titre court et explicite.")
    content: str = Field(min_length=1, description="Contenu complet du livrable.")
    language: str | None = Field(
        default=None, description="Langage pour la coloration (sql, dax, m, tsx…)."
    )
    notes: str | None = Field(
        default=None, description="Instructions d'intégration (ex. étapes dans Power BI Desktop)."
    )


class PublishArtifactTool(BaseTool[PublishArtifactInput]):
    name = "publish_artifact"
    description = (
        "Publie un livrable (requête SQL, mesure DAX, script Power Query M, composant React, "
        "document Markdown, aperçu de données…) dans le panneau Artefacts de l'utilisateur. "
        "Toujours l'utiliser pour du code ou un document long au lieu de l'écrire dans le chat ; "
        "résumer ensuite en une ou deux phrases."
    )
    input_model = PublishArtifactInput

    async def run(self, params: PublishArtifactInput, ctx: ToolContext) -> ToolOutput:
        metadata: dict[str, Any] = {"notes": params.notes} if params.notes else {}
        artifact = Artifact(
            kind=params.kind,
            title=params.title,
            content=params.content,
            language=params.language,
            metadata=metadata,
        )
        return ToolOutput(
            content=f"Artefact « {params.title} » publié dans le panneau latéral.",
            artifacts=[artifact],
        )
