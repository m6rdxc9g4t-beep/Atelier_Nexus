"""Workflows rejouables : les appels d'outils d'un tour réussi, figés et relancés sans modèle.

« L'agent explore, le workflow industrialise » : une fois qu'un agent a trouvé le bon chemin
(par exemple schéma Data Via → requête → publication d'une mesure), on enregistre ce chemin.
Le relancer exécute les mêmes outils, dans le même ordre, avec des paramètres `{{nom}}`
éventuels : résultat identique, instantané, sans jeton et sans modèle.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.llm.types import Message
from app.tools.base import Artifact

#: `{{ nom }}` dans une valeur texte d'un paramètre d'outil
PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,39})\s*\}\}")
PARAM_NAME = r"^[a-z][a-z0-9_]{0,39}$"
MAX_STEPS = 30


def placeholders(value: Any) -> Iterator[str]:
    """Noms des paramètres cités dans une entrée d'outil (récursif)."""
    if isinstance(value, str):
        yield from PLACEHOLDER.findall(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from placeholders(item)
    elif isinstance(value, list):
        for item in value:
            yield from placeholders(item)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowStep(_Strict):
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$", description="Nom de l'outil de l'agent.")
    input: dict[str, Any] = Field(default_factory=dict)
    label: str = Field(default="", max_length=200)


class WorkflowParam(_Strict):
    name: str = Field(pattern=PARAM_NAME)
    label: str = Field(default="", max_length=80)
    default: str = Field(default="", max_length=500)


class WorkflowFields(_Strict):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=MAX_STEPS)
    params: list[WorkflowParam] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _params_match_steps(self) -> Self:
        names = [p.name for p in self.params]
        if len(names) != len(set(names)):
            raise ValueError("Deux paramètres portent le même nom.")
        used = {name for step in self.steps for name in placeholders(step.input)}
        missing = sorted(used - set(names))
        if missing:
            raise ValueError(f"Paramètre(s) cité(s) mais non déclaré(s) : {', '.join(missing)}.")
        return self


class WorkflowCreate(WorkflowFields):
    agent: str = Field(min_length=1, max_length=41)
    source_conversation_id: str | None = Field(default=None, max_length=36)


class WorkflowUpdate(WorkflowFields):
    pass


RunStatus = Literal["completed", "failed"]


class Workflow(WorkflowCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    run_count: int = 0
    last_run_at: datetime | None = None
    last_status: RunStatus | None = None
    created_at: datetime
    updated_at: datetime


# ─── Capture depuis une conversation ──────────────────────────────


class CaptureRequest(_Strict):
    agent: str = Field(min_length=1, max_length=41)
    messages: list[Message] = Field(min_length=1)


class SkippedCall(BaseModel):
    tool: str
    reason: str


class WorkflowDraft(BaseModel):
    """Proposition de workflow à relire avant enregistrement (rien n'est stocké)."""

    agent: str
    title: str
    description: str
    steps: list[WorkflowStep]
    skipped: list[SkippedCall]
    #: Étapes qui modifient des données : chaque lancement redemandera la validation
    writes: list[int]


# ─── Exécution ────────────────────────────────────────────────────


class WorkflowRunRequest(_Strict):
    params: dict[str, str] = Field(default_factory=dict)
    #: Validation des étapes d'écriture : numéro d'étape (à partir de 1) → autorisée
    approvals: dict[str, bool] | None = None


StepStatus = Literal["ok", "error", "refused", "skipped"]


class StepResult(BaseModel):
    index: int
    tool: str
    label: str
    input: dict[str, Any]
    status: StepStatus
    content: str = ""


class PendingStep(BaseModel):
    index: int
    tool: str
    summary: str


class WorkflowRunResult(BaseModel):
    status: Literal["completed", "failed", "awaiting_approval"]
    message: str
    steps: list[StepResult] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    pending: list[PendingStep] = Field(default_factory=list)
