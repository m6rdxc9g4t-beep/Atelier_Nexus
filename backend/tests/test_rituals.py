"""Rituels de l'équipe : gabarits valides, installation (workflow + déclencheur), sans modèle."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_env_factory
from app.team_rituals import PREFIX, RITUALS, marker
from app.tools.environment import ToolEnvironment
from main import app
from tests.test_suite_nodes import Suite, suite  # noqa: F401  (fixture)
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


def test_ritual_is_recognised_by_its_marker_not_its_title(team_api: TestClient) -> None:
    # Un workflow de l'utilisateur au même titre ne bloque pas l'installation
    same_title = {**RITUALS[0].workflow, "description": "Mon workflow à moi."}
    assert team_api.post("/api/workflows", json=same_title).status_code == 201
    out = team_api.post("/api/equipe/rituels/point-lundi")
    assert out.status_code == 201, out.text
    workflow_id = out.json()["workflow_id"]
    wf = team_api.get(f"/api/workflows/{workflow_id}").json()
    assert marker("point-lundi") in wf["description"]
    # Renommé : toujours reconnu, pas réinstallable
    renamed = {**RITUALS[0].workflow, "title": "Mon point du lundi"}
    res = team_api.put(f"/api/workflows/{workflow_id}", json=renamed)
    assert res.status_code == 200, res.text
    assert team_api.post("/api/equipe/rituels/point-lundi").status_code == 409


def test_failed_trigger_rolls_back_and_keeps_the_original_error(
    team_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import equipe as api_equipe

    async def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("déclencheur refusé")

    async def broken_delete(*args: object, **kwargs: object) -> None:
        raise OSError("suppression impossible")

    service: object = None

    real_install = api_equipe._install

    async def spy(found, svc, *rest):  # type: ignore[no-untyped-def]
        nonlocal service
        service = svc
        monkeypatch.setattr(svc.triggers, "create", refuse)
        monkeypatch.setattr(svc.workflows, "delete", broken_delete)
        return await real_install(found, svc, *rest)

    monkeypatch.setattr(api_equipe, "_install", spy)
    with pytest.raises(RuntimeError, match="déclencheur refusé"):
        team_api.post("/api/equipe/rituels/point-lundi")
    assert service is not None


async def test_concurrent_installs_create_a_single_ritual(team_api: TestClient) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://nexus") as client:
        results = await asyncio.gather(
            *(client.post("/api/equipe/rituels/retours-vendredi") for _ in range(3))
        )
    assert sorted(r.status_code for r in results) == [201, 409, 409]
    rituals = [
        w for w in team_api.get("/api/workflows").json()
        if marker("retours-vendredi") in (w.get("description") or "")
    ]  # fmt: skip
    assert len(rituals) == 1


def test_friday_ritual_end_to_end(api: TestClient, suite: Suite) -> None:  # noqa: F811
    """Rituel du vendredi exécuté pour de vrai (doubles fidèles) : synthèse puis note, chaque
    étape validée ; le journal reçoit le Markdown brut ; sans formulaire ouvert, pas de note."""
    from app.tools import equipe
    from tests.fake_wiki_formulaire import FakeFormulaire, FakeWiki
    from tests.test_workflows_v2 import decide

    wiki, form = FakeWiki(), FakeFormulaire()

    def env() -> ToolEnvironment:
        base = suite.env(
            wiki_base_url="http://127.0.0.1:3200/api",
            formulaire_base_url="http://127.0.0.1:3300/api",
        )
        return ToolEnvironment(
            base.settings,
            transports={"wiki": httpx.MockTransport(wiki), "formulaire": httpx.MockTransport(form)},
        )

    app.dependency_overrides[get_env_factory] = lambda: env
    workflow_id = api.post("/api/equipe/rituels/retours-vendredi").json()["workflow_id"]
    run = api.post(f"/api/workflows/{workflow_id}/run", json={"params": {}}).json()
    assert run["status"] == "awaiting_approval"
    run = decide(api, run)  # synthèse
    assert run["status"] == "awaiting_approval", run
    run = decide(api, run)  # note au journal (entrée résolue montrée avant)
    assert run["status"] == "completed", run
    journal = next(p for p in wiki.pages.values() if p["title"] == equipe.JOURNAL)
    assert "Rituel du vendredi — Retours des formulaires" in journal["content"]
    assert "Satisfaction atelier" in journal["content"] and "<donnee" not in journal["content"]
    assert "alice@exemple.fr" not in journal["content"]
    # Aucun formulaire ouvert : la note est sautée (condition `not_empty`)
    form.forms[1]["status"] = "closed"
    run = api.post(f"/api/workflows/{workflow_id}/run", json={"params": {}}).json()
    run = decide(api, run)
    assert run["status"] == "completed", run
    assert journal["content"].count("· Rituel du vendredi") == 1


def test_friday_ritual_skips_the_note_without_open_forms(team_api: TestClient) -> None:
    (step,) = [s for s in RITUALS[1].workflow["steps"] if s["id"] == "journal"]
    assert step["when"] == {"left": "{{steps.synthese.data.forms}}", "op": "not_empty"}
    assert step["input"]["texte"] == "{{steps.synthese.data.markdown}}"
    (step,) = [s for s in RITUALS[0].workflow["steps"] if s["id"] == "journal"]
    assert step["input"]["texte"] == "{{steps.rapport.data.markdown}}"


def test_failed_trigger_leaves_no_half_installed_ritual(
    team_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import equipe as api_equipe

    real_install = api_equipe._install

    async def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("déclencheur refusé")

    async def spy(found, svc, *rest):  # type: ignore[no-untyped-def]
        monkeypatch.setattr(svc.triggers, "create", refuse)
        return await real_install(found, svc, *rest)

    monkeypatch.setattr(api_equipe, "_install", spy)
    with pytest.raises(RuntimeError):
        team_api.post("/api/equipe/rituels/point-lundi")
    workflows = team_api.get("/api/workflows").json()
    assert not [w for w in workflows if marker("point-lundi") in (w.get("description") or "")]
