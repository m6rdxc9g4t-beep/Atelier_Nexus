"""Mémoire d'équipe et rapports de l'équipe d'agents (docs/equipe.md).

**Mémoire** : un espace d'Atelier Wiki, « Équipe Atelier », que tous les agents lisent et complètent
de la même façon, pour se passer le travail d'une conversation à l'autre :

- page « Journal de l'équipe » : une section datée par note (« 2026-10-24 09:12 · Chef de projet ») ;
- page « Registre des décisions » : une section par décision (contexte, décision, conséquences) ;
- page « Comptes rendus » : une sous-page par réunion ou point (« CR 2026-10-24 — Lancement »).

L'espace et les pages sont créés à la première écriture (dans la même action validée, ce que dit la
carte de validation). Toutes les écritures passent par le nœud `atelier-node/1` du Wiki
(`app/tools/suite_node.py`) : idempotence, bouclage, schémas.

**Rapports** déterministes, sans modèle (utilisables dans les workflows et les rituels) :

- `equipe_point_avancement` : à partir d'Atelier Projets (tableau de bord, éléments, jalons) ;
- `equipe_synthese_formulaires` : synthèse AGRÉGÉE des formulaires ouverts (jamais de texte libre).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field

from app.schemas.projets import PRIORITY_LABELS, STATUS_LABELS, Project, WorkItem
from app.tools.base import Artifact, BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.tools.formatting import markdown_table
from app.tools.formulaire import aggregate_only, summary_text
from app.tools.http import AppError
from app.tools.suite_node import NodeTool, as_data

SPACE = "Équipe Atelier"
SPACE_DESCRIPTION = (
    "Mémoire partagée de l'équipe d'agents d'Atelier Nexus : journal, décisions, comptes rendus."
)
JOURNAL = "Journal de l'équipe"
DECISIONS = "Registre des décisions"
REPORTS = "Comptes rendus"
INTRO = {
    JOURNAL: "Notes datées de l'équipe d'agents et de l'utilisateur, la plus récente en bas.",
    DECISIONS: "Décisions prises, avec leur contexte et leurs conséquences. Une décision ne se "
    "supprime pas : une nouvelle décision la remplace et le dit.",
    REPORTS: "Comptes rendus de réunions et de points d'étape (une sous-page chacun).",
}
DONE = {"RESOLVED", "CLOSED", "REJECTED"}


class MemoryError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, app="wiki")


def now(env: ToolEnvironment) -> datetime:
    return datetime.now(ZoneInfo(env.settings.timezone))


# ─── Accès à l'espace de l'équipe ─────────────────────────────────


class _Memory[InputT: ToolInput](NodeTool[InputT]):
    app = "wiki"

    async def space_id(self) -> str | None:
        table = await self.action("spaces.list", {})
        for row in table.get("rows", []):
            if isinstance(row, dict) and row.get("nom") == SPACE:
                return str(row["id"])
        return None

    async def pages(self, space_id: str) -> list[dict[str, Any]]:
        table = await self.action("pages.list", {"space_id": space_id, "limit": 1000})
        return [r for r in table.get("rows", []) if isinstance(r, dict)]

    async def page_id(self, space_id: str, title: str) -> str | None:
        for row in await self.pages(space_id):
            if row.get("titre") == title and not row.get("parent_id"):
                return str(row["id"])
        return None

    async def ensure_space(self) -> str:
        found = await self.space_id()
        if found:
            return found
        space = await self.http(
            "POST", "/api/spaces", {"name": SPACE, "icon": "🤝", "description": SPACE_DESCRIPTION}
        )
        return str(space["id"])

    async def ensure_page(self, space_id: str, title: str) -> str:
        found = await self.page_id(space_id, title)
        if found:
            return found
        payload = {"title": title, "content": INTRO[title], "space_id": space_id}
        page = await self.action("pages.create", payload, idempotent_on=payload)
        return str(page["id"])


def _sections(content: str) -> list[str]:
    """Sections `## …` d'une page (la plus récente en dernier)."""
    parts = ("\n" + content).split("\n## ")
    return ["## " + p.strip() for p in parts[1:] if p.strip()]


# ─── Lecture de la mémoire ────────────────────────────────────────


class MemoryInput(ToolInput):
    recherche: str | None = Field(
        default=None,
        max_length=300,
        description="Mots cherchés dans toute la mémoire (sinon : dernières notes).",
    )
    entrees: int = Field(
        default=10, ge=1, le=50, description="Nombre de notes récentes du journal."
    )


class MemoryTool(_Memory[MemoryInput]):
    name = "equipe_memoire"
    description = (
        "Mémoire partagée de l'équipe (espace « Équipe Atelier » d'Atelier Wiki) : dernières notes "
        "du journal, décisions, comptes rendus, ou recherche. À lire AU DÉBUT de chaque tâche pour "
        "reprendre là où l'équipe s'est arrêtée."
    )
    input_model = MemoryInput

    async def run(self, params: MemoryInput, ctx: ToolContext) -> ToolOutput:
        space = await self.space_id()
        if space is None:
            return ToolOutput(
                content=(
                    f"La mémoire d'équipe n'existe pas encore (espace « {SPACE} » absent du Wiki) : "
                    "la première note (equipe_noter) la crée."
                )
            )
        if params.recherche:
            table = await self.action(
                "pages.search", {"query": params.recherche, "space_id": space, "limit": 20}
            )
            rows = [
                [r.get("id"), r.get("titre"), r.get("extrait")]
                for r in table.get("rows", [])
                if isinstance(r, dict)
            ]
            if not rows:
                return ToolOutput(
                    content=f"Rien dans la mémoire d'équipe pour « {params.recherche} »."
                )
            return ToolOutput(
                content="Pages de la mémoire d'équipe (lire en entier avec wiki_read_page) :\n"
                + markdown_table(["Id", "Page", "Extrait"], rows)
            )
        pages = await self.pages(space)
        by_title = {r.get("titre"): r for r in pages if not r.get("parent_id")}
        lines = [f"Mémoire d'équipe (espace « {SPACE} », {len(pages)} page(s))."]
        journal = by_title.get(JOURNAL)
        if journal:
            page = await self.action("pages.get", {"page_id": str(journal["id"])})
            notes = _sections(str(page.get("content") or ""))[-params.entrees :]
            lines.append(f"\nDernières notes du journal ({len(notes)}) :")
            lines.append(
                as_data("\n\n".join(notes) or "(vide)", kind="journal de l'équipe", limit=20_000)
            )
        decisions = by_title.get(DECISIONS)
        if decisions:
            page = await self.action("pages.get", {"page_id": str(decisions["id"])})
            titles = [s.splitlines()[0][3:] for s in _sections(str(page.get("content") or ""))]
            if titles:
                lines.append(
                    f"\nDécisions ({len(titles)}, page {decisions['id']}) : "
                    + " ; ".join(t[:120] for t in titles[-15:])
                )
        reports = by_title.get(REPORTS)
        if reports:
            children = [r for r in pages if str(r.get("parent_id")) == str(reports["id"])]
            if children:
                lines.append(
                    "\nComptes rendus : "
                    + " ; ".join(f"« {c.get('titre')} » ({c.get('id')})" for c in children[-10:])
                )
        return ToolOutput(content="\n".join(lines))


# ─── Écritures ────────────────────────────────────────────────────


_STRUCTURE = f"(crée l'espace « {SPACE} » et la page si besoin)"


class NoteInput(ToolInput):
    texte: str = Field(
        min_length=1,
        max_length=100_000,
        description="Note en Markdown : fait, avancement, question, suite à donner.",
    )
    auteur: str = Field(
        min_length=1,
        max_length=60,
        description="Qui note : ton rôle (« Chef de projet »…) ou « Rituel du lundi ».",
    )
    titre: str | None = Field(default=None, max_length=120, description="Titre court facultatif.")


class NoteTool(_Memory[NoteInput]):
    name = "equipe_noter"
    description = (
        "Ajoute une note datée au journal de l'équipe (Atelier Wiki) : ce qui a été fait, décidé "
        "en passant, ce qui reste à faire et pour qui. À appeler à la FIN d'une tâche."
    )
    input_model = NoteInput
    requires_approval = True

    def approval_summary(self, params: NoteInput) -> str:
        title = f" « {params.titre} »" if params.titre else ""
        return (
            f"Noter au journal de l'équipe{title}, par {params.auteur} "
            f"({len(params.texte)} caractères) {_STRUCTURE}"
        )

    async def run(self, params: NoteInput, ctx: ToolContext) -> ToolOutput:
        space = await self.ensure_space()
        page = await self.ensure_page(space, JOURNAL)
        heading = f"{now(self.env):%Y-%m-%d %H:%M} · {params.auteur}" + (
            f" — {params.titre}" if params.titre else ""
        )
        payload = {"page_id": page, "heading": heading, "content": params.texte}
        await self.action("pages.append", payload, idempotent_on=payload)
        return ToolOutput(
            content=f"Note ajoutée au journal de l'équipe (page {page}) : « {heading} »."
        )


class DecisionInput(ToolInput):
    titre: str = Field(min_length=1, max_length=150, description="La décision en une ligne.")
    decision: str = Field(
        min_length=1, max_length=20_000, description="Ce qui est décidé, précisément."
    )
    contexte: str = Field(
        default="", max_length=20_000, description="Pourquoi : faits, options écartées."
    )
    consequences: str = Field(
        default="", max_length=20_000, description="Ce que ça change, qui fait quoi."
    )
    auteur: str = Field(min_length=1, max_length=60, description="Qui l'enregistre (ton rôle).")


class DecisionTool(_Memory[DecisionInput]):
    name = "equipe_decision"
    description = (
        "Enregistre une décision dans le registre des décisions de l'équipe (Atelier Wiki), avec "
        "son contexte et ses conséquences. Seulement pour une décision prise ou validée par l'utilisateur."
    )
    input_model = DecisionInput
    requires_approval = True

    def approval_summary(self, params: DecisionInput) -> str:
        return f"Enregistrer la décision « {params.titre} » au registre de l'équipe {_STRUCTURE}"

    async def run(self, params: DecisionInput, ctx: ToolContext) -> ToolOutput:
        space = await self.ensure_space()
        page = await self.ensure_page(space, DECISIONS)
        today = now(self.env)
        body = [
            f"*Enregistrée le {today:%Y-%m-%d} par {params.auteur}.*",
            "",
            "**Décision** — " + params.decision,
        ]
        if params.contexte:
            body += ["", "**Contexte** — " + params.contexte]
        if params.consequences:
            body += ["", "**Conséquences** — " + params.consequences]
        payload = {
            "page_id": page,
            "heading": f"{today:%Y-%m-%d} : {params.titre}",
            "content": "\n".join(body),
        }
        await self.action("pages.append", payload, idempotent_on=payload)
        return ToolOutput(content=f"Décision « {params.titre} » enregistrée (page {page}).")


class ReportInput(ToolInput):
    sujet: str = Field(min_length=1, max_length=120, description="Sujet de la réunion ou du point.")
    contenu: str = Field(
        min_length=1,
        max_length=200_000,
        description="Compte rendu en Markdown : participants, points abordés, décisions, actions (qui, quoi, quand).",
    )
    date_cr: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Date AAAA-MM-JJ (défaut : aujourd'hui).",
    )


class ReportTool(_Memory[ReportInput]):
    name = "equipe_compte_rendu"
    description = (
        "Range un compte rendu (réunion, point d'étape) comme sous-page de « Comptes rendus » dans la "
        "mémoire d'équipe (Atelier Wiki)."
    )
    input_model = ReportInput
    requires_approval = True

    def title(self, params: ReportInput) -> str:
        day = params.date_cr or f"{now(self.env):%Y-%m-%d}"
        return f"CR {day} — {params.sujet}"

    def approval_summary(self, params: ReportInput) -> str:
        return (
            f"Ranger le compte rendu « {self.title(params)} » dans la mémoire d'équipe {_STRUCTURE}"
        )

    async def run(self, params: ReportInput, ctx: ToolContext) -> ToolOutput:
        space = await self.ensure_space()
        parent = await self.ensure_page(space, REPORTS)
        payload = {
            "title": self.title(params),
            "content": params.contenu,
            "space_id": space,
            "parent_id": parent,
        }
        page = await self.action("pages.create", payload, idempotent_on=payload)
        return ToolOutput(
            content=f"Compte rendu « {payload['title']} » rangé (page {page.get('id')})."
        )


# ─── Rapports déterministes ───────────────────────────────────────


class ProgressInput(ToolInput):
    projet: str | None = Field(
        default=None, max_length=200, description="Nom ou id d'un projet (défaut : tous)."
    )
    horizon_jours: int = Field(
        default=7, ge=1, le=60, description="Échéances à venir sur ce nombre de jours."
    )


def _project_match(projects: list[Project], wanted: str) -> list[Project]:
    text = wanted.strip().lower()
    exact = [p for p in projects if str(p.id) == text or p.name.lower() == text or p.slug == text]
    return exact or [p for p in projects if text in p.name.lower()]


def _item(i: WorkItem, today: date) -> list[Any]:
    late = (today - i.dueDate).days if i.dueDate else None
    return [
        f"#{i.id}",
        i.title[:80],
        STATUS_LABELS[i.status],
        PRIORITY_LABELS[i.priority],
        f"{i.dueDate:%d/%m}" + (f" ({late} j de retard)" if late and late > 0 else "")
        if i.dueDate
        else "—",
        f"{i.progress} %",
    ]


class ProgressTool(BaseTool[ProgressInput]):
    name = "equipe_point_avancement"
    description = (
        "Point d'avancement calculé depuis Atelier Projets (sans interprétation) : avancement, "
        "tendance, budget, éléments en retard, à échéance, bloqués, jalons. Base d'un point d'équipe."
    )
    input_model = ProgressInput
    expected_errors = (AppError,)

    def __init__(self, env: ToolEnvironment) -> None:
        self.env = env

    async def run(self, params: ProgressInput, ctx: ToolContext) -> ToolOutput:
        client = self.env.projets()
        projects = await client.projects()
        if params.projet:
            projects = _project_match(projects, params.projet)
            if not projects:
                return ToolOutput(
                    content=f"Aucun projet « {params.projet} » dans Atelier Projets.", is_error=True
                )
        today = now(self.env).date()
        horizon = today + timedelta(days=params.horizon_jours)
        lines = [f"# Point d'avancement du {today:%d/%m/%Y}", ""]
        if not projects:
            lines.append("Aucun projet dans Atelier Projets.")
        totals = {"late": 0, "soon": 0, "blocked": 0}
        for project in projects[:20]:
            dash = await client.dashboard(project.id)
            items = await client.work_items(project.id)
            milestones = await client.milestones(project.id)
            active = [i for i in items if i.status not in DONE]
            # Un élément bloqué ou en attente n'apparaît qu'une fois, dans sa propre liste
            blocked = [i for i in active if i.status in ("BLOCKED", "ON_HOLD")]
            moving = [i for i in active if i not in blocked]
            late = sorted(
                (i for i in moving if i.dueDate and i.dueDate < today),
                key=lambda i: i.dueDate or today,
            )
            soon = sorted(
                (i for i in moving if i.dueDate and today <= i.dueDate <= horizon),
                key=lambda i: i.dueDate or today,
            )
            totals["late"] += len(late)
            totals["soon"] += len(soon)
            totals["blocked"] += len(blocked)
            trend = {"AHEAD": "en avance", "ON_TRACK": "dans les temps", "BEHIND": "en retard"}.get(
                dash.trend or "", "non calculée"
            )
            budget = (
                f"{dash.budget.spent.days:g} j passés sur {dash.budget.initial.days:g} j"
                if dash.budget.initial
                else f"{dash.budget.spent.days:g} j passés (pas de budget)"
            )
            lines += [
                f"## {project.name} (projet {project.id})",
                f"- Avancement : {dash.progress.percent:.0f} % ; tendance : {trend} ; budget : {budget}.",
                f"- Éléments : {dash.workItems.done} terminés sur {dash.workItems.total}"
                + (
                    f" ; échéance du projet le {project.dueDate:%d/%m/%Y}"
                    if project.dueDate
                    else ""
                )
                + ".",
            ]
            headers = ["Élément", "Titre", "Statut", "Priorité", "Échéance", "Avancement"]
            for label, chosen in (
                ("En retard", late),
                (f"À échéance d'ici le {horizon:%d/%m}", soon),
                ("Bloqués ou en attente", blocked),
            ):
                if chosen:
                    lines += [
                        "",
                        f"**{label} ({len(chosen)})**",
                        markdown_table(headers, [_item(i, today) for i in chosen[:15]]),
                    ]
                    if len(chosen) > 15:
                        lines.append(f"(+{len(chosen) - 15} autres)")
            missed = [m for m in milestones if not m.reached and m.date < today]
            coming = [m for m in milestones if not m.reached and today <= m.date <= horizon]
            for label, chosen_ms in (
                ("Jalons dépassés non atteints", missed),
                ("Jalons à venir", coming),
            ):
                if chosen_ms:
                    lines.append(
                        f"- {label} : "
                        + " ; ".join(f"« {m.title} » ({m.date:%d/%m})" for m in chosen_ms)
                    )
            lines.append("")
        if len(projects) > 20:
            lines.append(f"({len(projects) - 20} projet(s) de plus non détaillés.)")
        lines.insert(
            2,
            f"**En bref** : {len(projects)} projet(s) ; {totals['late']} élément(s) en retard, "
            f"{totals['soon']} à échéance sous {params.horizon_jours} j, {totals['blocked']} bloqué(s) ou en attente.\n",
        )
        text = "\n".join(lines).rstrip()
        return ToolOutput(
            content=text,
            artifacts=[
                Artifact(
                    kind="markdown", title=f"Point d'avancement {today:%d/%m/%Y}", content=text
                )
            ],
            data={"markdown": text, **totals, "projects": len(projects)},
        )


class FormsDigestInput(ToolInput):
    tous: bool = Field(
        default=False,
        description="Inclure aussi les formulaires fermés (défaut : ouverts seulement).",
    )


class FormsDigestTool(NodeTool[FormsDigestInput]):
    name = "equipe_synthese_formulaires"
    description = (
        "Synthèse AGRÉGÉE des formulaires ouverts d'Atelier Formulaire (effectifs, moyennes ; "
        "jamais de réponse individuelle ni de texte libre). Base d'un point sur les retours."
    )
    input_model = FormsDigestInput
    app = "formulaire"

    async def run(self, params: FormsDigestInput, ctx: ToolContext) -> ToolOutput:
        table = await self.action("forms.list", {})
        forms = [
            r
            for r in table.get("rows", [])
            if isinstance(r, dict) and (params.tous or r.get("accepte_reponses"))
        ]
        today = now(self.env).date()
        lines = [f"# Retours des formulaires au {today:%d/%m/%Y}", ""]
        data: list[dict[str, Any]] = []
        if not forms:
            lines.append("Aucun formulaire ouvert aux réponses.")
        for form in forms[:10]:
            summary = await self.http("GET", f"/api/forms/{form['id']}/summary")
            lines += [
                f"## {form.get('titre')} (formulaire {form.get('id')})",
                summary_text(summary),
                "",
            ]
            data.append(
                {"id": str(form.get("id")), "title": form.get("titre"), **aggregate_only(summary)}
            )
        text = "\n".join(lines).rstrip()
        return ToolOutput(
            content=text,
            artifacts=[
                Artifact(
                    kind="markdown", title=f"Retours des formulaires {today:%d/%m/%Y}", content=text
                )
            ],
            data={"markdown": text, "forms": data},
        )


def equipe_memory_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [MemoryTool(env)]


def equipe_write_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [NoteTool(env), DecisionTool(env), ReportTool(env)]


def equipe_report_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    tools: list[BaseTool[Any]] = []
    if env.settings.projets_base_url:
        tools.append(ProgressTool(env))
    if env.settings.formulaire_base_url:
        tools.append(FormsDigestTool(env))
    return tools
