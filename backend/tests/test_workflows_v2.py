"""Workflows v2 (docs/workflows-v2-api.md) : gabarits, graphe, validation, exécution persistée
multi-applications, validations humaines, conversion v1 → v2, catalogue, carte de la suite.

Viz, Projets et Convert : httpx.MockTransport ; Tab : dossier `_atelier/` et faux serveur MCP.
Aucun appel réseau ni modèle.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.db.workflows import WorkflowRepository
from app.schemas.workflows import WorkflowCreate, WorkflowStep
from app.schemas.workflows_v2 import WorkflowStepV2
from app.suite.nodes import clear_manifest_cache
from app.tools.tab_mcp import tab_write_tools
from app.tools.toolsets import build_tools
from app.workflows_v2.engine import approval_token, bound_data
from app.workflows_v2.graph import ancestors, topo_order
from app.workflows_v2.templates import (
    RefNotFoundError,
    Scope,
    StepOutcome,
    coerce_params,
    evaluate,
    parse_ref,
    resolve,
)
from tests.fake_data_via import DATASET_ID
from tests.fake_suite import RELEVE_ID, FakeConvertNode
from tests.test_suite_nodes import Suite

BACKEND = Path(__file__).resolve().parents[1]


# ─── Gabarits ─────────────────────────────────────────────────────


def scope(**outcomes: StepOutcome) -> Scope:
    return Scope({"jeu": "007", "n": "20"}, outcomes, "run-1", set(outcomes))


TABLE = {
    "format": "atelier-table/1",
    "columns": [{"key": "titre", "label": "Titre", "type": "string"}],
    "rows": [{"titre": "Écrire", "heures": 4}, {"titre": "Relire", "heures": 2}],
    "total": 2,
    "truncated": False,
}


def test_exact_templates_keep_their_type_and_inline_ones_become_text() -> None:
    sc = scope(lire=StepOutcome("ok", "2 lignes", TABLE))
    assert resolve("{{steps.lire.data.total}}", sc) == 2
    assert resolve(" {{ steps.lire.data.rows[1].heures }} ", sc) == 2
    assert resolve("{{steps.lire.data.rows}}", sc) == TABLE["rows"]
    assert resolve("{{steps.lire.data}}", sc) is TABLE
    assert resolve("{{params.jeu}}", sc) == "007" and resolve("{{jeu}}", sc) == "007"
    assert resolve("Total : {{steps.lire.data.total}} ({{run.id}})", sc) == "Total : 2 (run-1)"
    assert resolve("x {{steps.lire.data.rows[0]}}", sc) == 'x {"titre":"Écrire","heures":4}'
    assert resolve({"a": ["{{steps.lire.content}}", 3]}, sc) == {"a": ["2 lignes", 3]}
    assert resolve("{{steps.lire.status}}", sc) == "ok"


def test_missing_paths_and_non_ancestors_are_ref_not_found() -> None:
    sc = scope(lire=StepOutcome("ok", "", TABLE), ko=StepOutcome("error", "boom", None))
    for template in (
        "{{steps.lire.data.rows[5].titre}}",
        "{{steps.lire.data.absent}}",
        "{{steps.ko.data}}",
        "{{steps.autre.data}}",
        "{{params.inconnu}}",
    ):
        with pytest.raises(RefNotFoundError):
            resolve(template, sc)
    assert resolve("{{steps.ko.status}}", sc) == "error"  # statut d'une étape en erreur : lisible
    restricted = Scope({}, {"lire": StepOutcome("ok", "", TABLE)}, "r", set())
    with pytest.raises(RefNotFoundError, match="amont"):
        resolve("{{steps.lire.data}}", restricted)
    assert parse_ref("steps.a.content.x").kind == "invalid"
    assert parse_ref("steps.a.data.rows[0].x").path == ("rows", 0, "x")


def test_conditions_and_param_coercion() -> None:
    assert evaluate("gt", "20", 3) and evaluate("lte", 2, 2) and not evaluate("lt", "b", "a")
    assert evaluate("eq", 2, "2") and evaluate("ne", "a", "b")
    assert evaluate("contains", ["a", "b"], "b") and evaluate("contains", "abc", "b")
    assert evaluate("empty", []) and evaluate("not_empty", [1]) and evaluate("empty", None)
    schema = {
        "properties": {"n": {"type": "integer"}, "x": {"type": "number"}, "ok": {"type": "boolean"}}
    }
    raw = {"n": "{{params.n}}", "x": "{{x}}", "ok": "{{params.b}}", "s": "{{params.n}}"}
    out = coerce_params({"n": "20", "x": "1.5", "ok": "oui", "s": "20"}, raw, schema)
    assert out == {"n": 20, "x": 1.5, "ok": True, "s": "20"}


# ─── Graphe ───────────────────────────────────────────────────────


def step(step_id: str, needs: list[str] | None = None, **extra: Any) -> WorkflowStepV2:
    return WorkflowStepV2(
        id=step_id, uses=extra.pop("uses", "tool:tab_list_tables"), needs=needs or [], **extra
    )


def test_topological_order_cycles_and_ancestors() -> None:
    steps = [step("d", ["b", "c"]), step("b", ["a"]), step("c", ["a"]), step("a")]
    order, cyclic = topo_order(steps)
    assert order == ["a", "b", "c", "d"] and not cyclic
    assert ancestors(steps, "d") == {"a", "b", "c"} and ancestors(steps, "a") == set()
    loop = [step("a", ["c"]), step("b", ["a"]), step("c", ["b"]), step("e")]
    order, cyclic = topo_order(loop)
    assert order == ["e"] and cyclic == {"a", "b", "c"}
    assert topo_order([step("a", ["a"])])[1] == {"a"}


def test_bounded_data_and_token() -> None:
    big = {**TABLE, "rows": [{"i": i} for i in range(1500)], "total": None}
    bounded = bound_data(big)
    assert len(bounded["rows"]) == 1000 and bounded["truncated"] and bounded["total"] == 1500
    token = approval_token("r", "s", "node:a/b.c", {"x": 1})
    assert len(token) == 32 and token != approval_token("r", "s", "node:a/b.c", {"x": 2})
    assert token != approval_token("r2", "s", "node:a/b.c", {"x": 1})


# ─── API ──────────────────────────────────────────────────────────


def body(steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "version": 2,
        "agent": None,
        "title": "Tab → Projets → Viz",
        "description": "",
        "params": [{"name": "table", "label": "Table", "default": "tbl_planning_lots"}],
        "steps": steps,
        **extra,
    }


def s(step_id: str, uses: str, input: dict[str, Any], needs: list[str] | None = None, **extra: Any) -> dict[str, Any]:  # fmt: skip
    return {"id": step_id, "label": "", "uses": uses, "input": input, "needs": needs or [],
            "on_error": "stop", **extra}  # fmt: skip


MULTI = [
    s("lire", "node:tab/tables.query", {"table_id": "{{params.table}}"}),
    s(
        "creer",
        "node:projets/work_items.create",
        {
            "story_id": 2,
            "type": "TASK",
            "title": "{{steps.lire.data.rows[0].task_name}}",
            "estimated_hours": "{{steps.lire.data.total}}",
        },
        ["lire"],
    ),
    s(
        "publier",
        "node:viz/datasets.upsert_rows",
        {"name": "lots", "table": "{{steps.lire.data}}", "note": "élément {{steps.creer.data.id}}"},
        ["creer"],
    ),
]


def create(client: TestClient, steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    response = client.post("/api/workflows", json=body(steps, **extra))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def decide(client: TestClient, run: dict[str, Any], allow: bool = True) -> dict[str, Any]:
    """Décision sur l'UNIQUE étape en attente (une à la fois, jeton de l'action montrée)."""
    (pending,) = run["pending"]
    response = client.post(
        f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {pending["token"]: allow}}
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_multi_app_run_stops_on_each_write_with_the_resolved_input(
    client: TestClient, suite: Suite
) -> None:
    wf = create(client, MULTI)
    assert wf["version"] == 2 and wf["agent"] is None
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {}}).json()
    # APPROVAL_MODE=every_step (défaut) : la lecture de Tab attend elle aussi
    assert run["status"] == "awaiting_approval" and run["trigger"] == "manual"
    assert run["pending"][0]["step_id"] == "lire" and run["pending"][0]["kind"] == "read"
    assert run["pending"][0]["input"] == {"table_id": "tbl_planning_lots"}
    assert not suite.mcp_calls()  # rien lu avant validation
    run = decide(client, run)
    assert run["status"] == "awaiting_approval"
    assert [(x["id"], x["status"]) for x in run["steps"]] == [
        ("lire", "ok"),
        ("creer", "awaiting_approval"),
        ("publier", "pending"),
    ]
    assert run["steps"][0]["data"]["rows"][0]["task_name"] == "Gros œuvre"
    pending = run["pending"][0]
    # Entrée résolue avec les valeurs réelles de l'étape précédente (types conservés)
    assert pending["input"] == {
        "story_id": 2,
        "type": "TASK",
        "title": "Gros œuvre",
        "estimated_hours": 2,
    }
    assert pending["kind"] == "write" and "Créer un élément" in pending["summary"]
    assert pending["token"] == approval_token(
        run["id"], "creer", "node:projets/work_items.create", pending["input"]
    )
    assert not suite.projets.created  # rien d'écrit avant validation

    # Jeton périmé : rien ne bouge
    stale = client.post(f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {"x": True}})
    assert stale.json()["status"] == "awaiting_approval" and not suite.projets.created

    run = client.post(
        f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {pending["token"]: True}}
    ).json()
    assert run["status"] == "awaiting_approval" and run["pending"][0]["step_id"] == "publier"
    assert run["pending"][0]["input"]["note"] == "élément 30000"
    assert run["pending"][0]["input"]["table"]["format"] == "atelier-table/1"
    assert "table « Planning & Lots » (2 ligne(s))" in run["pending"][0]["summary"]

    run = client.post(
        f"/api/workflow-runs/{run['id']}/resume",
        json={"approvals": {run["pending"][0]["token"]: True}},
    ).json()
    assert run["status"] == "completed", run["message"]
    assert [x["status"] for x in run["steps"]] == ["ok", "ok", "ok"]
    assert run["steps"][1]["data"]["id"] == 30000 and run["steps"][2]["data"]["id"] == "ds_lots"
    assert all(x["started_at"] and x["ended_at"] for x in run["steps"])
    assert [a["kind"] for a in run["artifacts"]] == ["data_preview"]  # la table lue
    assert suite.projets.created[0]["title"] == "Gros œuvre"
    assert suite.viz.published[0]["table"]["rows"][1]["task_name"] == "Charpente bois"

    # Idempotence transmise : nexus:<run>:<step>
    posts = [r for r in suite.projets.requests + suite.viz.requests if r.method == "POST"]
    assert [r.headers["idempotency-key"] for r in posts] == [
        f"nexus:{run['id']}:creer",
        f"nexus:{run['id']}:publier",
    ]
    # Une exécution terminée ne se reprend plus
    again = client.post(f"/api/workflow-runs/{run['id']}/resume", json={"approvals": {}})
    assert again.status_code == 409

    # Persistance : relue, listée, compteur du workflow
    assert client.get(f"/api/workflow-runs/{run['id']}").json() == run
    listed = client.get("/api/workflow-runs", params={"workflow_id": wf["id"]}).json()
    assert [r["id"] for r in listed] == [run["id"]]
    saved = client.get(f"/api/workflows/{wf['id']}").json()
    assert saved["run_count"] == 1 and saved["last_status"] == "completed"
    assert client.get("/api/workflow-runs/inconnue").status_code == 404


def test_refusal_stops_and_skips_the_rest(client: TestClient, suite: Suite) -> None:
    wf = create(client, MULTI)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {}}).json()
    run = decide(client, run)  # lecture autorisée
    run = decide(client, run, allow=False)  # création refusée
    assert run["status"] == "stopped" and "refusée" in run["message"]
    assert [x["status"] for x in run["steps"]] == ["ok", "refused", "skipped"]
    assert not suite.projets.created and not suite.viz.published


def test_mcp_write_gets_the_idempotency_field(client: TestClient, suite: Suite) -> None:
    wf = create(
        client,
        [s("ajout", "node:tab/rows.add", {"table": "{{params.table}}", "rows": [{"A": "x"}]})],
    )
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["pending"][0]["input"] == {"table": "tbl_planning_lots", "rows": [{"A": "x"}]}
    run = client.post(
        f"/api/workflow-runs/{run['id']}/resume",
        json={"approvals": {run["pending"][0]["token"]: True}},
    ).json()
    assert run["status"] == "completed"
    call = next(c for c in suite.mcp_calls() if c["name"] == "add_rows")
    assert call["arguments"]["idempotency_key"] == f"nexus:{run['id']}:ajout"


def test_destructive_node_action_waits_and_is_flagged(client: TestClient, suite: Suite) -> None:
    wf = create(client, [s("suppr", "node:projets/work_items.delete", {"work_item_id": 9})])
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "awaiting_approval" and run["pending"][0]["kind"] == "destructive"
    assert not [r for r in suite.projets.requests if r.method == "DELETE"]


def test_on_error_stop_and_continue(client: TestClient, suite: Suite) -> None:
    suite.approval_mode = "writes_only"  # sujet : le moteur ; every_step : test_approval_mode.py
    failing = s("q", "node:viz/datasets.query", {"dataset_id": "inconnu"})
    reader = s(
        "lit", "node:viz/datasets.query", {"dataset_id": "{{steps.q.data.rows[0].region}}"}, ["q"]
    )
    status_only = s(
        "suite", "tool:tab_list_tables", {}, ["q"], when={"left": "{{steps.q.status}}", "op": "eq", "right": "error"}
    )  # fmt: skip
    wf = create(client, [failing, reader, status_only])
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "failed" and "Jeu introuvable" in run["message"]
    assert [(x["status"], x["error_code"]) for x in run["steps"]] == [
        ("error", "NOT_FOUND"),
        ("skipped", None),
        ("skipped", None),
    ]

    # L'étape qui lit la sortie manquante échoue (REF_NOT_FOUND) ; elle aussi poursuit
    cont = create(
        client,
        [{**failing, "on_error": "continue"}, {**reader, "on_error": "continue"}, status_only],
    )
    run = client.post(f"/api/workflows/{cont['id']}/run", json={}).json()
    assert run["status"] == "completed" and "en erreur" in run["message"]
    assert [(x["id"], x["status"], x["error_code"]) for x in run["steps"]] == [
        ("q", "error", "NOT_FOUND"),
        ("lit", "error", "REF_NOT_FOUND"),
        ("suite", "ok", None),
    ]


def test_when_skips_the_step_and_its_dependents(client: TestClient, suite: Suite) -> None:
    suite.approval_mode = "writes_only"  # sujet : le moteur ; every_step : test_approval_mode.py
    lire = s("lire", "node:tab/tables.query", {"table_id": "{{params.table}}"})
    gros = s(
        "gros",
        "node:viz/datasets.query",
        {"dataset_id": "ds_ventes"},
        ["lire"],
        when={"left": "{{steps.lire.data.total}}", "op": "gt", "right": 10},
    )
    apres = s("apres", "tool:tab_list_tables", {}, ["gros"])
    autre = s("autre", "tool:tab_list_tables", {}, ["lire"])
    wf = create(client, [lire, gros, apres, autre])
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "completed"
    assert {x["id"]: x["status"] for x in run["steps"]} == {
        "lire": "ok",
        "gros": "skipped",
        "apres": "skipped",
        "autre": "ok",
    }
    assert not [r for r in suite.viz.requests if r.url.path == "/api/atelier/query"]


def test_tool_steps_share_context_and_bound_data(client: TestClient, suite: Suite) -> None:
    suite.approval_mode = "writes_only"  # sujet : le moteur ; every_step : test_approval_mode.py
    steps = [
        s("schema", "tool:data_via_describe_dataset", {"dataset_id": DATASET_ID}),
        s(
            "requete",
            "tool:data_via_query",
            {
                "dataset_id": "{{steps.schema.data.id}}",
                "dimensions": [{"field": "region"}],
                "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
            },
            ["schema"],
        ),
        s("gros", "node:viz/datasets.query", {"dataset_id": "ds_ventes"}),
    ]
    wf = create(client, steps)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "completed", run["message"]
    assert run["steps"][1]["data"]["rows"][0] == {
        "region": "Région 0",
        "sum_chiffre_affaires": 1000.0,
    }
    big = next(x for x in run["steps"] if x["id"] == "gros")["data"]
    assert len(big["rows"]) == 1000 and big["truncated"] and big["total"] == 1500
    assert len(run["artifacts"]) == 3  # schéma, requête (outils) + table du nœud


def test_resume_after_a_write_keeps_the_tool_context(client: TestClient, suite: Suite) -> None:
    """L'exploration préalable de Data Via faite avant une validation reste valable après."""
    suite.approval_mode = "writes_only"  # une seule validation : l'écriture
    steps = [
        s("schema", "tool:data_via_describe_dataset", {"dataset_id": DATASET_ID}),
        s("creer", "node:projets/work_items.create", {"story_id": 2, "type": "TASK", "title": "x"}, ["schema"]),
        s("requete", "tool:data_via_query",
          {"dataset_id": DATASET_ID, "measures": [{"agg": "count"}]}, ["creer"]),
    ]  # fmt: skip
    wf = create(client, steps)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    run = client.post(
        f"/api/workflow-runs/{run['id']}/resume",
        json={"approvals": {run["pending"][0]["token"]: True}},
    ).json()
    assert run["status"] == "completed", run["message"]


def test_gate_runs_nothing_when_a_param_breaks_an_input(client: TestClient, suite: Suite) -> None:
    suite.approval_mode = "writes_only"  # sujet : le moteur ; every_step : test_approval_mode.py
    wf = create(
        client,
        [
            s("lire", "node:tab/tables.query", {"table_id": "{{params.table}}"}),
            s("q", "node:viz/datasets.query", {"dataset_id": "x", "limit": "{{params.n}}"}),
        ],
        params=[
            {"name": "table", "label": "", "default": "tbl_planning_lots"},
            {"name": "n", "label": "Limite", "default": "beaucoup"},
        ],
    )
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["status"] == "failed" and run["message"].startswith("Rien n'a été exécuté")
    assert all(x["status"] == "skipped" for x in run["steps"])
    assert not suite.mcp_calls() and not [r for r in suite.viz.requests if r.method == "POST"]
    ok = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {"n": "20"}}).json()
    assert ok["steps"][1]["input"]["limit"] == 20  # paramètre texte converti pour le schéma
    missing = client.post(
        f"/api/workflows/{wf['id']}/run", json={"params": {"table": " ", "n": ""}}
    ).json()
    assert missing["status"] in ("completed", "failed")
    unknown = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {"pirate": "1"}})
    assert unknown.status_code == 422


# ─── Validation ───────────────────────────────────────────────────


def codes(client: TestClient, steps: list[dict[str, Any]], **extra: Any) -> set[tuple[str | None, str | None, str]]:  # fmt: skip
    result = client.post("/api/workflows/validate", json=body(steps, **extra)).json()
    assert result["ok"] is not bool(result["errors"]) or not result["errors"]
    return {(e["step_id"], e["field"], e["code"]) for e in result["errors"]}


def test_validation_codes(client: TestClient, suite: Suite) -> None:
    ok = client.post("/api/workflows/validate", json=body(MULTI)).json()
    assert ok == {"ok": True, "errors": [], "order": ["lire", "creer", "publier"]}
    lst = "tool:tab_list_tables"
    assert codes(client, [s("a", lst, {}), s("a", lst, {})]) == {("a", "id", "DUPLICATE_ID")}
    assert codes(client, [s("Mauvais", lst, {})]) == {("Mauvais", "id", "BAD_ID")}
    assert codes(client, [s("a", "tool:inexistant", {})]) == {("a", None, "UNKNOWN_USES")}
    assert codes(client, [s("a", "node:viz/rien.du_tout", {})]) == {("a", None, "UNKNOWN_USES")}
    assert codes(client, [s("a", "bizarre", {})]) == {("a", None, "UNKNOWN_USES")}
    assert codes(client, [s("a", "tool:tresorerie_dashboard", {})]) == {("a", None, "UNAVAILABLE")}
    assert codes(client, [s("a", lst, {}, ["b"]), s("b", lst, {}, ["a"])]) == {
        ("a", "needs", "CYCLE"),
        ("b", "needs", "CYCLE"),
    }
    assert codes(client, [s("a", lst, {}, ["zz"])]) == {("a", "needs", "UNKNOWN_NEED")}
    refs = [
        s("a", "node:tab/tables.query", {"table_id": "{{steps.b.content}}"}),
        s("b", "node:tab/tables.query", {"table_id": "{{steps.b.data.x}}"}),
    ]
    assert codes(client, refs) == {
        ("a", "table_id", "REF_NOT_ANCESTOR"),
        ("b", "table_id", "REF_NOT_ANCESTOR"),
    }
    assert codes(client, [s("a", "node:tab/tables.query", {"table_id": "{{params.x}}"})]) == {
        ("a", "table_id", "UNDECLARED_PARAM")
    }
    assert codes(client, [s("a", "node:projets/work_items.create", {"story_id": "deux"})]) == {
        ("a", "story_id", "INPUT_INVALID"),
        ("a", "type", "INPUT_INVALID"),  # champs requis manquants
        ("a", "title", "INPUT_INVALID"),
    }
    # Un champ qui contient un gabarit n'est vérifié qu'à l'exécution
    assert not codes(
        client,
        [
            s("a", lst, {}),
            s("b", "node:projets/work_items.create",
              {"story_id": "{{steps.a.data.total}}", "type": "TASK", "title": "t"}, ["a"]),
        ],
    )  # fmt: skip
    assert codes(client, [s("a", "tool:tab_read_table", {"table_id": "x", "limit": 0})]) == {
        ("a", "limit", "INPUT_INVALID")
    }
    many = [s(f"s{i}", lst, {}) for i in range(31)]
    assert (None, None, "TOO_MANY_STEPS") in codes(client, many)
    assert codes(client, [s("a", "tool:current_datetime", {})]) == {("a", None, "NOT_REPLAYABLE")}
    assert codes(client, [s("a", "tool:delegate_to_agent", {})]) == {("a", None, "NOT_REPLAYABLE")}
    assert codes(client, [s("a", lst, {}, when={"left": "", "op": "eq"})]) == {
        ("a", "when", "BAD_CONDITION")
    }
    assert codes(client, [s("a", lst, {}, when={"left": "{{steps.a.status}}", "op": "empty"})]) == {
        ("a", "when", "REF_NOT_ANCESTOR")
    }


def test_saving_refuses_a_broken_graph_but_accepts_a_draft(
    client: TestClient, suite: Suite
) -> None:
    cycle = body([s("a", "tool:tab_list_tables", {}, ["a"])])
    response = client.post("/api/workflows", json=cycle)
    assert response.status_code == 422 and "Boucle" in response.json()["detail"]
    draft = body([s("a", "node:projets/work_items.create", {"type": "TASK"})])
    assert client.post("/api/workflows", json=draft).status_code == 201
    suite.viz.mode = "down"
    later = body([s("a", "node:viz/datasets.query", {"dataset_id": "x"})])
    assert client.post("/api/workflows", json=later).status_code == 201


def test_agent_workflow_uses_only_the_agent_tools(client: TestClient, suite: Suite) -> None:
    scoped = body([s("a", "tool:projets_list_projects", {})], agent="data_analyst")
    result = client.post("/api/workflows/validate", json=scoped).json()
    assert result["errors"][0]["code"] == "UNKNOWN_USES"
    allowed = body([s("a", "tool:data_via_list_datasets", {})], agent="data_analyst")
    assert client.post("/api/workflows/validate", json=allowed).json()["ok"]
    assert client.post("/api/workflows", json=body([], agent="inconnu")).status_code == 404


def test_update_v2_and_crud(client: TestClient) -> None:
    wf = create(client, MULTI)
    changed = client.put(
        f"/api/workflows/{wf['id']}", json=body(MULTI[:1], title="Lecture seule")
    ).json()
    assert changed["title"] == "Lecture seule" and len(changed["steps"]) == 1
    assert changed["updated_at"] >= wf["updated_at"]
    v1_body = {"title": "x", "steps": [{"tool": "tab_list_tables", "input": {}}]}
    assert client.put(f"/api/workflows/{wf['id']}", json=v1_body).status_code == 422
    assert client.delete(f"/api/workflows/{wf['id']}").status_code == 204
    assert client.get(f"/api/workflows/{wf['id']}").status_code == 404


# ─── v1 : inchangé, conversion ────────────────────────────────────


async def test_v1_still_works_and_converts_to_v2(
    client: TestClient, repo: WorkflowRepository
) -> None:
    v1 = await repo.create(
        WorkflowCreate(
            agent="data_analyst",
            title="CA",
            steps=[
                WorkflowStep(tool="data_via_describe_dataset", input={"dataset_id": "{{jeu}}"}),
                WorkflowStep(
                    tool="data_via_query",
                    input={"dataset_id": "Jeu {{ jeu }}", "measures": [{"agg": "count"}]},
                ),
            ],  # fmt: skip
            params=[{"name": "jeu", "label": "Jeu", "default": DATASET_ID}],  # type: ignore[list-item]
        )
    )
    listed = client.get("/api/workflows").json()
    assert listed[0]["version"] == 1
    v1_run = client.post(f"/api/workflows/{v1.id}/run", json={}).json()
    # Réponse v1 (WorkflowRunResult) ; APPROVAL_MODE=every_step : les deux lectures attendent
    assert v1_run["status"] == "awaiting_approval" and "index" in v1_run["pending"][0]
    assert [p["kind"] for p in v1_run["pending"]] == ["read", "read"]
    approvals = {p["token"]: True for p in v1_run["pending"]}  # une décision par étape
    v1_run = client.post(f"/api/workflows/{v1.id}/run", json={"approvals": approvals}).json()
    assert "index" in v1_run["steps"][0] and v1_run["steps"][0]["status"] == "ok"

    converted = client.post(f"/api/workflows/{v1.id}/convert").json()
    assert converted["version"] == 2 and converted["id"] == v1.id
    assert [(x["id"], x["uses"], x["needs"]) for x in converted["steps"]] == [
        ("s1", "tool:data_via_describe_dataset", []),
        ("s2", "tool:data_via_query", ["s1"]),
    ]
    assert converted["steps"][0]["input"] == {"dataset_id": "{{params.jeu}}"}
    assert converted["steps"][1]["input"]["dataset_id"] == "Jeu {{params.jeu}}"
    assert converted["run_count"] == 1 and converted["agent"] == "data_analyst"
    run = client.post(f"/api/workflows/{v1.id}/run", json={}).json()
    assert "workflow_id" in run and run["pending"][0]["step_id"] == "s1"
    assert decide(client, run)["steps"][0]["status"] == "ok"
    # Déjà en v2 : renvoyé tel quel
    assert client.post(f"/api/workflows/{v1.id}/convert").json()["steps"] == converted["steps"]


# ─── Catalogue ────────────────────────────────────────────────────


def test_catalog_of_the_suite_and_of_an_agent(client: TestClient, suite: Suite) -> None:
    suite.projets.mode = "no_contract"
    suite.viz.mode = "down"
    catalog = client.get("/api/workflows/catalog").json()
    apps = {a["app"]: a for a in catalog["apps"]}
    assert apps["viz"]["status"] == "unreachable" and apps["viz"]["color"] == "#F2C811"
    assert apps["projets"]["status"] == "no_contract" and apps["tab"]["status"] == "ok"
    assert apps["tresorerie"]["status"] == "not_configured"
    entries = {e["uses"]: e for e in catalog["entries"]}
    assert "node:tab/rows.add" in entries and not any(u.startswith("node:viz") for u in entries)
    assert "tool:current_datetime" not in entries and "tool:delegate_to_agent" not in entries
    query = entries["tool:data_via_query"]
    assert query["app"] == "viz" and query["output_format"] == "atelier-table/1"
    assert query["kind"] == "read" and query["input_schema"]["required"] == ["dataset_id"]
    assert entries["tool:tab_delete_rows"]["kind"] == "write"
    assert entries["tool:tresorerie_dashboard"]["available"] is False
    assert entries["tool:projets_list_work_items"]["output_hint"]["columns"][0]["key"] == "id"
    assert entries["node:tab/rows.delete"]["kind"] == "destructive"

    agent = client.get("/api/workflows/catalog", params={"agent": "tableur"}).json()
    tools = {e["uses"] for e in agent["entries"] if e["source"] == "tool"}
    assert "tool:tab_add_rows" in tools and "tool:data_via_query" not in tools


def test_catalog_lists_the_convert_node(client: TestClient, suite: Suite) -> None:
    catalog = client.get("/api/workflows/catalog").json()
    apps = {a["app"]: a for a in catalog["apps"]}
    assert apps["convert"] == {"app": "convert", "name": "Atelier Convert", "status": "ok",
                               "color": "#C9951D"}  # fmt: skip
    entries = {e["uses"]: e for e in catalog["entries"]}
    table = entries["node:convert/conversions.table"]
    assert table["output_format"] == "atelier-table/1" and table["available"] is True
    assert table["input_schema"]["required"] == ["conversion_id"] and table["app"] == "convert"
    assert entries["node:convert/conversions.delete"]["kind"] == "destructive"
    assert entries["node:convert/conversions.send_to_tab"]["kind"] == "write"

    suite.convert.mode = "down"
    clear_manifest_cache()  # sinon le manifeste lu plus haut resterait 60 s en cache
    catalog = client.get("/api/workflows/catalog").json()
    apps = {a["app"]: a for a in catalog["apps"]}
    assert apps["convert"]["status"] == "unreachable"
    assert not any(e["uses"].startswith("node:convert/") for e in catalog["entries"])


def test_convert_to_tab_run_waits_at_each_step(
    client: TestClient, suite: Suite, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    steps = [
        s("lire", "node:convert/conversions.table",
          {"conversion_id": "{{params.conversion}}", "limit": 100}),
        s("ajouter", "node:tab/rows.add",
          {"table": "{{params.table}}", "rows": "{{steps.lire.data.rows}}"}, ["lire"]),
    ]  # fmt: skip
    wf = create(
        client,
        steps,
        params=[
            {"name": "table", "label": "Table", "default": "tbl_planning_lots"},
            {"name": "conversion", "label": "Conversion", "default": RELEVE_ID},
        ],
    )
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"params": {}}).json()
    # every_step : la lecture de Convert attend une validation, rien n'est lu avant
    assert run["status"] == "awaiting_approval" and run["pending"][0]["step_id"] == "lire"
    assert run["pending"][0]["input"] == {"conversion_id": RELEVE_ID, "limit": 100}
    assert "Atelier Convert · Lire la table d'une conversion" in run["pending"][0]["summary"]
    assert not [r for r in suite.convert.requests if r.url.path.endswith("/table")]
    run = decide(client, run)
    assert run["status"] == "awaiting_approval" and run["pending"][0]["step_id"] == "ajouter"
    # Entrée résolue montrée avant d'écrire : les lignes réelles de la conversion
    assert run["pending"][0]["input"] == {
        "table": "tbl_planning_lots",
        "rows": FakeConvertNode.ROWS,
    }
    assert run["pending"][0]["kind"] == "write"
    assert not [c for c in suite.mcp_calls() if c["name"] == "add_rows"]
    run = decide(client, run)
    assert run["status"] == "completed", run["message"]
    call = next(c for c in suite.mcp_calls() if c["name"] == "add_rows")
    assert call["arguments"]["rows"] == FakeConvertNode.ROWS
    assert call["arguments"]["idempotency_key"] == f"nexus:{run['id']}:ajouter"
    # Relevé bancaire : aucune donnée des étapes dans les journaux de Nexus (tous niveaux) ni
    # dans ceux des bibliothèques à partir d'INFO (aiosqlite trace ses requêtes en DEBUG)
    logged = [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith(("app", "main")) or r.levelno >= logging.INFO
    ]
    assert logged and not any("Loyer" in m or "Salaire" in m for m in logged)


def test_convert_send_to_tab_carries_the_idempotency_key(client: TestClient, suite: Suite) -> None:
    steps = [
        s("vers_tab", "node:convert/conversions.send_to_tab",
          {"conversion_id": RELEVE_ID, "project_id": "proj_budget", "table_name": "Octobre"}),
    ]  # fmt: skip
    wf = create(client, steps)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["pending"][0]["kind"] == "write" and not suite.convert.sent
    run = decide(client, run)
    assert run["status"] == "completed" and run["steps"][0]["data"]["table_id"] == "tbl_001"
    post = next(r for r in suite.convert.requests if r.method == "POST")
    assert post.headers["idempotency-key"] == f"nexus:{run['id']}:vers_tab"
    assert post.url.path == f"/api/atelier/conversions/{RELEVE_ID}/send-to-tab"


def test_tab_destructive_tools_require_approval(suite: Suite) -> None:
    """Correction demandée : `tab_delete_rows` (et toutes les écritures Tab) attendent une validation."""
    env = suite.env()
    tools, _ = build_tools(["tab_write"], env)
    assert {t.name: t.requires_approval for t in tools} == {
        "tab_set_cells": True,
        "tab_add_rows": True,
        "tab_delete_rows": True,
        "tab_add_column": True,
        "tab_create_table": True,
    }
    assert all(t.requires_approval for t in tab_write_tools(env.tab_mcp()))


# ─── Migration ────────────────────────────────────────────────────


def test_migration_0006_up_and_down(tmp_path: Path) -> None:
    db = tmp_path / "nexus.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "0005_workflows")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workflows (id, agent, title, description, steps, params, run_count, "
            "created_at, updated_at) VALUES ('w1', 'rh', 't', '', '[]', '[]', 0, '2026-10-21', "
            "'2026-10-21')"
        )
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert list(conn.execute("SELECT id, version FROM workflows")) == [("w1", 1)]
        runs = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
        nullable = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(workflows)")}
        conn.execute(
            "INSERT INTO workflows (id, version, agent, title, description, steps, params, "
            "run_count, created_at, updated_at) VALUES ('w2', 2, NULL, 't', '', '[]', '[]', 0, "
            "'2026-10-21', '2026-10-21')"
        )
    assert {"workflow_id", "status", "steps", "pending", "state", "artifacts"} <= runs
    assert nullable["agent"] == 0  # agent facultatif (workflow de suite)
    command.downgrade(cfg, "0005_workflows")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workflows)")}
        kept = list(conn.execute("SELECT id FROM workflows"))
    assert "workflow_runs" not in tables and "version" not in columns and kept == [("w1",)]
