"""Carte de la suite et événements (docs/workflows-v2-api.md §7) : manifestes des quatre nœuds
(Viz, Tab, Projets, Convert), outils et agents par application, échanges, workflows qui touchent
chaque application."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.tools.toolsets import toolset_ids
from tests.test_suite_nodes import Suite
from tests.test_workflows_v2 import MULTI, create


def test_suite_map(client: TestClient, suite: Suite) -> None:
    suite.projets.mode = "no_contract"  # avant toute lecture : le manifeste est gardé 60 s
    create(client, MULTI)
    data = client.get("/api/suite/map").json()
    apps = {a["app"]: a for a in data["apps"]}
    assert [a["app"] for a in data["apps"]][:4] == ["viz", "tab", "projets", "convert"]
    viz = apps["viz"]
    assert viz["status"] == "ok" and viz["transport"] == "http" and viz["color"] == "#F2C811"
    assert {"id": "datasets.upsert_rows", "label": "Publier une table", "kind": "write",
            "output_format": "json"} in viz["actions"]  # fmt: skip
    assert {"type": "viz.dataset.refreshed", "label": "Jeu actualisé"} in viz["events"]
    assert {"name": "data_via_query", "kind": "read", "toolset": "data_via"} in viz["nexus_tools"]
    analyst = next(a for a in viz["agents"] if a["name"] == "data_analyst")
    assert analyst["toolsets"] == ["data_via"] and analyst["writes"] is False
    chef = next(a for a in apps["projets"]["agents"] if a["name"] == "chef_de_projet")
    assert chef["writes"] is True and "projets_write" in chef["toolsets"]
    assert apps["projets"]["status"] == "no_contract" and apps["projets"]["actions"] == []
    assert apps["tab"]["transport"] == "mcp"
    assert apps["tresorerie"]["status"] == "not_configured"
    convert = apps["convert"]
    assert convert["name"] == "Atelier Convert" and convert["color"] == "#C9951D"
    assert convert["status"] == "ok" and convert["transport"] == "http"
    assert {"id": "conversions.table", "label": "Lire la table d'une conversion",
            "kind": "read", "output_format": "atelier-table/1"} in convert["actions"]  # fmt: skip
    assert {"id": "conversions.delete", "label": "Supprimer une conversion",
            "kind": "destructive", "output_format": "json"} in convert["actions"]  # fmt: skip
    assert {"type": "convert.conversion.created", "label": "Conversion créée"} in convert["events"]
    flows = data["flows"]
    for fixed in (
        {"from": "tab", "to": "projets", "label": "Import DataFlow", "via": "webhook"},
        {"from": "tab", "to": "viz", "label": "Instantanés", "via": "fichiers"},
        {"from": "projets", "to": "viz", "label": "Jeux de données", "via": "HTTP"},
        {"from": "convert", "to": "tab", "label": "Nouvelle table", "via": "fichiers"},
        {"from": "nexus", "to": "projets", "label": "Écritures validées", "via": "HTTP"},
        {"from": "viz", "to": "nexus", "label": "Lecture", "via": "HTTP"},
    ):
        assert fixed in flows
    if "data_via_write" not in toolset_ids():  # Viz : lecture seule (sans extension d'écriture)
        assert not any(f["from"] == "nexus" and f["to"] == "viz" for f in flows)
    assert data["workflows"][0]["apps"] == ["tab", "projets", "viz"]


def test_suite_events(client: TestClient, suite: Suite) -> None:
    suite.projets.mode = "down"
    entries = {e["app"]: e for e in client.get("/api/suite/events").json()}
    assert [e["seq"] for e in entries["viz"]["events"]] == [40, 41, 42]
    assert entries["tab"]["status"] == "ok" and entries["tab"]["next"] == 8
    assert entries["projets"]["status"] == "unreachable" and entries["projets"]["events"] == []
    only = client.get("/api/suite/events", params={"app": "viz", "since": 41}).json()
    assert len(only) == 1 and [e["seq"] for e in only[0]["events"]] == [42]
    gap = client.get("/api/suite/events", params={"app": "viz", "since": 2}).json()[0]
    assert gap["gap"] is True
    assert [e["seq"] for e in entries["convert"]["events"]] == [1, 2, 3]
    assert entries["convert"]["events"][0]["type"] == "convert.conversion.created"
    since = client.get("/api/suite/events", params={"app": "convert", "since": 1}).json()
    assert [e["seq"] for e in since[0]["events"]] == [2, 3] and since[0]["next"] == 3
