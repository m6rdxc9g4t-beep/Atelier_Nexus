"""Chaînes d'agents : une demande traverse plusieurs agents spécialisés, dans l'ordre.

Chaque étape est une conversation ordinaire avec son agent (validations d'actions, pas à pas,
historique). L'utilisateur valide le livrable de l'étape ; il est alors figé et transmis à
l'agent suivant avec la demande d'origine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Artifact


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChainStage(_Strict):
    agent: str
    #: Rôle de l'étape dans la chaîne (« Préparation des données »)
    role: str
    #: Mission transmise à l'agent pour cette étape
    instructions: str


class ChainDefinition(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    title: str
    description: str
    icon: str
    stages: list[ChainStage] = Field(min_length=2)


class ChainStageInfo(ChainStage):
    display_name: str
    local_only: bool


class ChainInfo(_Strict):
    id: str
    title: str
    description: str
    icon: str
    stages: list[ChainStageInfo]


StageStatus = Literal["pending", "active", "validated", "skipped"]
RunStatus = Literal["running", "completed", "stopped"]


class StageDeliverable(BaseModel):
    """Livrable figé au moment de la validation."""

    text: str
    artifacts: list[Artifact] = Field(default_factory=list)


class StageState(BaseModel):
    agent: str
    role: str
    status: StageStatus = "pending"
    conversation_id: str | None = None
    deliverable: StageDeliverable | None = None
    validated_at: datetime | None = None


class ChainRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chain: str
    request: str
    status: RunStatus
    stage_index: int
    stages: list[StageState]
    created_at: datetime
    updated_at: datetime


class ChainStart(_Strict):
    request: str = Field(min_length=3, max_length=8000)


class ChainStep(BaseModel):
    """Ce que l'interface doit faire ensuite : ouvrir la conversation de l'étape et y envoyer
    le message de passage de relais (ou montrer le récapitulatif si la chaîne est finie)."""

    run: ChainRun
    agent: str | None = None
    conversation_id: str | None = None
    handoff: str | None = None
    recap: Artifact | None = None
