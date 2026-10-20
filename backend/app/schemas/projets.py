"""Schémas de l'API d'Atelier Projets (`http://127.0.0.1:3000/api`, Fastify + Prisma).

Contrat de référence : `Atelier_Projets/backend/openapi.json` (généré depuis le code).
Champs en camelCase, exactement comme sur le fil. Réponses : champs inconnus ignorés.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkItemType = Literal["FEATURE", "TASK", "BUG"]
Status = Literal[
    "OPEN", "IN_PROGRESS", "IN_REVIEW", "ON_HOLD", "BLOCKED", "RESOLVED", "CLOSED", "REJECTED"
]
Priority = Literal["LOW", "NORMAL", "HIGH", "IMMEDIATE"]
BalanceKind = Literal["UNDER", "ON_BUDGET", "OVER", "REMAINING"]

#: Libellés français communs à la suite (SUITE.md §1.4)
STATUS_LABELS: dict[str, str] = {
    "OPEN": "À faire",
    "IN_PROGRESS": "En cours",
    "IN_REVIEW": "En revue",
    "ON_HOLD": "En attente",
    "BLOCKED": "Bloquée",
    "RESOLVED": "Résolue",
    "CLOSED": "Terminée",
    "REJECTED": "Rejetée",
}
PRIORITY_LABELS: dict[str, str] = {
    "LOW": "Basse",
    "NORMAL": "Normale",
    "HIGH": "Haute",
    "IMMEDIATE": "Immédiate",
}


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Duration(_R):
    hours: float
    days: float


class Balance(_R):
    kind: BalanceKind
    delta: Duration


class GitHubRef(_R):
    owner: str
    repo: str
    url: str


class Project(_R):
    id: int
    name: str
    slug: str
    description: str = ""
    github: GitHubRef | None = None
    defaultBranch: str = "main"
    hoursPerDay: float
    budget: Duration | None = None
    startDate: date | None = None
    dueDate: date | None = None


class WorkItem(_R):
    id: int
    projectId: int
    storyId: int
    type: WorkItemType
    status: Status
    priority: Priority
    title: str
    progress: int
    startDate: date | None = None
    dueDate: date | None = None
    estimate: Duration | None = None
    spent: Duration
    balance: Balance | None = None


class PathRef(_R):
    id: int
    code: str
    title: str


class WorkItemPath(_R):
    phase: PathRef
    epic: PathRef
    story: PathRef


class TimeEntry(_R):
    id: int
    workItemId: int
    spentOn: date
    duration: Duration
    comment: str | None = None


class Commit(_R):
    shortHash: str
    message: str
    authorName: str
    committedAt: datetime
    branch: str | None = None


class PullRequest(_R):
    number: int
    title: str
    state: Literal["OPEN", "MERGED", "CLOSED"]
    url: str
    headBranch: str


class Neighbour(_R):
    id: int
    title: str
    status: Status


class WorkItemDetail(WorkItem):
    description: str = ""
    implementationLog: str = ""
    path: WorkItemPath
    timeEntries: list[TimeEntry] = Field(default_factory=list)
    commits: list[Commit] = Field(default_factory=list)
    pullRequests: list[PullRequest] = Field(default_factory=list)
    predecessors: list[Neighbour] = Field(default_factory=list)
    successors: list[Neighbour] = Field(default_factory=list)


class Milestone(_R):
    id: int
    projectId: int
    phaseId: int | None = None
    title: str
    date: date
    reached: bool


class DashboardBudget(_R):
    initial: Duration | None = None
    spent: Duration
    remaining: Duration | None = None
    consumedPercent: float | None = None


class DashboardProgress(_R):
    percent: float
    planned: Duration
    earned: Duration


class DashboardCounts(_R):
    total: int
    done: int
    donePercent: float | None = None


class HistogramBar(_R):
    status: Status
    total: int


class Dashboard(_R):
    project: Project
    budget: DashboardBudget
    progress: DashboardProgress
    trend: Literal["AHEAD", "ON_TRACK", "BEHIND"] | None = None
    workItems: DashboardCounts
    histogram: list[HistogramBar] = Field(default_factory=list)


class Aggregate(_R):
    status: Status
    progress: float
    estimate: Duration
    spent: Duration
    workItems: int


class TreeStory(_R):
    id: int
    code: str
    title: str
    aggregate: Aggregate


class TreeEpic(_R):
    id: int
    code: str
    title: str
    aggregate: Aggregate
    stories: list[TreeStory] = Field(default_factory=list)


class TreePhase(_R):
    id: int
    code: str
    title: str
    aggregate: Aggregate
    epics: list[TreeEpic] = Field(default_factory=list)


class ProjectTree(_R):
    project: Project
    aggregate: Aggregate
    phases: list[TreePhase] = Field(default_factory=list)
    criticalPath: list[int] = Field(default_factory=list)


class TimesheetRow(_R):
    id: int
    type: WorkItemType
    title: str
    status: Status
    estimate: Duration | None = None
    spent: Duration
    balance: Balance | None = None


class TimesheetTotals(_R):
    count: int
    done: int
    donePercent: float | None = None
    estimate: Duration
    spent: Duration
    remaining: Duration


class Timesheet(_R):
    hoursPerDay: float
    rows: list[TimesheetRow]
    totals: TimesheetTotals


class Health(_R):
    status: str
    database: str


# ─── Corps d'écriture (stricts : l'API refuse tout champ inconnu) ──


class _W(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkItemCreate(_W):
    type: WorkItemType
    title: str = Field(min_length=1, max_length=200)
    status: Status | None = None
    priority: Priority | None = None
    description: str | None = None
    estimatedHours: float | None = Field(default=None, gt=0, le=10_000)
    dueDate: date | None = None


class WorkItemUpdate(_W):
    status: Status | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    priority: Priority | None = None
    dueDate: date | None = None


class TimeEntryCreate(_W):
    hours: float = Field(ge=0.01, le=24)
    spentOn: date | None = None
    comment: str | None = Field(default=None, max_length=2000)


class LogEntryCreate(_W):
    text: str = Field(min_length=1, max_length=20_000)
    hours: float | None = Field(default=None, ge=0, le=24)
