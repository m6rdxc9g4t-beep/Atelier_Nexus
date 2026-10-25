"""Règles pures des déclencheurs : horaires (jours, heure d'été / d'hiver, rattrapage), filtres
d'événements (chaque `op`), gabarits `{{event.…}}`, catalogue des champs d'un manifeste."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, get_args
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.schemas.triggers import DailySchedule, EventFilter, IntervalSchedule, TriggerApp
from app.suite.apps import NODE_APPS
from app.suite.manifest import parse_manifest
from app.triggers.matching import (
    MISSING,
    event_value,
    matches,
    mentions_event,
    render,
    render_params,
    template_problems,
)
from app.triggers.schedule import catch_up, next_occurrence
from tests.fake_suite import PROJETS_MANIFEST

PARIS = ZoneInfo("Europe/Paris")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


# ─── Horaires ─────────────────────────────────────────────────────


def test_interval_next_and_catch_up() -> None:
    every = IntervalSchedule(kind="interval", every_minutes=30)
    start = utc(2026, 10, 22, 8, 0)
    assert next_occurrence(every, start, PARIS) == utc(2026, 10, 22, 8, 30)
    # Nexus fermé 2 h : 4 occurrences échues, la prochaine reste sur la cadence
    count, upcoming = catch_up(every, utc(2026, 10, 22, 8, 30), utc(2026, 10, 22, 10, 40), PARIS)
    assert count == 5  # 8:30, 9:00, 9:30, 10:00, 10:30
    assert upcoming == utc(2026, 10, 22, 11, 0)
    assert catch_up(every, utc(2026, 10, 22, 11, 0), utc(2026, 10, 22, 10, 40), PARIS) == (
        0,
        utc(2026, 10, 22, 11, 0),
    )


def test_daily_respects_the_days_and_the_timezone() -> None:
    weekdays = DailySchedule(kind="daily", at="08:30", days=["mon", "fri"])
    # Jeudi 22 octobre 2026, 12:00 UTC → vendredi 23 à 08:30 Paris (heure d'été : UTC+2)
    assert next_occurrence(weekdays, utc(2026, 10, 22, 12, 0), PARIS) == utc(2026, 10, 23, 6, 30)
    # Vendredi 06:30 UTC pile : strictement après → lundi 26, déjà à l'heure d'hiver (UTC+1)
    assert next_occurrence(weekdays, utc(2026, 10, 23, 6, 30), PARIS) == utc(2026, 10, 26, 7, 30)
    assert DailySchedule(kind="daily", at="07:00", days=["sun", "mon", "sun"]).days == [
        "mon",
        "sun",
    ]


def test_daylight_saving_changes() -> None:
    every_day = DailySchedule(kind="daily", at="08:00", days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])  # fmt: skip
    # Passage à l'heure d'été (29 mars 2026) : 08:00 Paris = 07:00 UTC la veille, 06:00 le jour même
    assert next_occurrence(every_day, utc(2026, 3, 28, 6, 0), PARIS) == utc(2026, 3, 28, 7, 0)
    assert next_occurrence(every_day, utc(2026, 3, 28, 7, 0), PARIS) == utc(2026, 3, 29, 6, 0)
    # Passage à l'heure d'hiver (25 octobre 2026) : 06:00 UTC la veille, 07:00 le jour même
    assert next_occurrence(every_day, utc(2026, 10, 24, 5, 0), PARIS) == utc(2026, 10, 24, 6, 0)
    assert next_occurrence(every_day, utc(2026, 10, 24, 6, 0), PARIS) == utc(2026, 10, 25, 7, 0)
    # 02:30 n'existe pas le 29 mars : lu avec le décalage d'avant (03:30 heure d'été = 01:30 UTC)
    night = DailySchedule(kind="daily", at="02:30", days=["sun"])
    assert next_occurrence(night, utc(2026, 3, 28, 12, 0), PARIS) == utc(2026, 3, 29, 1, 30)
    # 02:30 existe deux fois le 25 octobre : une seule occurrence (la première, 00:30 UTC)
    first = next_occurrence(night, utc(2026, 10, 24, 12, 0), PARIS)
    assert first == utc(2026, 10, 25, 0, 30)
    assert next_occurrence(night, first, PARIS) == utc(2026, 11, 1, 1, 30)


def test_daily_catch_up_counts_the_missed_days() -> None:
    daily = DailySchedule(kind="daily", at="09:00", days=["mon", "tue", "wed", "thu", "fri"])
    # Dû le lundi 19 octobre 09:00 ; Nexus rouvert le jeudi 22 à 12:00 : lun, mar, mer, jeu
    count, upcoming = catch_up(daily, utc(2026, 10, 19, 7, 0), utc(2026, 10, 22, 10, 0), PARIS)
    assert count == 4 and upcoming == utc(2026, 10, 23, 7, 0)


@pytest.mark.parametrize(
    "schedule",
    [
        {"kind": "interval", "every_minutes": 4},
        {"kind": "interval", "every_minutes": 1441},
        {"kind": "daily", "at": "24:00", "days": ["mon"]},
        {"kind": "daily", "at": "8:30", "days": ["mon"]},
        {"kind": "daily", "at": "08:30", "days": []},
        {"kind": "daily", "at": "08:30", "days": ["lundi"]},
    ],
)
def test_invalid_schedules(schedule: dict[str, Any]) -> None:
    model = IntervalSchedule if schedule["kind"] == "interval" else DailySchedule
    with pytest.raises(ValidationError):
        model.model_validate(schedule)


# ─── Filtres ──────────────────────────────────────────────────────

EVENT: dict[str, Any] = {
    "seq": 42,
    "type": "projets.work_item.status_changed",
    "at": "2026-10-21T21:30:00+02:00",
    "subject": {"kind": "work_item", "id": "123", "label": "Écrire la doc"},
    "data": {"from": "OPEN", "to": "IN_PROGRESS", "project_id": "1", "hours": 2.5,
             "tags": ["a", "b"], "rows": [{"n": 7}], "none": None},
}  # fmt: skip


def f(path: str, op: str, value: Any = None) -> EventFilter:
    return EventFilter.model_validate({"path": path, "op": op, "value": value})


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        (f("data.to", "eq", "IN_PROGRESS"), True),
        (f("data.to", "eq", "CLOSED"), False),
        (f("data.project_id", "eq", 1), True),  # « 1 » et 1 : comparaison numérique
        (f("data.to", "ne", "CLOSED"), True),
        (f("data.absent", "ne", "x"), True),  # chemin absent : seul « ne » est vrai
        (f("data.absent", "eq", "x"), False),
        (f("data.to", "in", ["IN_PROGRESS", "IN_REVIEW"]), True),
        (f("data.to", "in", ["CLOSED"]), False),
        (f("subject.id", "in", [123, 456]), True),
        (f("subject.label", "contains", "doc"), True),
        (f("data.tags", "contains", "b"), True),
        (f("data.hours", "gt", 2), True),
        (f("data.hours", "gte", 2.5), True),
        (f("data.hours", "lt", "3"), True),
        (f("data.hours", "lte", 2), False),
        (f("seq", "gt", 41), True),
        (f("type", "eq", "projets.work_item.status_changed"), True),
        (f("data.rows[0].n", "eq", 7), True),
        (f("data.to", "exists"), True),
        (f("data.none", "exists"), False),
        (f("data.absent", "exists"), False),
        (f("data.absent", "gt", 1), False),
    ],
)
def test_each_filter_op(flt: EventFilter, expected: bool) -> None:
    assert matches([flt], EVENT) is expected


def test_all_filters_must_match_and_values_are_checked() -> None:
    assert matches([], EVENT)
    assert not matches([f("data.to", "eq", "IN_PROGRESS"), f("data.from", "eq", "CLOSED")], EVENT)
    assert event_value(EVENT, "data.rows[3].n") is MISSING
    for bad in (
        {"path": "data", "op": "eq", "value": 1},
        {"path": "payload.x", "op": "eq", "value": 1},
        {"path": "data.to", "op": "in", "value": "x"},
        {"path": "data.to", "op": "in", "value": []},
        {"path": "data.to", "op": "exists", "value": 1},
        {"path": "data.to", "op": "eq"},
        {"path": "data.to", "op": "eq", "value": {"x": 1}},
        {"path": "data.to", "op": "regex", "value": "x"},
    ):
        with pytest.raises(ValidationError):
            EventFilter.model_validate(bad)


# ─── Gabarits {{event.…}} ─────────────────────────────────────────


def test_event_templates_become_text() -> None:
    assert render("{{event.data.to}}", EVENT) == "IN_PROGRESS"
    assert render("#{{ event.subject.id }} {{event.subject.label}}", EVENT) == "#123 Écrire la doc"
    assert render("{{event.seq}}/{{event.type}}/{{event.subject.kind}}", EVENT) == (
        "42/projets.work_item.status_changed/work_item"
    )
    assert render("{{event.at}}", EVENT) == "2026-10-21T21:30:00+02:00"
    assert render("{{event.data.hours}} h, {{event.data.tags}}", EVENT) == '2.5 h, ["a","b"]'
    assert render("[{{event.data.absent}}]", EVENT) == "[]"
    assert render("{{event.data.rows[0].n}}", EVENT) == "7"
    assert render_params({"x": "{{event.data.to}}", "y": "fixe"}, None) == {"x": "", "y": "fixe"}


def test_template_problems() -> None:
    assert template_problems({"x": "{{event.data.to}} et {{event.subject.id}}"}, allow_event=True) == []  # fmt: skip
    assert "réservés" in template_problems({"x": "{{event.seq}}"}, allow_event=False)[0]
    assert "seuls" in template_problems({"x": "{{params.y}}"}, allow_event=True)[0]
    assert "illisible" in template_problems({"x": "{{event.payload}}"}, allow_event=True)[0]
    assert mentions_event({"a": ["{{ event.x }}"]}) and not mentions_event("{{params.event}}")


def test_manifest_event_fields_from_the_data_schema() -> None:
    manifest, _ = parse_manifest(PROJETS_MANIFEST, "projets")
    by_type = {e.type: e for e in manifest.events}
    assert by_type["projets.work_item.status_changed"].data_fields == ["project_id", "from", "to"]
    assert by_type["projets.work_item.deleted"].data_fields == []  # schéma illisible : ignoré
    assert by_type["projets.time_entry.created"].data_fields[1] == "hours"


def test_trigger_apps_are_the_suite_nodes() -> None:
    """Le Literal figé du contrat (docs/declencheurs-api.md) suit la liste des nœuds : une app
    ajoutée à NODE_APPS doit l'être aussi à TriggerApp (et à TRIGGER_APPS du frontend)."""
    assert set(get_args(TriggerApp)) == set(NODE_APPS)
