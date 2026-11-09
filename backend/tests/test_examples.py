"""Exemples de la suite (`exemples-suite/`, docs/exemples-suite.md) : fichiers livrés, résolution
des références, workflows et déclencheur créés, rechargement, retrait.

Applications simulées : nœuds de `tests/fake_suite.py` ; les lectures de Viz et Projets sont
remplacées par des réponses fixes quand le test porte sur la résolution.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_trigger_repository
from app.db.triggers import TriggerRepository
from app.db.workflows import WorkflowRepository
from app.examples import (
    REPO_DIR,
    Resolved,
    alert_trigger,
    dataset_id,
    mark_of,
    part,
    stories,
    story_id,
    workflow_body,
)
from app.suite.nodes import NodeResult, SuiteNodes
from app.workflows_v2.library import TEMPLATES
from main import app
from tests.test_suite_nodes import Suite
from tests.test_workflow_library import real

BY_SLUG = {t.slug: t for t in TEMPLATES}
GARANCE = "studio-garance"


@pytest.fixture
def api(client: TestClient, repo: WorkflowRepository, suite: Suite) -> Iterator[TestClient]:
    real(suite)  # manifestes réels : les modèles de la bibliothèque y sont valides
    app.dependency_overrides[get_trigger_repository] = lambda: TriggerRepository(repo.sessions)
    yield client


@pytest.fixture
def apps_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Viz et Projets répondent avec l'exemple de Studio Garance chargé."""
    real = SuiteNodes.run_action

    async def fake(self: SuiteNodes, app_id: str, action: str, payload: dict[str, Any], **kw: Any):
        if (app_id, action) == ("viz", "datasets.list"):
            return NodeResult(
                "",
                [
                    {"id": "aaaaaaaaaaaa", "name": "Autre", "origin": None},
                    {
                        "id": "0123456789ab",
                        "name": "Opérations",
                        "origin": {
                            "kind": "atelier-table",
                            "key": "exemple:studio-garance:operations",
                        },
                    },
                ],
            )
        if (app_id, action) == ("projets", "projects.list"):
            return NodeResult("", [{"id": 7, "name": "Gestion 2026 — Studio Garance"}])
        if (app_id, action) == ("projets", "projects.tree"):
            assert payload == {"project_id": 7}
            return NodeResult(
                "",
                {
                    "phases": [
                        {
                            "epics": [
                                {
                                    "stories": [
                                        {"id": 41, "title": "Clôture d'août"},
                                        {"id": 42, "title": "Suivi des budgets"},
                                    ]
                                }
                            ]
                        }
                    ]
                },
            )
        return await real(self, app_id, action, payload, **kw)

    monkeypatch.setattr(SuiteNodes, "run_action", fake)


# ─── Fichiers livrés ──────────────────────────────────────────────


def test_chaque_histoire_cite_des_modeles_de_la_bibliotheque() -> None:
    found = stories(REPO_DIR)
    assert len(found) >= 9
    for story in found:
        assert [s["app"] for s in story["parcours"]][:2] == ["convert", "tab"]
        data = part(REPO_DIR, story["id"])
        assert data["histoire"]["id"] == story["id"]
        assert data["workflows"], story["id"]
        for item in data["workflows"]:
            assert item["modele"] in BY_SLUG, item
        refs = data["references"]
        assert refs["tab_tables"][0] == f"tbl_ex_{story['id']}_0"
        for key in ("tab_projet", "viz_jeu_cle", "viz_alerte", "projets_projet", "projets_story"):
            assert refs.get(key), (story["id"], key)


def test_jamais_de_chemin_libre() -> None:
    from app.examples import ExampleError

    for bad in ("../index", "inconnue", "index"):
        with pytest.raises(ExampleError):
            part(REPO_DIR, bad)


# ─── Logique pure ─────────────────────────────────────────────────


def test_resolution_et_corps() -> None:
    assert dataset_id([{"id": "x", "origin": {"key": "k"}}], "k") == "x"
    assert dataset_id([{"id": "x", "origin": {"kind": "file"}}], "k") is None
    assert dataset_id(None, "k") is None
    tree = {"phases": [{"epics": [{"stories": [{"id": 3, "title": "A"}]}]}]}
    assert story_id(tree, "A") == 3
    assert story_id(tree, "B") is None

    data = part(REPO_DIR, GARANCE)
    resolved = Resolved(jeu="0123456789ab", story=42)
    body = workflow_body(BY_SLUG["viz-alerte-tache-projets"], data, resolved)
    assert body.title.endswith("· Studio Garance")
    assert len(body.description) <= 500
    assert mark_of(body.description) == GARANCE
    defaults = {p.name: p.default for p in body.params}
    assert defaults["jeu"] == "0123456789ab"
    assert defaults["story"] == "42"
    assert defaults["alerte"] == data["references"]["viz_alerte"]
    convert = workflow_body(BY_SLUG["convert-derniere-conversion-tab-viz"], data, resolved)
    assert {p.name: p.default for p in convert.params}["projet_tab"] == "prj_ex_studio-garance"

    planning = workflow_body(
        BY_SLUG["tab-planning-vers-projets"],
        part(REPO_DIR, "renovation-urbaine"),
        Resolved(projet=7),
    )
    assert {p.name: p.default for p in planning.params} == {
        "table": "tbl_ex_renovation-urbaine_1",
        "projet": "7",
        "type": "TASK",
    }
    temps = workflow_body(BY_SLUG["projets-temps-hebdo-viz"], data, resolved)
    assert {p.name: p.default for p in temps.params}["cle_temps"] == "exemple:studio-garance:temps"

    on = alert_trigger(data, resolved)
    assert on["enabled"] is True and on["params"]["story"] == "42"
    assert on["filters"] == [
        {"path": "subject.label", "op": "eq", "value": data["references"]["viz_alerte"]}
    ]
    off = alert_trigger(data, Resolved())
    assert off["enabled"] is False and "story" not in off["params"]


def test_marque_absente_ou_modifiee() -> None:
    assert mark_of("Un workflow à moi") is None
    assert mark_of("… [exemple:studio-garance] et une suite") is None


# ─── API ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("apps_answer")
def test_charger_recharger_retirer(api: TestClient, suite: Suite) -> None:
    listing = api.get("/api/exemples-suite").json()
    assert [h["id"] for h in listing["histoires"]][0] == GARANCE
    assert listing["histoires"][0]["workflows"] == []

    res = api.post(f"/api/exemples-suite/{GARANCE}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["jeu"] == "0123456789ab" and body["story"] == 42
    assert body["tab"] is True
    assert len(body["workflows"]) == 2 and body["trigger_id"]
    assert body["notes"] == []
    calls = suite.mcp_calls()
    assert {"name": "load_suite_example", "arguments": {"example": GARANCE}} in calls

    workflows = {w["id"]: w for w in api.get("/api/workflows").json()}
    alert = next(w for w in workflows.values() if "Alerte Viz" in w["title"])
    assert {p["name"]: p["default"] for p in alert["params"]}["story"] == "42"
    triggers = api.get(f"/api/workflows/{alert['id']}/triggers").json()
    assert len(triggers) == 1 and triggers[0]["enabled"] is True
    assert triggers[0]["params"]["story"] == "42"

    # Un workflow de l'utilisateur n'est jamais touché
    step = {"id": "jeux", "uses": "node:viz/datasets.list", "label": "Jeux", "input": {}}
    mine = api.post("/api/workflows", json={"version": 2, "title": "À moi", "steps": [step]})
    assert mine.status_code == 201, mine.text

    again = api.post(f"/api/exemples-suite/{GARANCE}").json()
    assert len(again["workflows"]) == 2
    titles = [w["title"] for w in api.get("/api/workflows").json()]
    assert len(titles) == 3 and "À moi" in titles
    listing = api.get("/api/exemples-suite").json()
    assert len(listing["histoires"][0]["workflows"]) == 2

    removed = api.delete(f"/api/exemples-suite/{GARANCE}")
    assert removed.json() == {"histoire": GARANCE, "retires": 2}
    assert [w["title"] for w in api.get("/api/workflows").json()] == ["À moi"]
    assert {"name": "remove_suite_example", "arguments": {"example": GARANCE}} in suite.mcp_calls()


def test_applications_absentes_dites_en_clair(api: TestClient, suite: Suite) -> None:
    suite.mcp = False
    body = api.post("/api/exemples-suite/freelance-data").json()
    assert body["tab"] is False
    assert body["jeu"] is None and body["story"] is None
    assert any("jeu" in n for n in body["notes"]) and any("story" in n for n in body["notes"])
    workflows = api.get("/api/workflows").json()
    assert len(workflows) == len(body["workflows"]) >= 1
    if body["trigger_id"]:
        alert = next(w for w in workflows if "Alerte Viz" in w["title"])
        trig = api.get(f"/api/workflows/{alert['id']}/triggers").json()[0]
        assert trig["enabled"] is False


def test_modele_refuse_par_un_manifeste_dit_en_clair(
    client: TestClient, repo: WorkflowRepository
) -> None:
    # Manifestes simulés (actions aux noms supposés) : les modèles n'y sont pas valides
    app.dependency_overrides[get_trigger_repository] = lambda: TriggerRepository(repo.sessions)
    body = client.post(f"/api/exemples-suite/{GARANCE}").json()
    assert body["workflows"] == []
    assert any("non créé" in n for n in body["notes"])


def test_histoire_inconnue(api: TestClient) -> None:
    assert api.post("/api/exemples-suite/inconnue").status_code == 404
    assert api.delete("/api/exemples-suite/inconnue").status_code == 404
    assert api.post("/api/exemples-suite/..%2Findex").status_code in (404, 405)
