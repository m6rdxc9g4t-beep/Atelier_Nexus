"""Workflows v2 : graphe d'étapes inter-applications (contrat figé : docs/workflows-v2-api.md).

Une étape utilise un outil Nexus (`tool:<nom>`) ou une action d'application déclarée dans un
manifeste `atelier-node/1` (`node:<app>/<action_id>`). Les étapes forment un graphe sans cycle
(`needs`) ; leurs entrées citent les paramètres et les sorties des étapes amont par gabarits
(`{{params.x}}`, `{{steps.id.data.rows[0].titre}}`…).

La saisie est volontairement peu contrainte (identifiants, nombre d'étapes, gabarits) : ces
règles sont vérifiées par `app/workflows_v2/validation.py`, qui rend des erreurs par étape et
par champ (codes stables) au lieu d'un 422 global.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.triggers import TriggerEventRef
from app.schemas.workflows import RunStatus as LastRunStatus
from app.schemas.workflows import WorkflowParam
from app.tools.base import Artifact

#: Bornes de saisie (les limites métier — 30 étapes — sont signalées par la validation)
HARD_MAX_STEPS = 200

ConditionOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "empty", "not_empty"]
OnError = Literal["stop", "continue"]
ActionKind = Literal["read", "write", "destructive"]
OutputFormat = Literal["atelier-table/1", "json", "text"]
AppStatus = Literal["ok", "unreachable", "no_contract", "not_configured"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Strict):
    left: str = Field(max_length=500)
    op: ConditionOp
    right: Any = None


class StepPosition(_Strict):
    x: float
    y: float


class WorkflowStepV2(_Strict):
    id: str = Field(max_length=100)
    label: str = Field(default="", max_length=200)
    uses: str = Field(max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    needs: list[str] = Field(default_factory=list, max_length=HARD_MAX_STEPS)
    when: Condition | None = None
    on_error: OnError = "stop"
    position: StepPosition | None = None


class WorkflowV2Fields(_Strict):
    """Corps de validation, de création et de modification (`version: 2`)."""

    version: Literal[2]
    agent: str | None = Field(default=None, min_length=1, max_length=41)
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    steps: list[WorkflowStepV2] = Field(default_factory=list, max_length=HARD_MAX_STEPS)
    params: list[WorkflowParam] = Field(default_factory=list, max_length=10)
    #: Conversation d'origine (création) ; accepté et ignoré en validation et en modification
    source_conversation_id: str | None = Field(default=None, max_length=36)


class WorkflowV2Create(WorkflowV2Fields):
    title: str = Field(min_length=1, max_length=120)


class WorkflowV2Update(WorkflowV2Fields):
    title: str = Field(min_length=1, max_length=120)


class WorkflowV2(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    version: Literal[2] = 2
    agent: str | None
    title: str
    description: str
    steps: list[WorkflowStepV2]
    params: list[WorkflowParam]
    source_conversation_id: str | None = None
    run_count: int = 0
    last_run_at: datetime | None = None
    last_status: LastRunStatus | None = None
    created_at: datetime
    updated_at: datetime


# ─── Bibliothèque de modèles (GET /api/workflows/library) ────────


class WorkflowTemplate(BaseModel):
    """Modèle de workflow de suite fourni par Nexus : un enchaînement prêt à copier dans un
    brouillon (jamais exécuté tel quel). `available` / `missing` sont calculés à chaque lecture
    avec le catalogue réel (applications joignables, boîtes configurées)."""

    slug: str
    title: str
    description: str
    #: Bénéfice pour l'utilisateur, une phrase
    value: str
    #: Applications enchaînées, dans l'ordre (puces colorées)
    apps: list[str]
    params: list[WorkflowParam]
    steps: list[WorkflowStepV2]
    #: Prérequis en clair (« Atelier Convert lancé », « TAB_MCP_COMMAND (serveur MCP de Tab) »…)
    requirements: list[str]
    #: Déclencheur conseillé, en clair ; None si manuel uniquement
    trigger_hint: str | None = None
    #: Toutes les étapes sont connues et leurs applications joignables
    available: bool = False
    #: Étapes ou applications manquantes (« node:convert/conversions.list : Atelier Convert
    #: injoignable »)
    missing: list[str] = Field(default_factory=list)


# ─── Catalogue ────────────────────────────────────────────────────


class OutputColumnHint(BaseModel):
    key: str
    label: str
    type: str


class OutputHint(BaseModel):
    columns: list[OutputColumnHint] | None = None
    fields: list[str] | None = None


class CatalogEntry(BaseModel):
    uses: str
    source: Literal["tool", "node"]
    app: str | None
    label: str
    description: str
    kind: ActionKind
    input_schema: dict[str, Any]
    output_format: OutputFormat
    output_hint: OutputHint | None = None
    available: bool
    unavailable_reason: str | None = None


class CatalogApp(BaseModel):
    app: str
    name: str
    status: AppStatus
    color: str


class Catalog(BaseModel):
    apps: list[CatalogApp]
    entries: list[CatalogEntry]


# ─── Validation ───────────────────────────────────────────────────


class ValidationIssue(BaseModel):
    step_id: str | None = None
    field: str | None = None
    code: str
    message: str


class ValidationResult(BaseModel):
    ok: bool
    errors: list[ValidationIssue]
    order: list[str]


# ─── Exécutions ───────────────────────────────────────────────────

RunStatus = Literal["running", "awaiting_approval", "completed", "failed", "stopped"]
StepRunStatus = Literal["pending", "ok", "error", "refused", "skipped", "awaiting_approval"]


class StepRun(BaseModel):
    id: str
    uses: str
    label: str
    status: StepRunStatus = "pending"
    input: dict[str, Any] | None = None
    content: str = ""
    data: Any = None
    error_code: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class PendingApproval(BaseModel):
    step_id: str
    uses: str
    #: `read` : seulement en `APPROVAL_MODE=every_step` (toute étape attend une validation)
    kind: Literal["read", "write", "destructive"]
    summary: str
    token: str
    input: dict[str, Any]


class WorkflowRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    status: RunStatus
    message: str
    params: dict[str, str]
    #: Origine (docs/declencheurs-api.md §2) ; `trigger_event` ne porte jamais les `data`
    trigger: Literal["manual", "schedule", "event", "test"] = "manual"
    trigger_id: str | None = None
    trigger_event: TriggerEventRef | None = None
    steps: list[StepRun]
    artifacts: list[Artifact]
    pending: list[PendingApproval]
    created_at: datetime
    updated_at: datetime


class ResumeRequest(_Strict):
    approvals: dict[str, bool] = Field(default_factory=dict)
