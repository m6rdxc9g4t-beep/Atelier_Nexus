"""Connecteur Atelier Wiki (contrat `atelier-node/1`, API sur 3200).

Routes appelées, lues dans le dépôt `Atelier_Wiki` :
- manifeste et actions (`backend/src/services/atelier-manifest.ts`, `routes/atelier.ts`) :
  `spaces.list` (GET /api/atelier/spaces), `pages.search` (POST /api/atelier/search),
  `pages.list` (GET /api/atelier/pages), `pages.get` (GET /api/atelier/pages/{page_id}),
  `pages.create` (POST /api/atelier/pages, idempotence par en-tête),
  `pages.append` (POST /api/atelier/pages/{page_id}/append, idempotence par en-tête),
  `pages.replace` (PUT /api/atelier/pages/{page_id}, ancienne version gardée dans l'historique) ;
- hors manifeste : POST /api/spaces (`routes/wiki.ts`, corps {name, icon, description}).

Lectures libres (validées en `every_step` comme toute action) ; écritures `requires_approval`.
Le texte des pages est rendu au modèle comme une donnée délimitée, jamais comme une consigne.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.tools.suite_node import NodeTool, NoInput, as_data, table_output

ID = r"^[0-9]+$"


class _WikiTool[InputT: ToolInput](NodeTool[InputT]):
    app = "wiki"


def page_text(page: dict[str, Any], *, with_content: bool = True) -> str:
    backlinks = page.get("backlinks") or []
    lines = [
        f"Page « {page.get('title')} » (id {page.get('id')}, espace « {page.get('space')} », "
        f"version {page.get('version')}, modifiée le {str(page.get('updated_at'))[:16]} "
        f"par {page.get('updated_by')}).",
    ]
    if page.get("url"):
        lines.append(f"Adresse : {page['url']}")
    if backlinks:
        cited = ", ".join(f"« {b.get('title')} » ({b.get('id')})" for b in backlinks[:15])
        lines.append(f"Citée par : {cited}.")
    if with_content:
        lines.append(as_data(str(page.get("content") or ""), kind="page du wiki"))
    return "\n".join(lines)


# ─── Lecture ──────────────────────────────────────────────────────


class SpacesTool(_WikiTool[NoInput]):
    name = "wiki_spaces"
    description = (
        "Espaces d'Atelier Wiki (id, nom, nombre de pages) : pour savoir où ranger ou chercher."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        return table_output(self.app, await self.action("spaces.list", {}), noun="espace")


class SearchInput(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Mots cherchés (titres et texte, accents ignorés).",
    )
    space_id: str | None = Field(
        default=None, description="Limiter à un espace (id).", pattern=r"^[0-9]+$", max_length=12
    )
    limit: int = Field(default=20, ge=1, le=100, description="Nombre de pages au plus.")


class SearchTool(_WikiTool[SearchInput]):
    name = "wiki_search"
    description = (
        "Recherche plein texte dans Atelier Wiki : pages et extraits. À utiliser AVANT d'écrire "
        "(une page existe peut-être déjà) et pour retrouver décisions, procédures, comptes rendus."
    )
    input_model = SearchInput

    async def run(self, params: SearchInput, ctx: ToolContext) -> ToolOutput:
        data = await self.action("pages.search", params.model_dump(exclude_none=True))
        return table_output(
            self.app, data, noun="page", empty=f"Aucune page pour « {params.query} »."
        )


class PagesInput(ToolInput):
    space_id: str | None = Field(
        default=None, description="Limiter à un espace (id).", pattern=r"^[0-9]+$", max_length=12
    )
    updated_since: str | None = Field(
        default=None, max_length=40, description="Pages modifiées depuis cet instant (ISO 8601)."
    )
    limit: int = Field(default=100, ge=1, le=1000, description="Nombre de pages au plus.")


class PagesTool(_WikiTool[PagesInput]):
    name = "wiki_pages"
    description = (
        "Pages d'Atelier Wiki (titre, espace, version, dernière modification), sans leur contenu."
    )
    input_model = PagesInput

    async def run(self, params: PagesInput, ctx: ToolContext) -> ToolOutput:
        data = await self.action("pages.list", params.model_dump(exclude_none=True))
        return table_output(self.app, data, noun="page")


class PageInput(ToolInput):
    page_id: str = Field(
        description="Identifiant de la page (wiki_search ou wiki_pages).",
        pattern=r"^[0-9]+$",
        max_length=12,
    )


class ReadPageTool(_WikiTool[PageInput]):
    name = "wiki_read_page"
    description = "Contenu Markdown complet d'une page d'Atelier Wiki et les pages qui la citent."
    input_model = PageInput

    async def run(self, params: PageInput, ctx: ToolContext) -> ToolOutput:
        page = await self.action("pages.get", {"page_id": params.page_id})
        return ToolOutput(content=page_text(page), data=page)


# ─── Écriture (validation) ────────────────────────────────────────


class CreatePageInput(ToolInput):
    title: str = Field(min_length=1, max_length=200, description="Titre de la page.")
    content: str = Field(
        default="", max_length=200_000, description="Contenu Markdown ; liens [[Titre]]."
    )
    space_id: str | None = Field(
        default=None,
        description="Espace cible (défaut : le premier).",
        pattern=r"^[0-9]+$",
        max_length=12,
    )
    parent_id: str | None = Field(
        default=None, description="Page parente (même espace).", pattern=r"^[0-9]+$", max_length=12
    )


class CreatePageTool(_WikiTool[CreatePageInput]):
    name = "wiki_create_page"
    description = (
        "Crée une page dans Atelier Wiki (Markdown, éventuellement sous une page parente). "
        "Chercher d'abord avec wiki_search pour ne pas créer de doublon."
    )
    input_model = CreatePageInput
    requires_approval = True

    def approval_summary(self, params: CreatePageInput) -> str:
        where = f" sous la page {params.parent_id}" if params.parent_id else ""
        space = f" dans l'espace {params.space_id}" if params.space_id else ""
        return (
            f"Créer dans Atelier Wiki la page « {params.title} »{space}{where} "
            f"({len(params.content)} caractères)"
        )

    async def run(self, params: CreatePageInput, ctx: ToolContext) -> ToolOutput:
        payload = params.model_dump(exclude_none=True)
        page = await self.action("pages.create", payload, idempotent_on=payload)
        return ToolOutput(content="Page créée. " + page_text(page, with_content=False), data=page)


class AppendInput(ToolInput):
    page_id: str = Field(description="Page complétée.", pattern=r"^[0-9]+$", max_length=12)
    content: str = Field(min_length=1, max_length=200_000, description="Markdown ajouté à la fin.")
    heading: str | None = Field(
        default=None, max_length=200, description="Titre de section (## …) placé avant."
    )


class AppendTool(_WikiTool[AppendInput]):
    name = "wiki_append_page"
    description = (
        "Ajoute une section à la fin d'une page existante d'Atelier Wiki (compte rendu, journal, "
        "décision) sans toucher au reste."
    )
    input_model = AppendInput
    requires_approval = True

    def approval_summary(self, params: AppendInput) -> str:
        section = f" la section « {params.heading} »" if params.heading else " un texte"
        return f"Ajouter{section} à la page {params.page_id} d'Atelier Wiki ({len(params.content)} caractères)"

    async def run(self, params: AppendInput, ctx: ToolContext) -> ToolOutput:
        payload = params.model_dump(exclude_none=True)
        page = await self.action("pages.append", payload, idempotent_on=payload)
        return ToolOutput(
            content="Page complétée. " + page_text(page, with_content=False), data=page
        )


class ReplaceInput(ToolInput):
    page_id: str = Field(description="Page réécrite.", pattern=r"^[0-9]+$", max_length=12)
    content: str = Field(max_length=200_000, description="Nouveau contenu Markdown COMPLET.")
    title: str | None = Field(
        default=None, min_length=1, max_length=200, description="Nouveau titre."
    )


class ReplaceTool(_WikiTool[ReplaceInput]):
    name = "wiki_replace_page"
    description = (
        "Remplace tout le contenu d'une page d'Atelier Wiki (l'ancienne version reste dans "
        "l'historique). Lire la page d'abord ; pour ajouter, préférer wiki_append_page."
    )
    input_model = ReplaceInput
    requires_approval = True

    def approval_summary(self, params: ReplaceInput) -> str:
        title = f", titre « {params.title} »" if params.title else ""
        return (
            f"RÉÉCRIRE entièrement la page {params.page_id} d'Atelier Wiki{title} "
            f"({len(params.content)} caractères ; l'ancienne version reste dans l'historique)"
        )

    async def run(self, params: ReplaceInput, ctx: ToolContext) -> ToolOutput:
        page = await self.action("pages.replace", params.model_dump(exclude_none=True))
        return ToolOutput(
            content="Page réécrite. " + page_text(page, with_content=False), data=page
        )


class CreateSpaceInput(ToolInput):
    name: str = Field(min_length=1, max_length=200, description="Nom de l'espace.")
    description: str = Field(default="", max_length=2000, description="À quoi sert cet espace.")
    icon: str = Field(default="", max_length=16, description="Émoji facultatif.")


class CreateSpaceTool(_WikiTool[CreateSpaceInput]):
    name = "wiki_create_space"
    description = (
        "Crée un espace dans Atelier Wiki (vérifier d'abord wiki_spaces : les noms sont uniques)."
    )
    input_model = CreateSpaceInput
    requires_approval = True

    def approval_summary(self, params: CreateSpaceInput) -> str:
        return f"Créer l'espace « {params.name} » dans Atelier Wiki"

    async def run(self, params: CreateSpaceInput, ctx: ToolContext) -> ToolOutput:
        space = await self.http("POST", "/api/spaces", params.model_dump())
        return ToolOutput(
            content=f"Espace « {space.get('name')} » créé (id {space.get('id')}).", data=space
        )


def wiki_read_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [SpacesTool(env), SearchTool(env), PagesTool(env), ReadPageTool(env)]


def wiki_write_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [CreatePageTool(env), AppendTool(env), ReplaceTool(env), CreateSpaceTool(env)]
