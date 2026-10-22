"""Déclencheurs de workflows (docs/declencheurs-api.md) : API, passages (`tick()`), horaires,
événements, débit, validation humaine des écritures, boîte « À valider », boucle de fond.

Applications simulées (httpx.MockTransport, dossier `_atelier/` de Tab), horloge et sommeil
injectés : aucun réseau, aucun modèle, aucune attente réelle.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

import main
from app.agents import AgentCatalog
from app.api.deps import get_trigger_repository
from app.api.triggers import get_trigger_clock
from app.core.config import get_settings
from app.db.triggers import TriggerRepository
from app.db.workflows import WorkflowRepository
from app.suite.nodes import clear_manifest_cache
from app.triggers import service as service_module
from app.triggers.service import GAP_WARNING, TriggerDeps, TriggerService
from main import app
from tests.fake_suite import event
from tests.fakes import make_router
from tests.test_suite_nodes import Suite

BACKEND = Path(__file__).resolve().parents[1]
STATUS = "projets.work_item.status_changed"


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 22, 6, 0, tzinfo=UTC))  # jeudi, 08:00 à Paris


@pytest.fixture
def triggers(repo: WorkflowRepository) -> TriggerRepository:
    return TriggerRepository(repo.sessions)


@pytest.fixture
def api(client: TestClient, triggers: TriggerRepository, clock: FakeClock) -> Iterator[TestClient]:
    app.dependency_overrides[get_trigger_repository] = lambda: triggers
    app.dependency_overrides[get_trigger_clock] = lambda: clock
    yield client


def make_service(
    triggers: TriggerRepository, repo: WorkflowRepository, suite: Suite, clock: FakeClock
) -> TriggerService:
    """Moteur tel que la tâche de fond le construit (un par « processus »)."""
    router = make_router()
    return TriggerService(
        TriggerDeps(
            triggers=triggers,
            workflows=repo,
            make_env=suite.env,
            llm=lambda: router,
            catalog=AgentCatalog,
            settings=get_settings,
        ),
        clock=clock,
    )


@pytest.fixture
def service(
    triggers: TriggerRepository, repo: WorkflowRepository, suite: Suite, clock: FakeClock
) -> TriggerService:
    return make_service(triggers, repo, suite, clock)


# ─── Workflows et déclencheurs d'exemple ──────────────────────────

PARAMS = [
    {"name": "projet", "label": "Projet", "default": "1"},
    {"name": "titre", "label": "Titre", "default": "Suivi"},
]
READ = [
    {"id": "lire", "label": "", "uses": "node:projets/work_items.list",
     "input": {"project_id": "{{params.projet}}"}, "needs": [], "on_error": "stop"},
]  # fmt: skip
WRITE = [
    {"id": "creer", "label": "Écrire la doc", "uses": "node:projets/work_items.create",
     "input": {"story_id": 2, "type": "TASK", "title": "{{params.titre}}"}, "needs": [],
     "on_error": "stop"},
]  # fmt: skip


def workflow(client: TestClient, steps: list[dict[str, Any]], title: str = "Suivi") -> str:
    body = {"version": 2, "agent": None, "title": title, "description": "", "params": PARAMS,
            "steps": steps}  # fmt: skip
    response = client.post("/api/workflows", json=body)
    assert response.status_code == 201, response.text
    workflow_id: str = response.json()["id"]
    return workflow_id


def on_event(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "event",
        "label": "Doc à écrire",
        "app": "projets",
        "types": [STATUS],
        "filters": [{"path": "data.to", "op": "eq", "value": "IN_PROGRESS"}],
        "params": {
            "titre": "Doc #{{event.subject.id}} {{event.subject.label}} ({{event.data.to}})"
        },
        **extra,
    }


def daily(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "schedule",
        "schedule": {"kind": "daily", "at": "08:30", "days": ["mon", "tue", "wed", "thu", "fri"]},
        **extra,
    }


def add(client: TestClient, workflow_id: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/api/workflows/{workflow_id}/triggers", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def get(client: TestClient, trigger: dict[str, Any]) -> dict[str, Any]:
    listed = client.get(f"/api/workflows/{trigger['workflow_id']}/triggers").json()
    return next(t for t in listed if t["id"] == trigger["id"])


def runs(client: TestClient, workflow_id: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = client.get(
        "/api/workflow-runs", params={"workflow_id": workflow_id}
    ).json()
    return data


def approve(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    token = run["pending"][0]["token"]
    data: dict[str, Any] = client.post(
        f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {token: True}}
    ).json()
    return data


# ─── Horaires ─────────────────────────────────────────────────────


async def test_daily_schedule_fires_once_then_catches_up_once_after_a_restart(
    api: TestClient,
    service: TriggerService,
    triggers: TriggerRepository,
    repo: WorkflowRepository,
    suite: Suite,
    clock: FakeClock,
) -> None:
    suite.approval_mode = (
        "writes_only"  # sujet : le moteur des déclencheurs (every_step : plus bas)
    )
    wf = workflow(api, READ)
    trigger = add(api, wf, daily(params={"projet": "7"}))
    state = trigger["state"]
    assert trigger["kind"] == "schedule" and trigger["max_runs_per_hour"] == 12
    assert state["next_fire_at"].startswith("2026-10-22T06:30:00")  # 08:30 heure d'été
    assert state["counters"] == {"fired": 0, "throttled": 0, "waiting": 0, "filtered": 0,
                                 "missed": 0, "errors": 0}  # fmt: skip
    await service.tick()
    assert runs(api, wf) == []  # pas encore l'heure

    clock.advance(minutes=31)
    await service.tick()
    await service.tick()  # deuxième passage : rien de plus
    [run] = runs(api, wf)
    assert run["trigger"] == "schedule" and run["trigger_id"] == trigger["id"]
    assert run["trigger_event"] is None and run["status"] == "completed"  # lecture seule : au bout
    assert run["params"] == {"projet": "7", "titre": "Suivi"}
    state = get(api, trigger)["state"]
    assert state["counters"]["fired"] == 1 and state["last_run_id"] == run["id"]
    assert state["last_run_status"] == "completed" and state["last_fired_at"]
    assert state["next_fire_at"].startswith("2026-10-23T06:30:00")

    # Nexus fermé du vendredi au mardi (passage à l'heure d'hiver le dimanche 25) : au
    # redémarrage, une seule exécution ; vendredi et lundi comptés `missed`
    clock.now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    restarted = make_service(triggers, repo, suite, clock)
    await restarted.tick()
    await restarted.tick()
    assert len(runs(api, wf)) == 2
    state = get(api, trigger)["state"]
    assert state["counters"]["fired"] == 2 and state["counters"]["missed"] == 2
    assert state["next_fire_at"].startswith("2026-10-28T07:30:00")  # 08:30 heure d'hiver


async def test_interval_schedule_waits_while_a_write_awaits_approval(
    api: TestClient, service: TriggerService, suite: Suite, clock: FakeClock
) -> None:
    wf = workflow(api, WRITE)
    trigger = add(api, wf, {"kind": "schedule", "schedule": {"kind": "interval", "every_minutes": 5}})  # fmt: skip
    assert trigger["state"]["next_fire_at"].startswith("2026-10-22T06:05:00")
    clock.advance(minutes=5)
    await service.tick()
    [run] = runs(api, wf)
    # Règle absolue : une écriture lancée par un déclencheur attend une validation humaine
    assert run["status"] == "awaiting_approval" and not suite.projets.created
    assert run["pending"][0]["input"]["title"] == "Suivi"

    clock.advance(minutes=5)
    await service.tick()
    assert len(runs(api, wf)) == 1  # au plus une exécution en attente par déclencheur
    assert get(api, trigger)["state"]["counters"]["waiting"] == 1

    run = approve(api, run)
    assert run["status"] == "completed" and suite.projets.created[0]["title"] == "Suivi"
    assert get(api, trigger)["state"]["last_run_status"] == "completed"
    clock.advance(minutes=5)
    await service.tick()
    assert len(runs(api, wf)) == 2


async def test_every_step_stops_a_read_at_step_one_and_fills_the_inbox(
    api: TestClient, service: TriggerService, suite: Suite, clock: FakeClock
) -> None:
    """APPROVAL_MODE=every_step (défaut) : même un workflow de lecture lancé par un horaire
    s'arrête sur sa première étape, compte dans « À valider », et n'est pas relancé tant qu'il
    attend (au plus une exécution en attente par déclencheur)."""
    wf = workflow(api, READ)
    trigger = add(api, wf, {"kind": "schedule", "schedule": {"kind": "interval", "every_minutes": 5}})  # fmt: skip
    clock.advance(minutes=5)
    await service.tick()
    [run] = runs(api, wf)
    assert run["status"] == "awaiting_approval" and run["trigger"] == "schedule"
    assert [(x["id"], x["status"]) for x in run["steps"]] == [("lire", "awaiting_approval")]
    assert run["pending"][0]["kind"] == "read" and run["pending"][0]["input"] == {"project_id": 1}
    assert not [r for r in suite.projets.requests if r.url.path.endswith("/work-items")]
    assert api.get("/api/workflow-runs/inbox-count").json() == {"awaiting_approval": 1}

    clock.advance(minutes=5)
    await service.tick()
    assert len(runs(api, wf)) == 1 and get(api, trigger)["state"]["counters"]["waiting"] == 1

    run = approve(api, run)
    assert run["status"] == "completed" and run["steps"][0]["status"] == "ok"
    assert api.get("/api/workflow-runs/inbox-count").json() == {"awaiting_approval": 0}


async def test_disabled_and_updated_schedules(
    api: TestClient, service: TriggerService, clock: FakeClock
) -> None:
    wf = workflow(api, READ)
    trigger = add(api, wf, daily(enabled=False, label="Matin"))
    assert trigger["state"]["next_fire_at"] is None and trigger["label"] == "Matin"
    clock.advance(hours=3)
    await service.tick()
    assert runs(api, wf) == []
    # Modification : réactivé, autre heure ; compteurs conservés, next_fire_at recalculé
    updated = api.put(f"/api/triggers/{trigger['id']}", json=trigger | daily(enabled=True, schedule={"kind": "daily", "at": "18:00", "days": ["thu"]})).json()  # fmt: skip
    assert updated["enabled"] is True and updated["state"]["next_fire_at"].startswith("2026-10-22T16:00:00")  # fmt: skip
    assert updated["created_at"] == trigger["created_at"] and updated["id"] == trigger["id"]
    assert api.put("/api/triggers/inconnu", json=daily()).status_code == 404


# ─── Événements ───────────────────────────────────────────────────


async def test_event_trigger_runs_a_write_that_waits_then_resumes(
    api: TestClient, service: TriggerService, suite: Suite
) -> None:
    wf = workflow(api, WRITE, title="Écrire la doc")
    trigger = add(api, wf, on_event())
    assert trigger["state"]["cursor"] == 5  # dernier seq connu à la création
    assert trigger["state"]["next_fire_at"] is None and trigger["debounce_seconds"] == 0
    suite.projets.events += [
        event(6, to="IN_PROGRESS", **{"from": "OPEN"}, project_id="1"),
        event(7, to="CLOSED", subject_id="124"),  # filtré
        event(8, "projets.work_item.created", subject_id="125"),  # autre type : ignoré
    ]
    await service.tick()
    [run] = runs(api, wf)
    assert run["trigger"] == "event" and run["status"] == "awaiting_approval"
    assert run["params"]["titre"] == "Doc #123 Écrire la doc (IN_PROGRESS)"
    assert run["trigger_event"] == {
        "app": "projets", "seq": 6, "type": STATUS, "at": "2026-10-22T09:06:00+02:00",
        "subject": {"kind": "work_item", "id": "123", "label": "Écrire la doc"},
    }  # fmt: skip
    assert "data" not in run["trigger_event"]  # jamais les données de l'événement
    assert run["pending"][0]["input"]["title"] == "Doc #123 Écrire la doc (IN_PROGRESS)"
    assert not suite.projets.created
    state = get(api, trigger)["state"]
    assert state["cursor"] == 8 and state["counters"]["fired"] == 1
    assert state["counters"]["filtered"] == 1

    # Boîte « À valider » (tous workflows) et badge
    # (APPROVAL_MODE=every_step, défaut : une lecture lancée à la main attend aussi)
    other = workflow(api, READ, title="Autre")
    manual = api.post(f"/api/workflows/{other}/run", json={"params": {}}).json()
    assert manual["status"] == "awaiting_approval" and manual["pending"][0]["kind"] == "read"
    inbox = api.get("/api/workflow-runs", params={"status": "awaiting_approval"}).json()
    assert {r["id"] for r in inbox} == {run["id"], manual["id"]}
    assert api.get("/api/workflow-runs/inbox-count").json() == {"awaiting_approval": 2}
    assert api.get("/api/workflow-runs", params={"status": "nope"}).status_code == 422

    # Tant qu'elle attend : les nouveaux événements sont comptés `waiting`
    suite.projets.events.append(event(9, to="IN_PROGRESS", subject_id="126"))
    await service.tick()
    assert len(runs(api, wf)) == 1
    assert get(api, trigger)["state"]["counters"]["waiting"] == 1

    run = approve(api, run)
    assert run["status"] == "completed" and run["trigger"] == "event"
    assert suite.projets.created[0]["title"] == "Doc #123 Écrire la doc (IN_PROGRESS)"
    assert api.get("/api/workflow-runs/inbox-count").json() == {"awaiting_approval": 1}
    suite.projets.events.append(event(10, to="IN_PROGRESS", subject_id="127", label="Tests"))
    await service.tick()
    latest = runs(api, wf)[0]
    assert latest["params"]["titre"] == "Doc #127 Tests (IN_PROGRESS)"
    assert get(api, trigger)["state"]["counters"]["fired"] == 2


async def test_first_start_replays_nothing_and_new_triggers_see_only_new_events(
    api: TestClient, service: TriggerService, triggers: TriggerRepository, suite: Suite
) -> None:
    suite.approval_mode = (
        "writes_only"  # sujet : le moteur des déclencheurs (every_step : plus bas)
    )
    wf = workflow(api, READ)
    suite.projets.mode = "down"  # créé alors que Projets ne répond pas : accepté, signalé
    clear_manifest_cache()
    trigger = add(api, wf, on_event(filters=[]))
    assert trigger["state"]["cursor"] is None and "injoignable" in trigger["state"]["last_error"]
    suite.projets.mode = "ok"
    clear_manifest_cache()
    suite.projets.events += [event(6, to="IN_PROGRESS"), event(7, to="IN_PROGRESS")]
    await service.tick()  # premier démarrage : curseur = dernier seq, rien n'est rejoué
    assert runs(api, wf) == [] and await triggers.get_cursor("projets") == 7
    state = get(api, trigger)["state"]
    assert state["cursor"] == 7 and state["last_error"] is None  # l'application répond

    suite.projets.events.append(event(8, to="IN_PROGRESS"))
    late = add(api, workflow(api, READ, title="Tardif"), on_event(filters=[]))
    assert late["state"]["cursor"] == 8  # créé après le seq 8 : ne le verra pas
    await service.tick()
    assert len(runs(api, wf)) == 1 and runs(api, late["workflow_id"]) == []
    suite.projets.events.append(event(9, to="IN_PROGRESS"))
    await service.tick()
    assert len(runs(api, wf)) == 2 and len(runs(api, late["workflow_id"])) == 1
    assert await triggers.get_cursor("projets") == 9


async def test_unreachable_app_sets_last_error_then_recovers(
    api: TestClient, service: TriggerService, suite: Suite, caplog: pytest.LogCaptureFixture
) -> None:
    wf = workflow(api, READ)
    trigger = add(api, wf, on_event())
    suite.projets.mode = "down"
    await service.tick()
    await service.tick()
    state = get(api, trigger)["state"]
    assert state["last_error"] == "Atelier Projets injoignable."
    assert state["counters"]["errors"] == 1  # une panne = une erreur, pas une par passage
    suite.projets.mode = "ok"
    secret = "donnée-confidentielle-42"
    suite.projets.events.append(event(6, to="IN_PROGRESS", note=secret))
    with caplog.at_level(logging.DEBUG):
        await service.tick()
    state = get(api, trigger)["state"]
    assert state["last_error"] is None and state["counters"]["fired"] == 1
    assert secret not in caplog.text  # jamais de données d'événement dans les journaux


async def test_gap_warns_and_relaunches_nothing(
    api: TestClient, service: TriggerService, triggers: TriggerRepository, suite: Suite
) -> None:
    suite.approval_mode = (
        "writes_only"  # sujet : le moteur des déclencheurs (every_step : plus bas)
    )
    wf = workflow(api, READ)
    trigger = add(api, wf, on_event(filters=[]))
    suite.projets.events.append(event(6, to="IN_PROGRESS"))
    await service.tick()
    assert len(runs(api, wf)) == 1
    # Journal de Projets remis à zéro : since (6) au-delà du dernier seq connu (3) → gap
    suite.projets.events[:] = [event(s, to="IN_PROGRESS") for s in (1, 2, 3)]
    await service.tick()
    assert len(runs(api, wf)) == 1  # rien relancé en masse
    state = get(api, trigger)["state"]
    assert state["warning"] == GAP_WARNING and state["cursor"] == 3
    assert await triggers.get_cursor("projets") == 3
    suite.projets.events.append(event(4, to="IN_PROGRESS"))
    await service.tick()
    assert len(runs(api, wf)) == 2 and get(api, trigger)["state"]["warning"] is None
    # Événements purgés (since < oldest - 1) : même traitement
    suite.projets.events[:] = [event(s, to="IN_PROGRESS") for s in (40, 41)]
    await service.tick()
    assert len(runs(api, wf)) == 2 and get(api, trigger)["state"]["warning"] == GAP_WARNING


async def test_debounce_keeps_the_last_event_of_the_burst(
    api: TestClient, service: TriggerService, suite: Suite, clock: FakeClock
) -> None:
    wf = workflow(api, READ)
    trigger = add(api, wf, on_event(debounce_seconds=60))
    suite.projets.events += [event(6, to="IN_PROGRESS", subject_id="1"),
                             event(7, to="IN_PROGRESS", subject_id="2")]  # fmt: skip
    await service.tick()
    clock.advance(seconds=30)
    suite.projets.events.append(event(8, to="IN_PROGRESS", subject_id="3"))
    await service.tick()
    assert runs(api, wf) == []  # la rafale continue
    clock.advance(seconds=59)
    await service.tick()
    assert runs(api, wf) == []
    clock.advance(seconds=2)
    await service.tick()
    [run] = runs(api, wf)
    assert run["params"]["titre"].startswith("Doc #3 ") and run["trigger_event"]["seq"] == 8
    await service.tick()
    assert len(runs(api, wf)) == 1
    assert get(api, trigger)["state"]["counters"]["fired"] == 1


async def test_throttling_by_max_runs_per_hour(
    api: TestClient, service: TriggerService, suite: Suite, clock: FakeClock
) -> None:
    suite.approval_mode = (
        "writes_only"  # sujet : le moteur des déclencheurs (every_step : plus bas)
    )
    wf = workflow(api, READ)
    trigger = add(api, wf, on_event(max_runs_per_hour=2))
    suite.projets.events += [event(s, to="IN_PROGRESS") for s in (6, 7, 8)]
    await service.tick()
    assert len(runs(api, wf)) == 2
    counters = get(api, trigger)["state"]["counters"]
    assert counters["fired"] == 2 and counters["throttled"] == 1
    clock.advance(minutes=61)
    suite.projets.events.append(event(9, to="IN_PROGRESS"))
    await service.tick()
    assert len(runs(api, wf)) == 3


async def test_tab_events_from_the_atelier_folder(
    api: TestClient, service: TriggerService, suite: Suite
) -> None:
    import json

    log = suite.exports / "_atelier" / "events.jsonl"

    def write(*seqs: int) -> None:
        lines = [{"seq": s, "type": "tab.table.changed", "at": "2026-10-22T10:00:00+02:00",
                  "subject": {"kind": "table", "id": "tbl_planning_lots", "label": "Planning"},
                  "data": {"revision": s, "rows": 2, "project": "Chantier"}} for s in seqs]  # fmt: skip
        log.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    write(1, 2)
    wf = workflow(api, READ)
    body = {"kind": "event", "app": "tab", "types": ["tab.table.changed"],
            "filters": [{"path": "data.project", "op": "in", "value": ["Chantier"]}],
            "params": {"titre": "{{event.subject.label}} r{{event.data.revision}}"}}  # fmt: skip
    trigger = add(api, wf, body)
    assert trigger["state"]["cursor"] == 2
    write(1, 2, 3)
    await service.tick()
    [run] = runs(api, wf)
    assert run["params"]["titre"] == "Planning r3" and run["trigger_event"]["app"] == "tab"


# ─── Test, suppression, catalogue ─────────────────────────────────


async def test_test_endpoint_with_a_sample_event(
    api: TestClient, service: TriggerService, suite: Suite
) -> None:
    wf = workflow(api, WRITE)
    trigger = add(api, wf, on_event())
    sample = {"seq": 99, "type": STATUS, "at": "2026-10-22T10:00:00+02:00",
              "subject": {"kind": "work_item", "id": "555", "label": "Exemple"},
              "data": {"to": "IN_PROGRESS", "secret": "x"}}  # fmt: skip
    run = api.post(f"/api/triggers/{trigger['id']}/test", json={"event": sample}).json()
    assert run["trigger"] == "test" and run["trigger_id"] == trigger["id"]
    assert run["status"] == "awaiting_approval"  # écriture : validation humaine, même en test
    assert run["params"]["titre"] == "Doc #555 Exemple (IN_PROGRESS)"
    assert run["trigger_event"]["seq"] == 99 and "data" not in run["trigger_event"]
    assert api.get("/api/workflow-runs/inbox-count").json() == {"awaiting_approval": 1}
    # Sans événement d'exemple : chemins absents → ""
    bare = api.post(f"/api/triggers/{trigger['id']}/test").json()
    assert bare["params"]["titre"] == "Doc #  ()" and bare["trigger_event"] is None
    state = get(api, trigger)["state"]
    assert state["counters"]["fired"] == 0  # un test ne compte pas
    # Un test en attente compte comme l'exécution en attente du déclencheur : pas de doublon
    suite.projets.events.append(event(6, to="IN_PROGRESS"))
    await service.tick()
    assert get(api, trigger)["state"]["counters"]["waiting"] == 1
    assert approve(api, run)["status"] == "completed" and suite.projets.created
    assert api.post("/api/triggers/inconnu/test").status_code == 404


def test_deleting_a_workflow_deletes_its_triggers(api: TestClient) -> None:
    wf = workflow(api, READ)
    first = add(api, wf, daily())
    second = add(api, wf, on_event())
    assert [t["id"] for t in api.get(f"/api/workflows/{wf}/triggers").json()] == [
        first["id"],
        second["id"],
    ]
    assert api.delete(f"/api/triggers/{first['id']}").status_code == 204
    assert api.delete(f"/api/triggers/{first['id']}").status_code == 404
    assert api.delete(f"/api/workflows/{wf}").status_code == 204
    assert api.get(f"/api/workflows/{wf}/triggers").status_code == 404
    assert api.put(f"/api/triggers/{second['id']}", json=on_event()).status_code == 404


def test_events_catalog(api: TestClient, suite: Suite) -> None:
    suite.viz.mode = "down"
    apps = {a["app"]: a for a in api.get("/api/triggers/events-catalog").json()["apps"]}
    assert set(apps) == {"viz", "tab", "projets"}
    projets = apps["projets"]
    assert projets["status"] == "ok" and projets["color"] == "#94D82D"
    status = next(e for e in projets["events"] if e["type"] == STATUS)
    assert status == {"type": STATUS, "label": "Statut changé",
                      "fields": ["data.project_id", "data.from", "data.to", "subject.id",
                                 "subject.label"]}  # fmt: skip
    deleted = next(e for e in projets["events"] if e["type"] == "projets.work_item.deleted")
    assert deleted["fields"] == ["subject.id", "subject.label"]
    assert apps["viz"]["status"] == "unreachable" and apps["viz"]["events"] == []
    assert apps["tab"]["events"][0]["type"] == "tab.table.changed"


# ─── Validation (422, texte français) ─────────────────────────────


def test_validation_errors(api: TestClient, repo: WorkflowRepository, suite: Suite) -> None:
    wf = workflow(api, READ)

    def refused(body: dict[str, Any], expected: str, target: str = wf) -> None:
        response = api.post(f"/api/workflows/{target}/triggers", json=body)
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert isinstance(detail, str) and expected in detail, detail

    refused(daily(params={"inconnu": "x"}), "Paramètre(s) inconnu(s) du workflow : inconnu")
    refused(on_event(types=["projets.work_item.archived"]), "non déclaré(s) par Atelier Projets")
    refused(on_event(types=["Pas un type"]), "type d'événement invalide")
    refused(on_event(types=[]), "au moins 1")
    refused(on_event(types=[f"projets.t{i}.x" for i in range(11)]), "au plus 10")
    refused(on_event(filters=[{"path": "data.to", "op": "eq", "value": 1}] * 11), "au plus 10")
    refused(on_event(filters=[{"path": "data.to", "op": "in", "value": "x"}]), "« in » attend")
    refused(on_event(debounce_seconds=3601), "inférieur ou égal à 3600")
    refused(on_event(max_runs_per_hour=0), "supérieur ou égal à 1")
    refused(daily(max_runs_per_hour=121), "inférieur ou égal à 120")
    refused(on_event(app="cine"), "valeur attendue")
    refused({"kind": "manuel"}, "« manuel » inconnu")
    refused({"label": "x"}, "champ « kind » obligatoire")
    refused(daily(schedule={"kind": "daily", "at": "25:00", "days": ["mon"]}), "HH:MM")
    refused(daily(schedule={"kind": "daily", "at": "08:00", "days": []}), "au moins 1")
    refused(daily(schedule={"kind": "interval", "every_minutes": 2}), "supérieur ou égal à 5")
    refused(daily(schedule={"kind": "weekly"}), "« weekly » inconnu")
    refused(daily(surprise=True), "champ inconnu")
    # Gabarits {{event.…}} : dans `params` d'un déclencheur événement seulement
    refused(daily(params={"titre": "{{event.subject.id}}"}), "réservés aux déclencheurs sur événement")  # fmt: skip
    refused(on_event(label="Pour {{event.subject.id}}"), "hors des paramètres")
    refused(on_event(filters=[{"path": "subject.id", "op": "eq", "value": "{{event.seq}}"}]), "hors des paramètres")  # fmt: skip
    refused(on_event(params={"titre": "{{params.projet}}"}), "seuls les gabarits")
    refused(on_event(params={"titre": "{{event.payload}}"}), "illisible")
    # Workflow v1 : refusé ; workflow inconnu : 404
    v1 = api.post("/api/workflows", json={"agent": "data_analyst", "title": "v1", "steps": [{"tool": "data_via_list_datasets", "input": {}}]}).json()  # fmt: skip
    refused(daily(), "workflows v2", target=v1["id"])
    assert api.post("/api/workflows/inconnu/triggers", json=daily()).status_code == 404
    # Application qui ne répond pas : accepté, signalé dans last_error
    suite.projets.mode = "down"
    clear_manifest_cache()
    accepted = add(api, wf, on_event(types=["projets.work_item.archived"]))
    assert "Types d'événements non vérifiés" in accepted["state"]["last_error"]
    # Les champs en lecture seule renvoyés par l'interface sont ignorés
    echoed = add(api, wf, daily() | {"id": "x", "state": {"cursor": 3}, "workflow_id": "y"})
    assert echoed["id"] != "x" and echoed["workflow_id"] == wf


# ─── Moteur : concurrence, erreurs, boucle de fond ────────────────


async def test_one_trigger_never_runs_twice_in_parallel(
    api: TestClient, service: TriggerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    wf = workflow(api, READ)
    trigger = add(api, wf, daily())
    active = 0
    peak = 0
    original = service._launch

    async def slow(*args: Any, **kwargs: Any) -> Any:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        try:
            return await original(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(service, "_launch", slow)
    await asyncio.gather(*(service.test(trigger["id"], None) for _ in range(3)))
    assert peak == 1 and len(runs(api, wf)) == 3


async def test_an_error_on_one_trigger_does_not_stop_the_pass(
    api: TestClient,
    service: TriggerService,
    suite: Suite,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite.approval_mode = (
        "writes_only"  # sujet : le moteur des déclencheurs (every_step : plus bas)
    )
    broken_wf = workflow(api, READ, title="Cassé")
    broken = add(api, broken_wf, daily())
    healthy_wf = workflow(api, READ, title="Sain")
    healthy = add(api, healthy_wf, daily())
    original = service._launch

    async def launch(wf: Any, *args: Any) -> Any:
        if wf.id == broken_wf:
            raise RuntimeError("panne simulée")
        return await original(wf, *args)

    monkeypatch.setattr(service, "_launch", launch)
    clock.advance(minutes=31)
    await service.tick()
    state = get(api, broken)["state"]
    assert state["counters"]["errors"] == 1 and "panne simulée" in state["last_error"]
    assert len(runs(api, healthy_wf)) == 1
    assert get(api, healthy)["state"]["counters"]["fired"] == 1
    # Un paramètre obligatoire vidé : erreur de lancement lisible, comptée
    api.put(f"/api/triggers/{healthy['id']}", json=daily(params={"titre": " "}))
    blank = api.put(f"/api/workflows/{healthy_wf}", json={"version": 2, "title": "Sain", "params": [{"name": "projet", "label": "Projet", "default": "1"}, {"name": "titre", "label": "Titre", "default": ""}], "steps": READ}).json()  # fmt: skip
    assert blank["params"][1]["default"] == ""
    clock.advance(days=1)
    await service.tick()
    state = get(api, healthy)["state"]
    assert state["counters"]["errors"] == 1 and "Lancement impossible" in state["last_error"]


async def test_background_loop_survives_exceptions_and_stops_cleanly(
    service: TriggerService, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    passes = 0
    slept = asyncio.Event()
    sleeps: list[float] = []

    async def tick() -> None:
        nonlocal passes
        passes += 1
        if passes <= 2:
            raise RuntimeError("base indisponible")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            slept.set()
            await asyncio.Event().wait()  # dort jusqu'à l'arrêt
        await asyncio.sleep(0)

    monkeypatch.setattr(service, "tick", tick)
    service.sleep = sleep
    with caplog.at_level(logging.WARNING):
        service.start()
        await asyncio.wait_for(slept.wait(), 2)
        assert service.running and passes == 3
        await asyncio.wait_for(service.stop(), 2)
    assert not service.running
    assert "base indisponible" in caplog.text and sleeps[0] == get_settings().triggers_poll_seconds
    await service.stop()  # sans effet une seconde fois


async def test_stop_cancels_a_pass_that_does_not_finish(
    service: TriggerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    cancelled = False

    async def stuck() -> None:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr(service, "tick", stuck)
    monkeypatch.setattr(service_module, "STOP_GRACE_SECONDS", 0.05)
    service.start()
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(service.stop(), 2)
    assert cancelled and not service.running


def test_lifespan_starts_and_stops_the_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[TriggerService] = []

    class Stub:
        def __init__(self) -> None:
            self.running = False
            self.stopped = False

        def start(self) -> None:
            self.running = True
            started.append(self)  # type: ignore[arg-type]

        async def stop(self) -> None:
            self.running = False
            self.stopped = True

    class NoAttachments:
        async def purge_orphans(self) -> int:
            return 0

    monkeypatch.setattr(main.settings, "db_auto_migrate", False)
    monkeypatch.setattr(main, "get_attachment_repository", NoAttachments)
    monkeypatch.setattr(main, "background_triggers", Stub)
    monkeypatch.setattr(main.settings, "triggers_enabled", True)
    with TestClient(app):
        assert started and started[0].running
    assert started[0].stopped and not started[0].running
    monkeypatch.setattr(main.settings, "triggers_enabled", False)
    with TestClient(app):
        pass
    assert len(started) == 1  # coupée (TRIGGERS_ENABLED=false) : jamais démarrée


def test_settings_timezone_is_checked() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    assert Settings(_env_file=None).timezone == "Europe/Paris"  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="Fuseau horaire inconnu"):
        Settings(_env_file=None, timezone="Lune/Tranquillité")  # type: ignore[call-arg]


# ─── Migration ────────────────────────────────────────────────────


def test_migration_0007_up_and_down(tmp_path: Path) -> None:
    db = tmp_path / "nexus.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "0006_workflow_runs")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workflows (id, version, agent, title, description, steps, params, "
            "run_count, created_at, updated_at) VALUES ('w1', 2, NULL, 't', '', '[]', '[]', 0, "
            "'2026-10-22', '2026-10-22')"
        )
        conn.execute(
            'INSERT INTO workflow_runs (id, workflow_id, status, message, params, "trigger", '
            "steps, artifacts, pending, state, created_at, updated_at) VALUES ('r1', 'w1', "
            "'completed', '', '{}', 'manual', '[]', '[]', '[]', '{}', '2026-10-22', '2026-10-22')"
        )
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
        trigger_columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_triggers)")}
        assert list(conn.execute("SELECT trigger_id, trigger_event FROM workflow_runs")) == [
            (None, None)
        ]
        conn.execute(
            "INSERT INTO workflow_triggers (id, workflow_id, kind, label, enabled, app, params, "
            "max_runs_per_hour, config, state, internal, created_at, updated_at) VALUES "
            "('t1', 'w1', 'event', '', 1, 'projets', '{}', 12, '{}', '{}', '{}', "
            "'2026-10-22', '2026-10-22')"
        )
        conn.execute("UPDATE workflow_runs SET \"trigger\" = 'event', trigger_id = 't1'")
        conn.execute(
            "INSERT INTO trigger_cursors (app, seq, updated_at) VALUES ('projets', 8, 'x')"
        )
    assert {"workflow_triggers", "trigger_cursors"} <= tables
    assert {"trigger_id", "trigger_event"} <= run_columns
    assert {"workflow_id", "kind", "app", "config", "state", "internal"} <= trigger_columns  # fmt: skip
    command.downgrade(cfg, "0006_workflow_runs")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
        kept = list(conn.execute('SELECT id, "trigger" FROM workflow_runs'))
    assert "workflow_triggers" not in tables and "trigger_cursors" not in tables
    assert "trigger_id" not in run_columns and kept == [("r1", "manual")]
    command.upgrade(cfg, "head")  # remontée possible après la descente
