"""Déclencheurs de workflows v2 : horaire et événement (contrat figé : docs/declencheurs-api.md).

Un déclencheur lance un workflow v2 tout seul, à heure fixe (`schedule`) ou quand une application
publie un événement `atelier-node/1` (`event`). Une écriture lancée ainsi s'arrête toujours sur
`awaiting_approval`, comme en manuel.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FilterOp = Literal["eq", "ne", "in", "contains", "gt", "gte", "lt", "lte", "exists"]
TriggerApp = Literal["viz", "projets", "tab"]
RunOrigin = Literal["manual", "schedule", "event", "test"]

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
#: Chemins d'un filtre : `type`, `seq`, `at`, `subject.id|label|kind`, `data.x.y`
FILTER_PATH = re.compile(
    r"^(type|seq|at|subject\.(id|label|kind)|data(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+)$"
)

DEFAULT_MAX_RUNS_PER_HOUR = 12


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─── Horaire ──────────────────────────────────────────────────────


class IntervalSchedule(_Strict):
    kind: Literal["interval"]
    every_minutes: int = Field(ge=5, le=1440)


class DailySchedule(_Strict):
    kind: Literal["daily"]
    at: str
    days: list[Weekday] = Field(min_length=1, max_length=7)

    @field_validator("at")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not HHMM.match(value):
            raise ValueError("heure attendue au format HH:MM (24 h), ex. 08:30")
        return value

    @field_validator("days")
    @classmethod
    def _week_order(cls, value: list[Weekday]) -> list[Weekday]:
        return [d for d in WEEKDAYS if d in value]  # sans doublon, dans l'ordre de la semaine


Schedule = Annotated[IntervalSchedule | DailySchedule, Field(discriminator="kind")]


# ─── Événement ────────────────────────────────────────────────────


class EventFilter(_Strict):
    path: str = Field(max_length=200)
    op: FilterOp
    value: Any = None

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not FILTER_PATH.match(value):
            raise ValueError(
                "chemin attendu : type, seq, at, subject.id, subject.label, subject.kind "
                "ou data.<champ>"
            )
        return value

    @model_validator(mode="after")
    def _value(self) -> Self:
        if self.op == "exists":
            if self.value is not None:
                raise ValueError("« exists » ne prend pas de valeur")
        elif self.op == "in":
            if not isinstance(self.value, list) or not self.value or len(self.value) > 50:
                raise ValueError("« in » attend une liste de 1 à 50 valeurs")
        elif self.value is None:
            raise ValueError(f"« {self.op} » attend une valeur")
        elif isinstance(self.value, dict | list):
            raise ValueError(f"« {self.op} » attend une valeur simple (texte, nombre, booléen)")
        return self


# ─── Corps (création, modification) ───────────────────────────────


class _TriggerFieldsBase(_Strict):
    label: str = Field(default="", max_length=120)
    enabled: bool = True
    #: Valeurs des paramètres du workflow ; gabarits {{event.…}} permis (déclencheur événement)
    params: dict[str, Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=dict, max_length=10
    )
    max_runs_per_hour: int = Field(default=DEFAULT_MAX_RUNS_PER_HOUR, ge=1, le=120)


class ScheduleTriggerFields(_TriggerFieldsBase):
    kind: Literal["schedule"]
    schedule: Schedule


class EventTriggerFields(_TriggerFieldsBase):
    kind: Literal["event"]
    app: TriggerApp
    types: list[Annotated[str, Field(max_length=120)]] = Field(min_length=1, max_length=10)
    filters: list[EventFilter] = Field(default_factory=list, max_length=10)
    debounce_seconds: int = Field(default=0, ge=0, le=3600)

    @field_validator("types")
    @classmethod
    def _types(cls, value: list[str]) -> list[str]:
        for item in value:
            if not EVENT_TYPE.match(item):
                raise ValueError(f"type d'événement invalide : {item!r}")
        if len(set(value)) != len(value):
            raise ValueError("type d'événement en double")
        return value


TriggerFields = Annotated[ScheduleTriggerFields | EventTriggerFields, Field(discriminator="kind")]


# ─── État (lecture seule) ─────────────────────────────────────────


class TriggerCounters(BaseModel):
    fired: int = 0
    throttled: int = 0
    waiting: int = 0
    filtered: int = 0
    missed: int = 0
    errors: int = 0


class TriggerState(BaseModel):
    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_run_id: str | None = None
    last_run_status: str | None = None
    #: Déclencheur événement : dernier seq traité (au départ, celui de la création)
    cursor: int | None = None
    counters: TriggerCounters = Field(default_factory=TriggerCounters)
    last_error: str | None = None
    warning: str | None = None


class _TriggerOut(BaseModel):
    id: str
    workflow_id: str
    created_at: datetime
    updated_at: datetime
    state: TriggerState


class ScheduleTrigger(ScheduleTriggerFields, _TriggerOut):
    pass


class EventTrigger(EventTriggerFields, _TriggerOut):
    pass


Trigger = Annotated[ScheduleTrigger | EventTrigger, Field(discriminator="kind")]


# ─── Exécutions et test ───────────────────────────────────────────


class TriggerEventSubject(BaseModel):
    kind: str
    id: str
    label: str = ""


class TriggerEventRef(BaseModel):
    """Événement à l'origine d'une exécution — jamais ses `data`."""

    app: str
    seq: int
    type: str
    at: str
    subject: TriggerEventSubject


class SampleEvent(BaseModel):
    """Événement d'exemple (`POST /api/triggers/{id}/test`), format §7.3 du contrat."""

    model_config = ConfigDict(extra="ignore")

    seq: int = 0
    type: str = Field(default="", max_length=120)
    at: str = Field(default="", max_length=64)
    subject: TriggerEventSubject = Field(
        default_factory=lambda: TriggerEventSubject(kind="", id="", label="")
    )
    data: dict[str, Any] = Field(default_factory=dict)


class TriggerTestRequest(_Strict):
    event: SampleEvent | None = None


# ─── Catalogue des événements, boîte « À valider » ────────────────


class CatalogEvent(BaseModel):
    type: str
    label: str
    fields: list[str]


class CatalogEventApp(BaseModel):
    app: str
    name: str
    color: str
    status: Literal["ok", "unreachable", "no_contract", "not_configured"]
    events: list[CatalogEvent]


class EventsCatalog(BaseModel):
    apps: list[CatalogEventApp]


class InboxCount(BaseModel):
    awaiting_approval: int
