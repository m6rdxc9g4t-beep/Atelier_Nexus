"""Bibliothèque de modèles de workflows de la suite (`GET /api/workflows/library`).

Chaque modèle est validé par le moteur v2 contre les MANIFESTES RÉELS de Viz, Projets, Tab et
Convert (`tests/fixtures/<app>/manifest.json`), servis par les doubles de la suite
(httpx.MockTransport, dossier `_atelier/` et faux serveur MCP de Tab) : aucun réseau.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.schemas.workflows_v2 import WorkflowV2
from app.suite.apps import NODE_APPS
from app.suite.nodes import clear_manifest_cache
from app.tools.toolsets import get_toolset
from app.workflows_v2 import library as library_module
from app.workflows_v2.engine import gate_problems
from app.workflows_v2.library import COLUMN_WIDTH, TEMPLATES, as_fields, layered, missing_for
from app.workflows_v2.steps import StepRegistry, parse_uses
from app.workflows_v2.templates import refs_in
from app.workflows_v2.validation import blocking, validate_workflow
from tests.fake_suite import REAL_MANIFESTS, RELEVE_ID, FakeConvertNode, write_tab_manifest
from tests.test_suite_nodes import Suite

BY_SLUG = {t.slug: t for t in TEMPLATES}

#: Valeurs de lancement plausibles des paramètres sans défaut (identifiants à saisir)
SAMPLE = {
    "projet_tab": "proj_budget",
    "conversion": RELEVE_ID,
    "projet": "12",
    "element_suivi": "30001",
    "story": "2",
    "jeu": "0123456789ab",
}


def real(suite: Suite) -> Suite:
    """Les doubles servent les manifestes réels (Convert l'utilise déjà)."""
    suite.viz.manifest = REAL_MANIFESTS["viz"]
    suite.projets.manifest = REAL_MANIFESTS["projets"]
    write_tab_manifest(suite.exports, REAL_MANIFESTS["tab"])
    (suite.log.parent / "mcp_manifest.json").write_text(
        (suite.exports / "_atelier" / "manifest.json").read_text()
    )
    return suite


@pytest.fixture
def real_suite(suite: Suite) -> Suite:
    return real(suite)


async def registry_of(suite: Suite, **settings: Any) -> StepRegistry:
    env = suite.env(**settings)
    try:
        return await StepRegistry.build(env, None)
    finally:
        await env.aclose()


# ─── Données ──────────────────────────────────────────────────────


def test_templates_are_well_formed() -> None:
    assert len(TEMPLATES) == 7 and len(BY_SLUG) == len(TEMPLATES)  # slugs uniques
    for t in TEMPLATES:
        assert t.slug.islower() and " " not in t.slug
        assert t.title and t.value and t.requirements and len(t.description) <= 500
        assert len(t.title) <= 120 and len(t.params) <= 10
        assert all(p.label and len(p.label) <= 80 for p in t.params)
        assert t.apps and set(t.apps) <= set(NODE_APPS)
        assert t.available is False and t.missing == []  # calculés par la route
        # Applications des étapes : toutes annoncées par les puces du modèle
        touched = []
        for step in t.steps:
            parsed = parse_uses(step.uses)
            assert parsed is not None, step.uses
            source, name, _ = parsed
            touched.append(name if source == "node" else get_toolset(_toolset(name)).app)
        assert set(touched) <= set(t.apps), t.slug
        # Jamais de fichier en base64 dans un workflow (historique des exécutions)
        assert all(s.uses != "node:convert/conversions.convert_file" for s in t.steps)
        assert all(s.label for s in t.steps)


def _toolset(tool: str) -> str:
    return {
        "tab_check_table": "tab",
        "projets_preview_tab_import": "tab_projets",
        "projets_import_tab_table": "tab_projets",
    }[tool]


def test_positions_are_layered_left_to_right() -> None:
    for t in TEMPLATES:
        by_id = {s.id: s for s in t.steps}
        for step in t.steps:
            assert step.position is not None, (t.slug, step.id)
            for need in step.needs:
                upstream = by_id[need].position
                assert upstream is not None and upstream.x < step.position.x
        spots = {(s.position.x, s.position.y) for s in t.steps if s.position}
        assert len(spots) == len(t.steps), t.slug  # aucun nœud superposé
    # Colonnes centrées : deux branches sous une racine
    first = BY_SLUG["convert-derniere-conversion-tab-viz"].steps
    pos = {s.id: s.position for s in first}
    assert pos["historique"] is not None and pos["vers_tab"] is not None
    assert pos["lignes"] is not None and pos["par_mois"] is not None
    assert pos["historique"].x == 0 and pos["par_mois"].x == 3 * COLUMN_WIDTH
    assert pos["vers_tab"].x == pos["lignes"].x == COLUMN_WIDTH
    assert pos["historique"].y == (pos["vers_tab"].y + pos["lignes"].y) / 2
    assert layered([]) == []


# ─── Validation par le moteur, manifestes réels ───────────────────


async def test_each_template_passes_the_engine_validation(real_suite: Suite) -> None:
    registry = await registry_of(real_suite)
    for t in TEMPLATES:
        result = validate_workflow(as_fields(t), registry)
        # Ids, needs sans cycle, gabarits vers des ancêtres seulement, paramètres déclarés,
        # uses connus : aucune erreur, pas même celles tolérées pour un brouillon
        assert result.ok, (t.slug, [(e.step_id, e.code, e.message) for e in result.errors])
        assert blocking(result) == []
        assert set(result.order) == {s.id for s in t.steps}
        assert missing_for(t, registry) == [], t.slug
        declared = {p.name for p in t.params}
        cited = {r.name for s in t.steps for _, r in refs_in(s.input) if r.kind == "param"}
        assert cited == declared, t.slug  # chaque paramètre sert, aucun n'est oublié


async def test_gate_accepts_plausible_launch_values(real_suite: Suite) -> None:
    """Porte de contrôle du lancement : avec les défauts et des identifiants plausibles, les
    entrées connues avant l'exécution (paramètres convertis en nombres…) sont acceptées."""
    registry = await registry_of(real_suite)
    now = datetime.now(UTC)
    for t in TEMPLATES:
        values = {p.name: p.default or SAMPLE[p.name] for p in t.params}
        workflow = WorkflowV2(
            id="modele", agent=None, title=t.title, description=t.description, steps=t.steps,
            params=t.params, created_at=now, updated_at=now,
        )  # fmt: skip
        assert gate_problems(workflow, registry, values) == [], t.slug


def test_templates_can_be_saved_as_suite_workflows(client: TestClient, real_suite: Suite) -> None:
    for t in TEMPLATES:
        body = as_fields(t).model_dump(mode="json")
        response = client.post("/api/workflows", json=body)
        assert response.status_code == 201, (t.slug, response.text)
        assert [s["position"] for s in response.json()["steps"]] == [
            s.position.model_dump() if s.position else None for s in t.steps
        ]


# ─── Route ────────────────────────────────────────────────────────


def test_library_route_with_every_app_up(client: TestClient, real_suite: Suite) -> None:
    response = client.get("/api/workflows/library")
    assert response.status_code == 200
    listed = response.json()
    assert [t["slug"] for t in listed] == [t.slug for t in TEMPLATES]
    assert all(t["available"] and t["missing"] == [] for t in listed)
    first = listed[0]
    assert set(first) == {
        "slug", "title", "description", "value", "apps", "params", "steps", "requirements",
        "trigger_hint", "available", "missing",
    }  # fmt: skip
    assert first["apps"] == ["convert", "tab", "viz"]
    assert first["steps"][0]["uses"] == "node:convert/conversions.list"
    assert first["steps"][0]["position"] == {"x": 0.0, "y": 65.0}  # centrée sur 2 branches
    weekly = next(t for t in listed if t["slug"] == "projets-temps-hebdo-viz")
    assert "lundi à 08:00" in weekly["trigger_hint"]
    alert = next(t for t in listed if t["slug"] == "viz-alerte-tache-projets")
    assert "viz.alert.triggered" in alert["trigger_hint"]


def test_library_route_says_what_is_missing(client: TestClient, real_suite: Suite) -> None:
    real_suite.convert.mode = "down"
    real_suite.mcp = False  # sans TAB_MCP_COMMAND : actions de Tab impossibles
    response = client.get("/api/workflows/library")
    assert response.status_code == 200  # une application arrêtée ne fait jamais échouer la route
    listed = {t["slug"]: t for t in response.json()}
    first = listed["convert-derniere-conversion-tab-viz"]
    assert first["available"] is False
    assert first["missing"] == [
        "node:convert/conversions.list : Atelier Convert injoignable",
        "node:convert/conversions.send_to_tab : Atelier Convert injoignable",
        "node:convert/conversions.table : Atelier Convert injoignable",
    ]
    budget = listed["convert-releve-budget-tab-viz"]
    assert "node:convert/conversions.table : Atelier Convert injoignable" in budget["missing"]
    assert (
        "node:tab/rows.add : TAB_MCP_COMMAND non défini : actions d'Atelier Tab impossibles"
        in budget["missing"]
    )
    # Sans Convert ni MCP : les modèles Projets / Viz et l'import par instantané restent possibles
    assert listed["tab-planning-vers-projets"]["available"] is True
    assert listed["projets-temps-hebdo-viz"]["available"] is True
    assert listed["tab-controle-qualite-projets"]["available"] is False
    # Convert arrêté : l'échec est gardé 10 s, la galerie rouverte ne le réinterroge pas
    tried = len(real_suite.convert.requests)
    again = client.get("/api/workflows/library")
    assert again.status_code == 200 and len(real_suite.convert.requests) == tried == 1
    assert again.json()[0]["missing"] == first["missing"]


async def test_missing_explains_each_kind_of_problem(real_suite: Suite) -> None:
    clear_manifest_cache()
    registry = await registry_of(
        real_suite, convert_base_url=None, projets_base_url=None, tab_exports_dir=None
    )
    planning = missing_for(BY_SLUG["tab-planning-vers-projets"], registry)
    assert "tool:tab_check_table : boîte « Atelier Tab » non configurée" in planning
    assert (
        "node:projets/work_items.list : Atelier Projets non configuré (PROJETS_BASE_URL)"
        in planning
    )
    first = missing_for(BY_SLUG["convert-derniere-conversion-tab-viz"], registry)
    assert first[0] == (
        "node:convert/conversions.list : Atelier Convert non configuré (CONVERT_BASE_URL)"
    )
    # Une version de Viz sans l'action utilisée : dite telle quelle
    clear_manifest_cache()
    real_suite.viz.manifest = {
        **REAL_MANIFESTS["viz"],
        "actions": [a for a in REAL_MANIFESTS["viz"]["actions"] if a["id"] != "datasets.get"],
    }
    registry = await registry_of(real_suite)
    assert missing_for(BY_SLUG["viz-alerte-tache-projets"], registry) == [
        "node:viz/datasets.get : action absente du manifeste d'Atelier Viz 0.1.0"
    ]
    # Tab sans dossier ni serveur MCP ; Convert d'avant le contrat (route du manifeste absente)
    clear_manifest_cache()
    real_suite.mcp = False
    real_suite.convert.mode = "no_contract"
    registry = await registry_of(real_suite, tab_exports_dir=None)
    budget = missing_for(BY_SLUG["convert-releve-budget-tab-viz"], registry)
    assert budget[:2] == [
        "node:convert/conversions.table : Atelier Convert sans manifeste atelier-node/1 "
        "(version antérieure au contrat)",
        "node:tab/rows.add : Atelier Tab non configuré (TAB_EXPORTS_DIR ou TAB_MCP_COMMAND)",
    ]


def test_unexpected_manifest_never_breaks_the_gallery(
    client: TestClient, real_suite: Suite, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Schéma d'entrée avec un `$ref` introuvable : l'étape est dite telle quelle, route en 200
    actions = [dict(a) for a in REAL_MANIFESTS["viz"]["actions"]]
    get = next(a for a in actions if a["id"] == "datasets.get")
    get["input_schema"] = {
        "type": "object",
        "properties": {"dataset_id": {"$ref": "#/$defs/Absent"}},
        "required": ["dataset_id"],
    }
    real_suite.viz.manifest = {**REAL_MANIFESTS["viz"], "actions": actions}
    response = client.get("/api/workflows/library")
    assert response.status_code == 200
    alert = next(t for t in response.json() if t["slug"] == "viz-alerte-tache-projets")
    assert alert["available"] is False
    assert alert["missing"] == [
        "Étape « jeu_info » : schéma d'entrée de datasets.get illisible (référence $ref "
        "introuvable)"
    ]
    # Toute autre erreur inattendue : ce modèle seul est dit invérifiable, les autres restent
    real = library_module.missing_for

    def flaky(template: Any, registry: StepRegistry) -> list[str]:
        if template.slug == "projets-temps-hebdo-viz":
            raise RuntimeError("inattendu")
        return real(template, registry)

    monkeypatch.setattr(library_module, "missing_for", flaky)
    listed = {t["slug"]: t for t in client.get("/api/workflows/library").json()}
    assert listed["projets-temps-hebdo-viz"]["missing"] == [library_module.UNCHECKED]
    assert listed["projets-temps-hebdo-viz"]["available"] is False
    assert listed["tab-planning-vers-projets"]["available"] is True


def test_identifiers_are_asked_before_anything_runs(client: TestClient, real_suite: Suite) -> None:
    """Défauts sûrs : un identifiant sans défaut est demandé au lancement et rien n'est envoyé
    aux applications ; un modèle dont tous les paramètres ont un défaut s'arrête sur sa
    première étape, à valider (every_step)."""
    for t in TEMPLATES:
        created = client.post("/api/workflows", json=as_fields(t).model_dump(mode="json"))
        wf = created.json()["id"]
        answer = client.post(f"/api/workflows/{wf}/run", json={"params": {}})
        empty = [p for p in t.params if not p.default]
        if empty:
            assert answer.status_code == 422, t.slug
            assert answer.json()["detail"] == f"Renseignez « {empty[0].label} ».", t.slug
        else:
            assert answer.status_code == 200, t.slug
            run = answer.json()
            assert run["status"] == "awaiting_approval", t.slug
            assert [p["step_id"] for p in run["pending"]] == [t.steps[0].id]
    contract = ("/atelier/manifest", "/atelier/events")
    for node in (real_suite.viz, real_suite.projets, real_suite.convert):
        assert all(r.url.path.endswith(contract) for r in node.requests)
    assert real_suite.mcp_calls() == []


# ─── Un modèle lancé de bout en bout (étapes Convert) ─────────────


def test_first_template_resolves_real_convert_outputs(
    client: TestClient, real_suite: Suite
) -> None:
    template = BY_SLUG["convert-derniere-conversion-tab-viz"]
    created = client.post("/api/workflows", json=as_fields(template).model_dump(mode="json"))
    assert created.status_code == 201, created.text
    wf = created.json()["id"]
    run = client.post(f"/api/workflows/{wf}/run", json={"params": {"projet_tab": "proj_budget"}})
    run = run.json()

    def allow(current: dict[str, Any]) -> dict[str, Any]:
        token = current["pending"][0]["token"]
        answer: dict[str, Any] = client.post(
            f"/api/workflow-runs/{current['id']}/resume", json={"approvals": {token: True}}
        ).json()
        return answer

    assert run["pending"][0]["step_id"] == "historique"  # every_step : même la lecture attend
    run = allow(run)
    assert run["pending"][0]["step_id"] == "vers_tab"
    assert run["pending"][0]["input"] == {
        "conversion_id": RELEVE_ID, "project_id": "proj_budget", "table_name": "Relevé octobre",
    }  # fmt: skip
    run = allow(run)
    assert real_suite.convert.sent[0]["table_id"] == "tbl_001"
    run = allow(run)  # lignes
    pending = run["pending"][0]
    assert pending["step_id"] == "vers_viz" and pending["kind"] == "write"
    assert pending["input"]["key"] == f"convert:{RELEVE_ID}"
    assert pending["input"]["name"] == "Relevé octobre"
    assert pending["input"]["table"]["rows"] == FakeConvertNode.ROWS
    stopped = client.post(
        f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {pending["token"]: False}}
    ).json()
    assert stopped["status"] == "stopped"
    assert [s["status"] for s in stopped["steps"]] == ["ok", "ok", "ok", "refused", "skipped"]


def test_every_node_has_a_recorded_manifest() -> None:
    """Un nœud ajouté à NODE_APPS doit venir avec son manifeste réel enregistré : les modèles
    sont validés contre lui, jamais contre des noms d'actions supposés."""
    fixtures = Path(__file__).parent / "fixtures"
    assert all((fixtures / app / "manifest.json").is_file() for app in NODE_APPS)
