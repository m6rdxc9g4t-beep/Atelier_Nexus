"""Connecteur Atelier Projets — point d'entrée unique vers son API (`:3000/api`).

Lecture libre ; écritures (créer une story ou un élément, modifier un élément, saisir du temps,
journaliser) marquées `requires_approval` : l'agent attend la validation de l'utilisateur, sur un
résumé qui décrit exactement ce qui sera envoyé.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from pydantic import Field

from app.core.config import Settings
from app.schemas.projets import (
    PRIORITY_LABELS,
    STATUS_LABELS,
    Dashboard,
    Duration,
    Health,
    ImportPreview,
    ImportResult,
    LogEntryCreate,
    Milestone,
    Priority,
    Project,
    ProjectTree,
    Status,
    Story,
    StoryCreate,
    TimeEntry,
    TimeEntryCreate,
    Timesheet,
    WorkItem,
    WorkItemCreate,
    WorkItemDetail,
    WorkItemType,
    WorkItemUpdate,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.clock import DEFAULT_TIMEZONE, local_today
from app.tools.formatting import (
    TableType,
    atelier_table,
    data_artifact,
    fmt,
    table_for_model,
    table_hint,
)
from app.tools.http import AppClient, AppError, safe_id


def _import_params(project_id: int | None, item_type: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if project_id is not None:
        params["projectId"] = safe_id(project_id)
    if item_type:
        params["type"] = item_type
    return params


# ═══ Client ═══════════════════════════════════════════════════════


class ProjetsClient(AppClient):
    app = "projets"
    label = "Atelier Projets"

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> ProjetsClient | None:
        if not settings.projets_base_url:
            return None
        client = cls(settings.projets_base_url, timeout=settings.apps_timeout, transport=transport)
        token = settings.projets_import_token
        client.import_token = token.get_secret_value() if token else None
        client.timezone = settings.timezone
        return client

    #: Jeton ATELIER_IMPORT_TOKEN d'Atelier Projets (import depuis Tab), s'il est configuré
    import_token: str | None = None
    #: Fuseau de l'utilisateur (`TIMEZONE`) : « aujourd'hui » des retards et des jalons
    timezone: str = DEFAULT_TIMEZONE

    async def health(self) -> Health:
        return self.parse(Health, await self.request("GET", "health"))

    def _import_headers(self, idempotency_key: str | None) -> dict[str, str]:
        headers = {"X-Atelier-Schema-Version": "2.1.0"}
        if self.import_token:
            headers["Authorization"] = f"Bearer {self.import_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def preview_tab_import(
        self, envelope: dict[str, Any], *, project_id: int | None, item_type: str | None
    ) -> ImportPreview:
        """Aperçu de l'import d'une table Atelier Tab : rien n'est modifié."""
        data = await self.request(
            "POST",
            "imports/atelier-tab/preview",
            json_body=envelope,
            params=_import_params(project_id, item_type),
            headers=self._import_headers(None),
        )
        return self.parse(ImportPreview, data)

    async def import_tab(
        self,
        envelope: dict[str, Any],
        *,
        project_id: int | None,
        item_type: str | None,
        idempotency_key: str,
    ) -> ImportResult:
        """Import (création / mise à jour par `record_id`), idempotent par `Idempotency-Key`."""
        data = await self.request(
            "POST",
            "imports/atelier-tab",
            json_body=envelope,
            params=_import_params(project_id, item_type),
            headers=self._import_headers(idempotency_key),
        )
        result = self.parse(ImportResult, data)
        headers = self.last_headers
        result.replayed = bool(headers and headers.get("idempotency-replayed") == "true")
        return result

    async def projects(self) -> list[Project]:
        return self.parse_list(Project, await self.request("GET", "projects"))

    async def dashboard(self, project_id: int) -> Dashboard:
        data = await self.request("GET", f"projects/{safe_id(project_id)}/dashboard")
        return self.parse(Dashboard, data)

    async def tree(self, project_id: int) -> ProjectTree:
        return self.parse(
            ProjectTree, await self.request("GET", f"projects/{safe_id(project_id)}/tree")
        )

    async def work_items(
        self,
        project_id: int,
        *,
        status: list[str] | None = None,
        types: list[str] | None = None,
        story_id: int | None = None,
        q: str | None = None,
    ) -> list[WorkItem]:
        params: list[tuple[str, str | int]] = [("status", s) for s in status or []]
        params += [("type", t) for t in types or []]
        if story_id:
            params.append(("storyId", safe_id(story_id)))
        if q:
            params.append(("q", q))
        data = await self.request(
            "GET", f"projects/{safe_id(project_id)}/work-items", params=params
        )
        return self.parse_list(WorkItem, data)

    async def work_item(self, work_item_id: int) -> WorkItemDetail:
        data = await self.request("GET", f"work-items/{safe_id(work_item_id)}")
        return self.parse(WorkItemDetail, data)

    async def timesheet(self, project_id: int) -> Timesheet:
        data = await self.request("GET", f"projects/{safe_id(project_id)}/timesheet")
        return self.parse(Timesheet, data)

    async def milestones(self, project_id: int) -> list[Milestone]:
        data = await self.request("GET", f"projects/{safe_id(project_id)}/milestones")
        return self.parse_list(Milestone, data)

    # ─── Écritures (appelées seulement après validation) ──────────

    async def create_story(self, epic_id: int, body: StoryCreate) -> Story:
        data = await self.request(
            "POST",
            f"epics/{safe_id(epic_id)}/stories",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return self.parse(Story, data)

    async def create_work_item(self, story_id: int, body: WorkItemCreate) -> WorkItemDetail:
        data = await self.request(
            "POST",
            f"stories/{safe_id(story_id)}/work-items",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return self.parse(WorkItemDetail, data)

    async def update_work_item(self, work_item_id: int, body: WorkItemUpdate) -> WorkItemDetail:
        data = await self.request(
            "PATCH",
            f"work-items/{safe_id(work_item_id)}",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return self.parse(WorkItemDetail, data)

    async def add_time_entry(self, work_item_id: int, body: TimeEntryCreate) -> TimeEntry:
        data = await self.request(
            "POST",
            f"work-items/{safe_id(work_item_id)}/time-entries",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return self.parse(TimeEntry, data)

    async def add_log_entry(self, work_item_id: int, body: LogEntryCreate) -> WorkItemDetail:
        data = await self.request(
            "POST",
            f"work-items/{safe_id(work_item_id)}/log-entries",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return self.parse(WorkItemDetail, data)


# ═══ Mise en forme ════════════════════════════════════════════════


#: Statuts terminés : un élément dans l'un d'eux n'est jamais « en retard »
DONE_STATUSES = frozenset({"RESOLVED", "CLOSED", "REJECTED"})


def hours(d: Duration | None) -> float | None:
    return None if d is None else d.hours


def is_over_budget(item: WorkItem) -> bool:
    """Temps passé au-delà de l'estimation (écart calculé par Atelier Projets)."""
    return item.balance is not None and item.balance.kind == "OVER"


def is_overdue(item: WorkItem, today: date) -> bool:
    """Échéance dépassée et élément non terminé."""
    return item.dueDate is not None and item.dueDate < today and item.status not in DONE_STATUSES


def balance_text(item: WorkItem) -> str:
    if item.balance is None:
        return "—"
    delta = item.balance.delta.hours
    return {
        "UNDER": f"sous le budget ({delta:+g} h)",
        "ON_BUDGET": "dans le budget",
        "OVER": f"dépassement ({delta:+g} h)",
        "REMAINING": f"reste {delta:g} h",
    }[item.balance.kind]


def work_item_rows(items: list[WorkItem]) -> tuple[list[str], list[list[Any]]]:
    headers = ["id", "type", "statut", "priorité", "titre", "avancement %", "estimé h", "passé h",
               "écart", "échéance"]  # fmt: skip
    rows = [
        [
            i.id,
            i.type,
            STATUS_LABELS[i.status],
            PRIORITY_LABELS[i.priority],
            i.title,
            i.progress,
            hours(i.estimate),
            i.spent.hours,
            balance_text(i),
            i.dueDate.isoformat() if i.dueDate else None,
        ]  # fmt: skip
        for i in items
    ]
    return headers, rows


#: Colonnes `atelier-table/1` des éléments (mêmes clés que le jeu `work-items` de Projets)
WORK_ITEM_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("id", "Identifiant", "number"), ("project_id", "Projet", "number"),
    ("story_id", "Story", "number"), ("type", "Type", "string"), ("status", "Statut", "string"),
    ("status_label", "Statut (libellé)", "string"), ("priority", "Priorité", "string"),
    ("title", "Titre", "string"), ("progress", "Avancement %", "number"),
    ("estimated_hours", "Heures estimées", "number"), ("spent_hours", "Heures passées", "number"),
    ("balance", "Écart", "string"), ("start_date", "Début", "date"), ("due_date", "Échéance", "date"),
)  # fmt: skip
PROJECT_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("id", "Identifiant", "number"), ("name", "Nom", "string"), ("slug", "Slug", "string"),
    ("budget_hours", "Budget h", "number"), ("hours_per_day", "Heures par jour", "number"),
    ("start_date", "Début", "date"), ("due_date", "Échéance", "date"),
    ("github", "Dépôt GitHub", "string"),
)  # fmt: skip
TIMESHEET_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("id", "Identifiant", "number"), ("type", "Type", "string"), ("title", "Titre", "string"),
    ("status", "Statut", "string"), ("estimated_hours", "Heures estimées", "number"),
    ("spent_hours", "Heures passées", "number"), ("balance", "Écart", "string"),
)  # fmt: skip
MILESTONE_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("id", "Identifiant", "number"), ("title", "Titre", "string"), ("date", "Date", "date"),
    ("reached", "Atteint", "boolean"), ("phase_id", "Phase", "number"),
)  # fmt: skip


def work_items_table(items: list[WorkItem], label: str) -> dict[str, Any]:
    return atelier_table(
        "work-items",
        label,
        WORK_ITEM_COLUMNS,
        [
            [
                i.id,
                i.projectId,
                i.storyId,
                i.type,
                i.status,
                STATUS_LABELS[i.status],
                i.priority,
                i.title,
                i.progress,
                hours(i.estimate),
                i.spent.hours,
                balance_text(i),
                i.startDate,
                i.dueDate,
            ]  # fmt: skip
            for i in items
        ],
    )


def work_item_record(w: WorkItem) -> dict[str, Any]:
    """Fiche d'un élément (clés `snake_case`) : sortie structurée des lectures et écritures."""
    record: dict[str, Any] = {
        "id": w.id,
        "project_id": w.projectId,
        "story_id": w.storyId,
        "type": w.type,
        "status": w.status,
        "priority": w.priority,
        "title": w.title,
        "progress": w.progress,
        "estimated_hours": hours(w.estimate),
        "spent_hours": w.spent.hours,
        "start_date": w.startDate.isoformat() if w.startDate else None,
        "due_date": w.dueDate.isoformat() if w.dueDate else None,
    }
    if isinstance(w, WorkItemDetail):
        record["path"] = {
            level: {"id": ref.id, "code": ref.code, "title": ref.title}
            for level, ref in (
                ("phase", w.path.phase),
                ("epic", w.path.epic),
                ("story", w.path.story),
            )
        }
    return record


# ═══ Outils de lecture ════════════════════════════════════════════


class _ProjetsTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError, ValueError)

    def __init__(self, client: ProjetsClient) -> None:
        self.client = client


class NoInput(ToolInput):
    pass


class ProjectInput(ToolInput):
    project_id: int = Field(description="Identifiant du projet (projets_list_projects).")


class ListProjectsTool(_ProjetsTool[NoInput]):
    name = "projets_list_projects"
    description = (
        "Liste les projets d'Atelier Projets : identifiant, nom, budget, dates, dépôt GitHub."
    )
    input_model = NoInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*PROJECT_COLUMNS)

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        projects = await self.client.projects()
        data = atelier_table(
            "projects",
            "Projets",
            PROJECT_COLUMNS,
            [
                [
                    p.id,
                    p.name,
                    p.slug,
                    hours(p.budget),
                    p.hoursPerDay,
                    p.startDate,
                    p.dueDate,
                    f"{p.github.owner}/{p.github.repo}" if p.github else None,
                ]  # fmt: skip
                for p in projects
            ],
        )
        if not projects:
            return ToolOutput(content="Aucun projet dans Atelier Projets.", data=data)
        rows = [
            [
                p.id,
                p.name,
                hours(p.budget),
                p.hoursPerDay,
                p.startDate,
                p.dueDate,
                f"{p.github.owner}/{p.github.repo}" if p.github else None,
            ]  # fmt: skip
            for p in projects
        ]
        text, _ = table_for_model(
            ["id", "nom", "budget h", "h/jour", "début", "échéance", "github"], rows, noun="projet"
        )
        return ToolOutput(content=text, data=data)


class DashboardTool(_ProjetsTool[ProjectInput]):
    name = "projets_dashboard"
    description = (
        "Tableau de bord d'un projet : budget consommé, avancement pondéré, tendance "
        "(en avance / dans les temps / en retard), éléments terminés et répartition par statut."
    )
    input_model = ProjectInput

    async def run(self, params: ProjectInput, ctx: ToolContext) -> ToolOutput:
        d = await self.client.dashboard(params.project_id)
        trend = {"AHEAD": "en avance", "ON_TRACK": "dans les temps", "BEHIND": "en retard"}
        lines = [
            f"Projet « {d.project.name} » (id {d.project.id}), {d.project.hoursPerDay:g} h/jour.",
            f"- Budget : {fmt(hours(d.budget.initial))} h ; consommé {d.budget.spent.hours:g} h"
            f" ({fmt(d.budget.consumedPercent)} %) ; reste {fmt(hours(d.budget.remaining))} h.",
            f"- Avancement pondéré : {d.progress.percent:g} % "
            f"(acquis {d.progress.earned.hours:g} h sur {d.progress.planned.hours:g} h prévues).",
            f"- Tendance : {trend.get(d.trend or '', 'non calculable (pas de budget)')}.",
            f"- Éléments : {d.workItems.done}/{d.workItems.total} terminés ({fmt(d.workItems.donePercent)} %).",
            "- Par statut : "
            + ", ".join(f"{STATUS_LABELS[b.status]} {b.total}" for b in d.histogram if b.total),
        ]
        return ToolOutput(content="\n".join(lines))


class StructureTool(_ProjetsTool[ProjectInput]):
    name = "projets_structure"
    description = (
        "Arborescence d'un projet : phases > epics > stories avec identifiants, codes, avancement "
        "et temps. Indispensable pour trouver le story_id avant de créer un élément."
    )
    input_model = ProjectInput

    async def run(self, params: ProjectInput, ctx: ToolContext) -> ToolOutput:
        tree = await self.client.tree(params.project_id)
        a = tree.aggregate
        lines = [
            f"Projet « {tree.project.name} » : {a.workItems} éléments, avancement {a.progress:g} %, "
            f"estimé {a.estimate.hours:g} h, passé {a.spent.hours:g} h."
        ]
        for ph in tree.phases:
            lines.append(
                f"- Phase {ph.code} « {ph.title} » (id {ph.id}) — {ph.aggregate.progress:g} %"
            )
            for ep in ph.epics:
                lines.append(
                    f"  - Epic {ep.code} « {ep.title} » (id {ep.id}) — {ep.aggregate.progress:g} %"
                )
                for st in ep.stories:
                    lines.append(
                        f"    - Story {st.code} « {st.title} » (story_id {st.id}) — "
                        f"{st.aggregate.workItems} éléments, {STATUS_LABELS[st.aggregate.status]}"
                    )
        if tree.criticalPath:
            lines.append(
                "Chemin critique (éléments) : " + ", ".join(f"#{i}" for i in tree.criticalPath)
            )
        return ToolOutput(content="\n".join(lines))


class ListWorkItemsInput(ToolInput):
    project_id: int
    status: list[Status] = Field(default_factory=list, description="Filtre statuts (vide = tous).")
    types: list[WorkItemType] = Field(default_factory=list, description="FEATURE, TASK, BUG.")
    story_id: int | None = None
    query: str | None = Field(default=None, max_length=200, description="Texte du titre ou #id.")
    over_budget: bool = Field(
        default=False, description="Seulement les éléments en dépassement (passé > estimé)."
    )
    overdue: bool = Field(
        default=False,
        description="Seulement les éléments en retard (échéance passée, non terminés).",
    )


class ListWorkItemsTool(_ProjetsTool[ListWorkItemsInput]):
    name = "projets_list_work_items"
    description = (
        "Liste les éléments (FEATURE / TASK / BUG) d'un projet avec statut, priorité, avancement, "
        "estimé, temps passé, écart au budget et échéance. Filtres, cumulés : statuts, types, "
        "story, texte, over_budget (en dépassement), overdue (en retard). Ex. éléments bloqués : "
        '{"project_id": 1, "status": ["BLOCKED"]} ; en dépassement : {"project_id": 1, '
        '"over_budget": true}.'
    )
    input_model = ListWorkItemsInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*WORK_ITEM_COLUMNS)

    async def run(self, params: ListWorkItemsInput, ctx: ToolContext) -> ToolOutput:
        items = await self.client.work_items(
            params.project_id,
            status=list(params.status),
            types=list(params.types),
            story_id=params.story_id,
            q=params.query,
        )
        # Dépassement et retard : calculés ici (l'API ne les filtre pas), d'après l'écart
        # d'Atelier Projets et la date du jour de l'utilisateur
        today = local_today(self.client.timezone)
        if params.over_budget:
            items = [i for i in items if is_over_budget(i)]
        if params.overdue:
            items = [i for i in items if is_overdue(i, today)]
        data = work_items_table(items, f"Éléments du projet {params.project_id}")
        if not items:
            return ToolOutput(content="Aucun élément ne correspond.", data=data)
        headers, rows = work_item_rows(items)
        text, truncated = table_for_model(headers, rows, noun="élément")
        if params.overdue:
            text = f"En retard au {today.isoformat()} : {text}"
        if truncated:  # le modèle ne lit pas l'artefact : il affine plutôt que de deviner
            text += (
                "\nListe coupée : affine avec status, types, story_id, over_budget ou overdue "
                "pour lire les autres éléments."
            )
        artifact = data_artifact(
            f"Éléments du projet {params.project_id}",
            headers,
            rows,
            numeric={"id", "avancement %", "estimé h", "passé h"},
            metadata={"source": "projets", "project_id": params.project_id},
        )
        return ToolOutput(content=text, artifacts=[artifact], data=data)


class WorkItemInput(ToolInput):
    work_item_id: int = Field(description="Identifiant #ID de l'élément.")


class WorkItemTool(_ProjetsTool[WorkItemInput]):
    name = "projets_work_item"
    description = (
        "Détail d'un élément : chemin (phase / epic / story), description et critères, journal "
        "d'avancement, saisies de temps, commits et pull requests liés, dépendances."
    )
    input_model = WorkItemInput
    output_format = "json"
    output_hint = {"fields": [c[0] for c in WORK_ITEM_COLUMNS if c[0] != "status_label"] + ["path"]}

    async def run(self, params: WorkItemInput, ctx: ToolContext) -> ToolOutput:
        w = await self.client.work_item(params.work_item_id)
        p = w.path
        lines = [
            f"#{w.id} {w.type} « {w.title} » — {STATUS_LABELS[w.status]}, priorité "
            f"{PRIORITY_LABELS[w.priority]}, {w.progress} %.",
            f"Chemin : phase {p.phase.code} « {p.phase.title} » › epic {p.epic.code} « {p.epic.title} » "
            f"› story {p.story.code} « {p.story.title} » (story_id {p.story.id}).",
            f"Temps : estimé {fmt(hours(w.estimate))} h, passé {w.spent.hours:g} h, {balance_text(w)}.",
        ]
        if w.dueDate:
            lines.append(f"Échéance : {w.dueDate.isoformat()}.")
        if w.description:
            lines += ["", "Description :", w.description[:4000]]
        if w.implementationLog:
            lines += ["", "Journal d'avancement (fin) :", w.implementationLog[-3000:]]
        if w.timeEntries:
            lines += ["", "Saisies de temps récentes :"]
            lines += [
                f"- {t.spentOn.isoformat()} : {t.duration.hours:g} h — {t.comment or 'sans commentaire'}"
                for t in w.timeEntries[:10]
            ]
        if w.commits:
            lines += ["", "Commits liés :"]
            lines += [f"- {c.shortHash} {c.message.splitlines()[0]}" for c in w.commits[:10]]
        if w.pullRequests:
            lines += ["", "Pull requests :"]
            lines += [f"- #{pr.number} {pr.title} ({pr.state})" for pr in w.pullRequests]
        if w.predecessors:
            lines.append(
                "Dépend de : "
                + ", ".join(f"#{n.id} ({STATUS_LABELS[n.status]})" for n in w.predecessors)
            )
        return ToolOutput(content="\n".join(lines), data=work_item_record(w))


class TimesheetTool(_ProjetsTool[ProjectInput]):
    name = "projets_timesheet"
    description = (
        "Feuille de temps d'un projet : estimé, passé, reste et écart par élément, avec totaux."
    )
    input_model = ProjectInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*TIMESHEET_COLUMNS)

    async def run(self, params: ProjectInput, ctx: ToolContext) -> ToolOutput:
        ts = await self.client.timesheet(params.project_id)
        t = ts.totals
        headers = ["id", "type", "titre", "statut", "estimé h", "passé h"]
        rows = [
            [r.id, r.type, r.title, STATUS_LABELS[r.status], hours(r.estimate), r.spent.hours]
            for r in ts.rows
        ]
        text, _ = table_for_model(headers, rows, noun="élément")
        summary = (
            f"Totaux : {t.count} éléments, {t.done} terminés ({fmt(t.donePercent)} %), estimé "
            f"{t.estimate.hours:g} h, passé {t.spent.hours:g} h, reste {t.remaining.hours:g} h."
        )
        artifact = data_artifact(
            f"Feuille de temps — projet {params.project_id}", headers, rows,
            numeric={"id", "estimé h", "passé h"}, metadata={"source": "projets"},
        )  # fmt: skip
        data = atelier_table(
            "timesheet",
            f"Feuille de temps — projet {params.project_id}",
            TIMESHEET_COLUMNS,
            [
                [
                    r.id,
                    r.type,
                    r.title,
                    r.status,
                    hours(r.estimate),
                    r.spent.hours,
                    r.balance.kind if r.balance else None,
                ]  # fmt: skip
                for r in ts.rows
            ],
        )
        return ToolOutput(content=f"{summary}\n{text}", artifacts=[artifact], data=data)


class MilestonesTool(_ProjetsTool[ProjectInput]):
    name = "projets_milestones"
    description = "Jalons d'un projet avec date et état (atteint ou non)."
    input_model = ProjectInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*MILESTONE_COLUMNS)

    async def run(self, params: ProjectInput, ctx: ToolContext) -> ToolOutput:
        ms = await self.client.milestones(params.project_id)
        data = atelier_table(
            "milestones",
            f"Jalons — projet {params.project_id}",
            MILESTONE_COLUMNS,
            [[m.id, m.title, m.date, m.reached, m.phaseId] for m in ms],
        )
        if not ms:
            return ToolOutput(content="Aucun jalon.", data=data)
        today = local_today(self.client.timezone)
        lines = [
            f"- {m.date.isoformat()} « {m.title} » : "
            + ("atteint" if m.reached else ("en retard" if m.date < today else "à venir"))
            for m in ms
        ]
        return ToolOutput(content="\n".join(lines), data=data)


# ═══ Outils d'écriture (validation requise) ═══════════════════════


#: Titre d'Atelier Projets (`Title` de schemas/common.ts) : au moins un caractère visible, refusé
#: avant la carte de validation plutôt qu'après (« »)
TITLE = r"\S"


def _preview(text: str, size: int = 80) -> str:
    """Début d'un texte, sur une ligne, pour un résumé de validation."""
    flat = " ".join(text.split())
    return flat if len(flat) <= size else flat[: size - 1].rstrip() + "…"


class CreateStoryInput(ToolInput):
    epic_id: int = Field(description="Epic parent (identifiant « id » vu par projets_structure).")
    title: str = Field(
        min_length=1, max_length=200, pattern=TITLE, description="Livrable attendu de la story."
    )
    description: str | None = Field(
        default=None,
        max_length=20_000,
        description="Markdown : objectif, périmètre, hors périmètre.",
    )
    start_date: date | None = None
    due_date: date | None = None


class CreateStoryTool(_ProjetsTool[CreateStoryInput]):
    name = "projets_create_story"
    description = (
        "Crée une story (conteneur de Projets) dans un epic, pour y ranger ensuite ses FEATURE / "
        "TASK / BUG avec projets_create_work_item. Action soumise à validation."
    )
    input_model = CreateStoryInput
    requires_approval = True
    output_format = "json"
    output_hint = {"fields": ["id", "epic_id", "title", "start_date", "due_date"]}

    def approval_summary(self, params: CreateStoryInput) -> str:
        extra = []
        if params.start_date:
            extra.append(f"début {params.start_date.isoformat()}")
        if params.due_date:
            extra.append(f"échéance {params.due_date.isoformat()}")
        if params.description:
            extra.append(f"description « {_preview(params.description, 60)} »")
        more = f" ({', '.join(extra)})" if extra else ""
        return f"Créer la story « {params.title} » dans l'epic {params.epic_id}{more}"

    async def run(self, params: CreateStoryInput, ctx: ToolContext) -> ToolOutput:
        story = await self.client.create_story(
            params.epic_id,
            StoryCreate(
                title=params.title,
                description=params.description,
                startDate=params.start_date,
                dueDate=params.due_date,
            ),
        )
        return ToolOutput(
            content=f"Story #{story.id} « {story.title} » créée dans l'epic {story.epicId}. Ses "
            f"éléments se créent avec projets_create_work_item (story_id {story.id}).",
            data={
                "id": story.id,
                "epic_id": story.epicId,
                "title": story.title,
                "start_date": story.startDate.isoformat() if story.startDate else None,
                "due_date": story.dueDate.isoformat() if story.dueDate else None,
            },
        )


class CreateWorkItemInput(ToolInput):
    story_id: int = Field(description="Story parente (voir projets_structure).")
    type: WorkItemType
    title: str = Field(min_length=1, max_length=200, pattern=TITLE)
    description: str | None = Field(
        default=None, description="Markdown : objectif + critères d'acceptation."
    )
    priority: Priority | None = None
    estimated_hours: float | None = Field(default=None, gt=0, le=10_000)
    due_date: date | None = None


class CreateWorkItemTool(_ProjetsTool[CreateWorkItemInput]):
    name = "projets_create_work_item"
    description = "Crée une FEATURE, TASK ou BUG dans une story. Action soumise à la validation de l'utilisateur."
    input_model = CreateWorkItemInput
    requires_approval = True
    output_format = "json"

    def approval_summary(self, params: CreateWorkItemInput) -> str:
        extra = ""
        if params.estimated_hours:
            extra += f", {params.estimated_hours:g} h estimées"
        if params.priority:
            extra += f", priorité {PRIORITY_LABELS[params.priority]}"
        if params.due_date:
            extra += f", échéance {params.due_date.isoformat()}"
        return f"Créer la {params.type} « {params.title} » dans la story {params.story_id}{extra}"

    async def run(self, params: CreateWorkItemInput, ctx: ToolContext) -> ToolOutput:
        body = WorkItemCreate(
            type=params.type,
            title=params.title,
            description=params.description,
            priority=params.priority,
            estimatedHours=params.estimated_hours,
            dueDate=params.due_date,
        )
        created = await self.client.create_work_item(params.story_id, body)
        return ToolOutput(
            content=f"Élément #{created.id} « {created.title} » créé ({STATUS_LABELS[created.status]}).",
            data=work_item_record(created),
        )


class UpdateWorkItemInput(ToolInput):
    work_item_id: int
    title: str | None = Field(default=None, min_length=1, max_length=200, pattern=TITLE)
    description: str | None = Field(
        default=None,
        max_length=20_000,
        description="Nouvelle description Markdown COMPLÈTE (remplace l'actuelle).",
    )
    status: Status | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    priority: Priority | None = None
    estimated_hours: float | None = Field(default=None, gt=0, le=10_000)
    due_date: date | None = None


#: Statuts qui imposent 100 % d'avancement (Nexus l'impose même si un autre avancement est donné)
FULL_PROGRESS = frozenset({"RESOLVED", "CLOSED"})


class UpdateWorkItemTool(_ProjetsTool[UpdateWorkItemInput]):
    name = "projets_update_work_item"
    description = (
        "Modifie un élément : titre, description, statut, avancement, priorité, estimation ou "
        "échéance (seuls les champs donnés changent). RESOLVED et CLOSED imposent 100 %. "
        "Action soumise à validation."
    )
    input_model = UpdateWorkItemInput
    requires_approval = True
    output_format = "json"

    def approval_summary(self, params: UpdateWorkItemInput) -> str:
        changes = []
        if params.title:
            changes.append(f"titre « {params.title} »")
        if params.description is not None and not params.description.strip():
            changes.append("description effacée")
        elif params.description is not None:
            changes.append(
                f"description remplacée ({len(params.description)} caractères : "
                f"« {_preview(params.description, 60)} »)"
            )
        if params.status:
            changes.append(f"statut « {STATUS_LABELS[params.status]} »")
        if params.status in FULL_PROGRESS and params.progress not in (None, 100):
            changes.append(
                f"avancement 100 % (imposé par « {STATUS_LABELS[params.status]} », "
                f"au lieu de {params.progress} %)"
            )
        elif params.progress is not None:
            changes.append(f"avancement {params.progress} %")
        elif params.status in FULL_PROGRESS:
            changes.append("avancement 100 % (fixé par Atelier Projets pour ce statut)")
        if params.priority:
            changes.append(f"priorité {PRIORITY_LABELS[params.priority]}")
        if params.estimated_hours:
            changes.append(f"estimation {params.estimated_hours:g} h")
        if params.due_date:
            changes.append(f"échéance {params.due_date.isoformat()}")
        return f"Modifier l'élément #{params.work_item_id} : " + (
            ", ".join(changes) or "aucun changement"
        )

    async def run(self, params: UpdateWorkItemInput, ctx: ToolContext) -> ToolOutput:
        progress = params.progress
        if params.status in FULL_PROGRESS and progress not in (None, 100):
            progress = 100  # règle d'Atelier Projets, annoncée dans le résumé de validation
        body = WorkItemUpdate(
            title=params.title,
            description=params.description,
            status=params.status,
            progress=progress,
            priority=params.priority,
            estimatedHours=params.estimated_hours,
            dueDate=params.due_date,
        )
        if not body.model_dump(exclude_none=True):
            return ToolOutput(content="Aucun changement demandé.", is_error=True)
        updated = await self.client.update_work_item(params.work_item_id, body)
        return ToolOutput(
            content=f"#{updated.id} mis à jour : {STATUS_LABELS[updated.status]}, {updated.progress} %.",
            data=work_item_record(updated),
        )


class AddTimeEntryInput(ToolInput):
    work_item_id: int
    hours: float = Field(ge=0.01, le=24)
    spent_on: date | None = Field(default=None, description="Jour (défaut : aujourd'hui).")
    comment: str | None = Field(default=None, max_length=2000)


class AddTimeEntryTool(_ProjetsTool[AddTimeEntryInput]):
    name = "projets_add_time_entry"
    description = "Saisit du temps passé sur un élément. Action soumise à validation."
    input_model = AddTimeEntryInput
    requires_approval = True
    output_format = "json"

    def approval_summary(self, params: AddTimeEntryInput) -> str:
        day = params.spent_on.isoformat() if params.spent_on else "aujourd'hui"
        note = f" — « {_preview(params.comment)} »" if params.comment else ""
        return f"Saisir {params.hours:g} h sur #{params.work_item_id} ({day}){note}"

    async def run(self, params: AddTimeEntryInput, ctx: ToolContext) -> ToolOutput:
        entry = await self.client.add_time_entry(
            params.work_item_id,
            TimeEntryCreate(hours=params.hours, spentOn=params.spent_on, comment=params.comment),
        )
        return ToolOutput(
            content=f"{entry.duration.hours:g} h saisies le {entry.spentOn.isoformat()} sur #{entry.workItemId}.",
            data={
                "id": entry.id,
                "work_item_id": entry.workItemId,
                "spent_on": entry.spentOn.isoformat(),
                "hours": entry.duration.hours,
                "comment": entry.comment,
            },
        )


class AddLogEntryInput(ToolInput):
    work_item_id: int
    text: str = Field(min_length=1, max_length=20_000, description="Ce qui a été fait (Markdown).")
    hours: float | None = Field(
        default=None,
        ge=0,
        le=24,
        description="Heures citées dans l'en-tête de l'entrée (ne saisit pas de temps).",
    )


class AddLogEntryTool(_ProjetsTool[AddLogEntryInput]):
    name = "projets_add_log_entry"
    description = "Ajoute une entrée horodatée au journal d'avancement d'un élément. Action soumise à validation."
    input_model = AddLogEntryInput
    requires_approval = True
    output_format = "json"

    def approval_summary(self, params: AddLogEntryInput) -> str:
        mention = f" ({params.hours:g} h mentionnées)" if params.hours is not None else ""
        return f"Ajouter au journal de #{params.work_item_id}{mention} : « {_preview(params.text, 120)} »"

    async def run(self, params: AddLogEntryInput, ctx: ToolContext) -> ToolOutput:
        updated = await self.client.add_log_entry(
            params.work_item_id, LogEntryCreate(text=params.text, hours=params.hours)
        )
        return ToolOutput(
            content=f"Journal de #{params.work_item_id} complété.", data=work_item_record(updated)
        )


def projets_read_tools(client: ProjetsClient) -> list[BaseTool[Any]]:
    return [
        ListProjectsTool(client),
        DashboardTool(client),
        StructureTool(client),
        ListWorkItemsTool(client),
        WorkItemTool(client),
        TimesheetTool(client),
        MilestonesTool(client),
    ]


def projets_write_tools(client: ProjetsClient) -> list[BaseTool[Any]]:
    return [
        CreateStoryTool(client),
        CreateWorkItemTool(client),
        UpdateWorkItemTool(client),
        AddTimeEntryTool(client),
        AddLogEntryTool(client),
    ]
