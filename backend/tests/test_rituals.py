"""Rituels de l'équipe : gabarits valides, installation (workflow + déclencheur), sans modèle."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_env_factory
from app.team_rituals import PREFIX, RITUALS
from app.tools.environment import ToolEnvironment
from main import app
from tests.test_suite_nodes import Suite
from tests.test_triggers import api, clock, triggers  # noqa: F401  (fixtures)


@pytest.fixture
def team_api(api: TestClient, suite: Suite) -> Iterator[TestClient]:  # noqa: F811
    """Toutes les applications des rituels configurées (aucune n'est appelée à l'installation)."""

    def env() -> ToolEnvironment:
        return suite.env(
            wiki_base_url="http://127.0.0.1:3200/api",
            formulaire_base_url="http://127.0.0.1:3300/api",
            tresorerie_base_url="http://127.0.0.1:5050/api",
        )

    app.dependency_overrides[get_env_factory] = lambda: env
    yield api


def test_rituals_never_call_a_model() -> None:
    for r in RITUALS:
        uses = [s["uses"] for s in r.workflow["steps"]]
        assert all(u.startswith("tool:") for u in uses) and "tool:delegate_to_agent" not in uses
        assert r.workflow["title"].startswith(PREFIX) and r.trigger["kind"] == "schedule"
        assert r.trigger["max_runs_per_hour"] == 1


def test_list_shows_what_is_missing(api: TestClient) -> None:  # noqa: F811
    items = {r["id"]: r for r in api.get("/api/equipe/rituels").json()}
    assert set(items) == {"point-lundi", "retours-vendredi", "tresorerie-lundi"}
    assert items["point-lundi"]["missing"] == ["Atelier Wiki"]  # Projets configuré, Wiki non
    assert items["tresorerie-lundi"]["missing"] == ["Atelier Trésorerie"]
    assert all(r["workflow_id"] is None for r in items.values())
    out = api.post("/api/equipe/rituels/point-lundi")
    assert out.status_code == 422 and "Atelier Wiki" in out.json()["detail"]


def test_install_creates_workflow_and_schedule(team_api: TestClient) -> None:
    out = team_api.post("/api/equipe/rituels/point-lundi")
    assert out.status_code == 201, out.text
    workflow_id = out.json()["workflow_id"]
    wf = team_api.get(f"/api/workflows/{workflow_id}").json()
    assert (
        wf["version"] == 2
        and wf["agent"] is None
        and wf["title"] == "Rituel · Point d'avancement du lundi"
    )
    assert [s["uses"] for s in wf["steps"]] == ["tool:equipe_point_avancement", "tool:equipe_noter"]
    (trigger,) = team_api.get(f"/api/workflows/{workflow_id}/triggers").json()
    assert trigger["schedule"] == {"kind": "daily", "at": "08:30", "days": ["mon"]}
    assert trigger["enabled"] and trigger["state"]["next_fire_at"]
    again = team_api.post("/api/equipe/rituels/point-lundi")
    assert again.status_code == 409
    listed = {r["id"]: r for r in team_api.get("/api/equipe/rituels").json()}
    assert (
        listed["point-lundi"]["workflow_id"] == workflow_id
        and listed["point-lundi"]["missing"] == []
    )

    for ritual_id in ("retours-vendredi", "tresorerie-lundi"):
        res = team_api.post(f"/api/equipe/rituels/{ritual_id}")
        assert res.status_code == 201, res.text
    finance = next(
        w
        for w in team_api.get("/api/workflows").json()
        if w["title"].endswith("trésorerie du lundi")
    )
    assert finance["agent"] == "finance"
    assert team_api.post("/api/equipe/rituels/inconnu").status_code == 404


def test_installed_ritual_runs_and_waits_for_approval(team_api: TestClient) -> None:
    """Lancé comme par le déclencheur : en every_step, la première étape attend « Autoriser »."""
    workflow_id = team_api.post("/api/equipe/rituels/point-lundi").json()["workflow_id"]
    run: dict[str, Any] = team_api.post(
        f"/api/workflows/{workflow_id}/run", json={"params": {}}
    ).json()
    assert run["status"] == "awaiting_approval"
    assert run["steps"][0]["id"] == "rapport"
