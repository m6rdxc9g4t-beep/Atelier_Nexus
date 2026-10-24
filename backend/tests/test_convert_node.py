"""Atelier Convert dans les workflows v2 : nœud `atelier-node/1` (actions, événements, écriture
validée sur son entrée résolue, idempotence). Double fidèle : tests/fake_convert.py, manifeste
produit par le code d'Atelier Convert."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.triggers.service import TriggerService
from tests.test_suite_nodes import Suite
from tests.test_triggers import FakeClock, add, api, clock, runs, service, triggers, workflow  # noqa: F401
from tests.test_workflows_v2 import decide

URL = "http://127.0.0.1:8010/api"
CONV = "a1b2c3d4e5f6"


@pytest.fixture(autouse=True)
def convert_on(suite: Suite) -> None:
    suite.convert_url = URL


async def test_convert_is_a_node_with_its_actions_and_events(suite: Suite) -> None:
    env = suite.env()
    try:
        state = await env.suite().state("convert")
    finally:
        await env.aclose()
    assert state.status == "ok" and state.transport == "http" and not state.ignored
    actions = {a.id: a.kind for a in state.manifest.actions}  # type: ignore[union-attr]
    assert actions == {
        "conversions.list": "read", "conversions.table": "read",
        "conversions.convert_file": "write", "tab.projects": "read",
        "conversions.send_to_tab": "write", "conversions.delete": "destructive",
    }  # fmt: skip
    events = {e.type for e in state.manifest.events}  # type: ignore[union-attr]
    assert "convert.conversion.created" in events and "convert.conversion.sent_to_tab" in events


def test_events_catalog_lists_convert(api: TestClient) -> None:  # noqa: F811
    apps = {a["app"]: a for a in api.get("/api/triggers/events-catalog").json()["apps"]}
    convert = apps["convert"]
    assert convert["status"] == "ok" and convert["color"] == "#C9951D"
    created = next(e for e in convert["events"] if e["type"] == "convert.conversion.created")
    assert "data.statement" in created["fields"] and "subject.id" in created["fields"]


def test_convert_to_tab_workflow_waits_for_each_validation(
    client: TestClient, suite: Suite
) -> None:
    """Lire l'historique, puis envoyer la dernière conversion dans Atelier Tab : l'envoi attend
    « Autoriser » sur son entrée RÉSOLUE, puis part avec une clé d'idempotence (pas de doublon)."""
    steps = [
        {"id": "lister", "label": "", "uses": "node:convert/conversions.list", "input": {},
         "needs": [], "on_error": "stop"},
        {"id": "envoyer", "label": "", "uses": "node:convert/conversions.send_to_tab",
         "input": {"conversion_id": "{{steps.lister.data[0].id}}", "project_id": "proj_budget",
                   "table_name": "{{steps.lister.data[0].name}}"},
         "needs": ["lister"], "on_error": "stop"},
    ]  # fmt: skip
    body: dict[str, Any] = {"version": 2, "agent": None, "title": "Relevé → Tab", "description": "",
                            "params": [], "steps": steps}  # fmt: skip
    created = client.post("/api/workflows", json=body)
    assert created.status_code == 201, created.text
    run = client.post(f"/api/workflows/{created.json()['id']}/run", json={"params": {}}).json()
    assert run["status"] == "awaiting_approval" and run["pending"][0]["kind"] == "read"
    run = decide(client, run)
    pending = run["pending"][0]
    assert pending["step_id"] == "envoyer" and pending["kind"] == "write"
    assert pending["input"] == {
        "conversion_id": CONV, "project_id": "proj_budget", "table_name": "Relevé octobre",
    }  # fmt: skip
    assert not suite.convert.sent  # rien d'envoyé avant validation
    run = decide(client, run)
    assert run["status"] == "completed", run["message"]
    (sent,) = suite.convert.sent
    assert sent["table_name"] == "Relevé octobre" and sent["rows"] == 3
    (post,) = [r for r in suite.convert.requests if r.method == "POST"]
    assert post.headers["idempotency-key"].startswith("nexus:") and post.url.path.endswith(
        f"/conversions/{CONV}/send-to-tab"
    )


async def test_new_conversion_event_launches_a_run_that_waits(
    api: TestClient,  # noqa: F811
    service: TriggerService,  # noqa: F811
    suite: Suite,
    clock: FakeClock,  # noqa: F811
) -> None:
    """Une conversion créée dans Convert lance le workflow ; l'envoi dans Tab attend toujours."""
    steps = [
        {"id": "envoyer", "label": "", "uses": "node:convert/conversions.send_to_tab",
         "input": {"conversion_id": "{{params.projet}}", "project_id": "proj_budget"},
         "needs": [], "on_error": "stop"},
    ]  # fmt: skip
    wf = workflow(api, steps, title="Relevé → Tab")
    trigger = {"kind": "event", "label": "Nouveau relevé", "app": "convert",
               "types": ["convert.conversion.created"],
               "filters": [{"path": "data.statement", "op": "eq", "value": True}],
               "params": {"projet": "{{event.subject.id}}"}}  # fmt: skip
    add(api, wf, trigger)
    await service.tick()
    assert runs(api, wf) == []  # événements antérieurs au déclencheur : ignorés
    suite.convert.events.append(
        {"seq": 2, "type": "convert.conversion.created", "at": "2026-10-24T10:00:00Z",
         "subject": {"kind": "conversion", "id": CONV, "label": "Relevé octobre"},
         "data": {"name": "Relevé octobre", "format": "pdf", "rows": 3, "columns": 4,
                  "statement": True, "ocr": False, "origin": "interface"}}
    )  # fmt: skip
    clock.advance(minutes=1)
    await service.tick()
    [run] = runs(api, wf)
    assert run["status"] == "awaiting_approval" and run["trigger"] == "event"
    assert run["pending"][0]["input"]["conversion_id"] == CONV
    assert not suite.convert.sent
