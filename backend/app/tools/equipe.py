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

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field

from app.schemas.projets import (
    PRIORITY_LABELS,
    STATUS_LABELS,
    Dashboard,
    DashboardBudget,
    Milestone,
    Project,
    WorkItem,
)
from app.suite.http import NodeActionError
from app.tools.base import Artifact, BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.tools.formatting import markdown_table
from app.tools.formulaire import aggregate_only, summary_markdown
from app.tools.http import AppError
from app.tools.suite_node import REPLAYED, NodeTool, as_data, rows_of

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


#: Titre de section imposé par le Wiki à `pages.append` (manifeste : 200 caractères au plus)
HEADING_MAX = 200


def now(env: ToolEnvironment) -> datetime:
    return datetime.now(ZoneInfo(env.settings.timezone))


# ─── Accès à l'espace de l'équipe ─────────────────────────────────


def normalize(title: str) -> str:
    """Comme `normalizeTitle` d'Atelier Wiki : sans accents, minuscules, espaces réduits."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", title) if unicodedata.category(c) != "Mn"
    )
    return " ".join(plain.lower().split())


def _by_id(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("id")))
    except ValueError:
        return 0


class _Memory[InputT: ToolInput](NodeTool[InputT]):
    app = "wiki"

    async def space_id(self) -> str | None:
        # Le Wiki refuse deux espaces de même nom aux accents et à la casse près : même règle ici
        wanted = normalize(SPACE)
        for row in rows_of(self.app, await self.action("spaces.list", {})):
            if normalize(str(row.get("nom") or "")) == wanted:
                return str(row["id"])
        return None

    async def pages(self, space_id: str) -> list[dict[str, Any]]:
        """Pages de l'espace (hors corbeille), les plus récemment modifiées d'abord."""
        table = await self.action("pages.list", {"space_id": space_id, "limit": 1000})
        return rows_of(self.app, table)

    async def page_id(self, space_id: str, title: str) -> str | None:
        """Page de premier niveau de ce titre ; s'il y en a plusieurs, la plus ancienne (toujours
        la même). Au-delà de 1000 pages, recherche par titre."""
        table = await self.action("pages.list", {"space_id": space_id, "limit": 1000})
        rows = rows_of(self.app, table)
        if table.get("truncated"):
            found = await self.action(
                "pages.search", {"query": title, "space_id": space_id, "limit": 50}
            )
            rows = rows_of(self.app, found)
        same = [r for r in rows if r.get("titre") == title and not r.get("parent_id")]
        return str(min(same, key=_by_id)["id"]) if same else None

    async def ensure_space(self) -> str:
        found = await self.space_id()
        if found:
            return found
        try:
            space = await self.http(
                "POST",
                "/api/spaces",
                {"name": SPACE, "icon": "🤝", "description": SPACE_DESCRIPTION},
            )
        except NodeActionError as exc:
            # Créé entre-temps (autre écriture validée en même temps) : on le relit
            if exc.status != 409 or not (found := await self.space_id()):
                raise
            return found
        return str(space["id"])

    async def ensure_page(self, space_id: str, title: str) -> str:
        """Page de structure, créée si absente. Sans clé d'idempotence : une clé constante ferait
        rejouer par le Wiki (30 jours) l'identifiant d'une page mise depuis à la corbeille."""
        found = await self.page_id(space_id, title)
        if found:
            return found
        payload = {"title": title, "content": INTRO[title], "space_id": space_id}
        page = await self.action("pages.create", payload)
        # Deux créations simultanées : on garde partout la plus ancienne
        return await self.page_id(space_id, title) or str(page["id"])


#: Section d'une note ou d'une décision : `## 2026-10-24 …` (en-tête daté écrit par ces outils)
_DATED = re.compile(r"^## (?=\d{4}-\d{2}-\d{2})", re.MULTILINE)
_HEADING = re.compile(r"^(#{1,2})(?=\s)")
_OPEN_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _sections(content: str) -> list[str]:
    """Sections datées d'une page (la plus récente en dernier). Les titres internes d'une note
    (`## Projet`) ne coupent pas la note ; le texte d'avant la première note est ignoré.
    Les textes écrits par ces outils passent par `demote` : aucune de leurs lignes ne peut
    ressembler à un en-tête daté, même dans un bloc de code."""
    starts = [m.start() for m in _DATED.finditer(content)]
    return [
        content[a:b].strip()
        for a, b in zip(starts, [*starts[1:], len(content)], strict=True)
        if content[a:b].strip()
    ]


def demote(text: str) -> str:
    """Prépare un texte ajouté au journal ou au registre :

    - titres `#` et `##` → `###` / `####` hors blocs de code (ils restent sous l'en-tête daté) ;
    - toute ligne `## AAAA-MM-JJ…`, même dans un bloc de code ou un bloc non fermé, reçoit une
      espace en tête : elle ne peut pas passer pour l'en-tête d'une autre note.

    Blocs de code au sens de CommonMark : une barrière se ferme par le même caractère, au moins
    aussi long, sans texte après."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        if fence is None:
            if m := _OPEN_FENCE.match(line):
                fence = m.group(1)
            else:
                line = _HEADING.sub(lambda m: m.group(1) + "##", line, count=1)
        elif re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*", line):
            fence = None
        if _DATED.match(line):
            line = " " + line
        out.append(line)
    return "\n".join(out)


def heading(*parts: str) -> str:
    text = " ".join(" ".join(parts).split())
    return text if len(text) <= HEADING_MAX else text[: HEADING_MAX - 1] + "…"


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
                [r.get("id"), r.get("titre"), r.get("extrait")] for r in rows_of(self.app, table)
            ]
            if not rows:
                return ToolOutput(
                    content=f"Rien dans la mémoire d'équipe pour « {params.recherche} »."
                )
            return ToolOutput(
                content="Pages de la mémoire d'équipe (lire en entier avec wiki_read_page) :\n"
                + as_data(markdown_table(["Id", "Page", "Extrait"], rows), kind="recherche")
            )
        pages = await self.pages(space)
        top = sorted((r for r in pages if not r.get("parent_id")), key=_by_id, reverse=True)
        by_title = {r.get("titre"): r for r in top}  # le plus ancien gagne (comme page_id)
        lines = [f"Mémoire d'équipe (espace « {SPACE} », {len(pages)} page(s))."]
        journal = by_title.get(JOURNAL)
        if journal:
            page = await self.action("pages.get", {"page_id": str(journal["id"])})
            notes = _sections(str(page.get("content") or ""))[-params.entrees :]
            lines.append(f"\nDernières notes du journal ({len(notes)}, la plus récente en bas) :")
            lines.append(
                as_data(
                    "\n\n".join(notes) or "(vide)",
                    kind="journal de l'équipe",
                    limit=20_000,
                    keep="end",
                )
            )
        decisions = by_title.get(DECISIONS)
        if decisions:
            page = await self.action("pages.get", {"page_id": str(decisions["id"])})
            titles = [s.splitlines()[0][3:] for s in _sections(str(page.get("content") or ""))]
            if titles:
                lines.append(f"\nDécisions ({len(titles)}, page {decisions['id']}, 15 dernières) :")
                lines.append(
                    as_data("\n".join(t[:150] for t in titles[-15:]), kind="titres des décisions")
                )
        reports = by_title.get(REPORTS)
        if reports:
            children = sorted(
                (r for r in pages if str(r.get("parent_id")) == str(reports["id"])), key=_by_id
            )
            if children:
                lines.append(f"\nComptes rendus ({len(children)}, 10 derniers) :")
                lines.append(
                    as_data(
                        "\n".join(f"{c.get('titre')} (page {c.get('id')})" for c in children[-10:]),
                        kind="titres des comptes rendus",
                    )
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
        title = heading(
            f"{now(self.env):%Y-%m-%d %H:%M} · {params.auteur}",
            f"— {params.titre}" if params.titre else "",
        )
        payload = {"page_id": page, "heading": title, "content": demote(params.texte)}
        result = await self.run_node("pages.append", payload, idempotent_on=payload)
        return ToolOutput(
            content=f"Note ajoutée au journal de l'équipe (page {page}) : « {title} »"
            + (REPLAYED if result.replayed else "")
            + "."
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
            "heading": heading(f"{today:%Y-%m-%d} : {params.titre}"),
            "content": demote("\n".join(body)),
        }
        result = await self.run_node("pages.append", payload, idempotent_on=payload)
        return ToolOutput(
            content=f"Décision « {params.titre} » enregistrée (page {page})"
            + (REPLAYED if result.replayed else "")
            + "."
        )


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
        # Le Wiki accepte deux pages de même titre : le même compte rendu déjà rangé est signalé,
        # un autre compte rendu du même jour et du même sujet reçoit « (2) », « (3) »…
        children = {
            str(r.get("titre")): str(r.get("id"))
            for r in await self.pages(space)
            if str(r.get("parent_id")) == parent
        }
        base = self.title(params)
        title, n = base, 1
        while title in children:
            existing = await self.action("pages.get", {"page_id": children[title]})
            if str(existing.get("content") or "").strip() == params.contenu.strip():
                return ToolOutput(
                    content=f"Ce compte rendu est déjà rangé : « {title} » (page {children[title]}). "
                    "Rien de nouveau n'a été écrit."
                )
            n += 1
            title = f"{base} ({n})"
        payload = {
            "title": title,
            "content": params.contenu,
            "space_id": space,
            "parent_id": parent,
        }
        # Clé à la minute : une même validation exécutée deux fois ne crée rien en double, mais un
        # compte rendu mis à la corbeille puis redemandé plus tard est recréé (une clé sur le seul
        # contenu ferait rejouer par le Wiki, 30 jours, la page supprimée)
        minute = f"{now(self.env):%Y-%m-%d %H:%M}"
        result = await self.run_node(
            "pages.create", payload, idempotent_on={**payload, "minute": minute}
        )
        return ToolOutput(
            content=f"Compte rendu « {title} » rangé (page {result.data.get('id')})"
            + (REPLAYED if result.replayed else "")
            + "."
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
        detailed = projects[:MAX_PROJECTS]
        totals = {"late": 0, "late_blocked": 0, "soon": 0, "blocked": 0, "over_budget": 0}
        failed: list[str] = []
        sections: list[str] = []
        for project in detailed:
            try:
                dash = await client.dashboard(project.id)
                items = await client.work_items(project.id)
                milestones = await client.milestones(project.id)
            except AppError as exc:
                failed.append(project.name)
                sections += [
                    f"## {project.name} (projet {project.id})",
                    f"- Données indisponibles : {exc}",
                    "",
                ]
                continue
            sections += _project_section(project, dash, items, milestones, today, horizon, totals)
        if not projects:
            sections.append("Aucun projet dans Atelier Projets.")
        if len(projects) > MAX_PROJECTS:
            sections.append(
                f"({len(projects) - MAX_PROJECTS} projet(s) de plus non détaillés ni comptés : "
                "demander un projet précis.)"
            )
        scope = (
            f"{len(detailed)} projet(s) détaillé(s) sur {len(projects)}"
            if len(projects) > len(detailed)
            else f"{len(projects)} projet(s)"
        )
        blocked_late = (
            f" (dont {totals['late_blocked']} bloqué(s))" if totals["late_blocked"] else ""
        )
        brief = (
            f"**En bref** : {scope} ; {totals['late']} élément(s) en retard{blocked_late}, "
            f"{totals['soon']} à échéance sous {params.horizon_jours} j, "
            f"{totals['blocked']} bloqué(s) ou en attente"
            + (
                f", {totals['over_budget']} projet(s) au-delà du budget"
                if totals["over_budget"]
                else ""
            )
            + (f" ; données indisponibles pour : {', '.join(failed)}" if failed else "")
            + ".\n"
        )
        text = "\n".join(
            [f"# Point d'avancement du {today:%d/%m/%Y}", "", brief, *sections]
        ).rstrip()
        return ToolOutput(
            # Noms et titres viennent de Projets : texte délimité pour le modèle, brut ailleurs
            content=as_data(text, kind="point d'avancement", limit=60_000),
            artifacts=[
                Artifact(
                    kind="markdown", title=f"Point d'avancement {today:%d/%m/%Y}", content=text
                )
            ],
            data={
                "markdown": text,
                **totals,
                "projects": len(projects),
                "detailed": len(detailed),
                "failed": failed,
            },
        )


MAX_PROJECTS = 20
TRENDS = {"AHEAD": "en avance", "ON_TRACK": "dans les temps", "BEHIND": "en retard"}


def _budget(b: DashboardBudget) -> tuple[str, bool]:
    """Texte du budget (jours) et dépassement."""
    if b.initial is None or b.initial.days <= 0:
        return f"{b.spent.days:g} j passés (pas de budget)", False
    percent = (
        b.consumedPercent if b.consumedPercent is not None else 100 * b.spent.days / b.initial.days
    )
    over = b.spent.days > b.initial.days
    rest = (
        f"dépassé de {b.spent.days - b.initial.days:g} j"
        if over
        else f"reste {b.remaining.days if b.remaining else b.initial.days - b.spent.days:g} j"
    )
    return f"{b.spent.days:g} j passés sur {b.initial.days:g} j ({percent:.0f} %, {rest})", over


def _project_section(
    project: Project,
    dash: Dashboard,
    items: list[WorkItem],
    milestones: list[Milestone],
    today: date,
    horizon: date,
    totals: dict[str, int],
) -> list[str]:
    active = [i for i in items if i.status not in DONE]
    # Un élément bloqué ou en attente n'apparaît qu'une fois, dans sa propre liste ; il compte
    # pourtant dans le total « en retard » (signalé « dont … bloqués »)
    blocked = [i for i in active if i.status in ("BLOCKED", "ON_HOLD")]
    moving = [i for i in active if i not in blocked]
    late = sorted((i for i in moving if i.dueDate and i.dueDate < today), key=_due)
    soon = sorted((i for i in moving if i.dueDate and today <= i.dueDate <= horizon), key=_due)
    late_blocked = [i for i in blocked if i.dueDate and i.dueDate < today]
    totals["late"] += len(late) + len(late_blocked)
    totals["late_blocked"] += len(late_blocked)
    totals["soon"] += len(soon)
    totals["blocked"] += len(blocked)
    budget, over = _budget(dash.budget)
    totals["over_budget"] += int(over)
    due = ""
    if project.dueDate:
        overdue = (today - project.dueDate).days
        due = f" ; échéance du projet le {project.dueDate:%d/%m/%Y}" + (
            f" (DÉPASSÉE de {overdue} j)" if overdue > 0 and dash.progress.percent < 100 else ""
        )
    lines = [
        f"## {project.name} (projet {project.id})",
        f"- Avancement : {dash.progress.percent:.0f} % ; tendance : "
        f"{TRENDS.get(dash.trend or '', 'non calculée')} ; budget : {budget}.",
        f"- Éléments : {dash.workItems.done} terminés sur {dash.workItems.total}{due}.",
    ]
    headers = ["Élément", "Titre", "Statut", "Priorité", "Échéance", "Avancement"]
    for label, chosen in (
        ("En retard", late),
        (f"À échéance d'ici le {horizon:%d/%m}", soon),
        ("Bloqués ou en attente", sorted(blocked, key=_due)),
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
    for label, chosen_ms in (("Jalons dépassés non atteints", missed), ("Jalons à venir", coming)):
        if chosen_ms:
            lines.append(
                f"- {label} : " + " ; ".join(f"« {m.title} » ({m.date:%d/%m})" for m in chosen_ms)
            )
    lines.append("")
    return lines


def _due(i: WorkItem) -> date:
    return i.dueDate or date.max


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
            for r in rows_of(self.app, table)
            if (params.tous or r.get("accepte_reponses")) and str(r.get("id", "")).isdigit()
        ]
        today = now(self.env).date()
        lines = [f"# Retours des formulaires au {today:%d/%m/%Y}", ""]
        data: list[dict[str, Any]] = []
        if not forms:
            lines.append("Aucun formulaire ouvert aux réponses.")
        for form in forms[:10]:
            summary = await self.http("GET", f"/api/forms/{int(form['id'])}/summary")
            lines += [
                f"## {form.get('titre')} (formulaire {form.get('id')})",
                summary_markdown(summary),
                "",
            ]
            data.append(
                {"id": str(form.get("id")), "title": form.get("titre"), **aggregate_only(summary)}
            )
        text = "\n".join(lines).rstrip()
        return ToolOutput(
            content=as_data(text, kind="retours des formulaires", limit=40_000),
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
