"""Doubles des nœuds de la suite (contrat atelier-node/1) pour httpx.MockTransport et MCP.

Noms d'actions supposés (les applications les publient dans leur manifeste) :
- Viz : `datasets.query` (lecture, table), `datasets.list` (GET avec requête),
  `datasets.upsert_rows` (écriture, `Idempotency-Key`), `datasets.delete` (destructive) ;
- Projets : `work_items.list` (lecture, table), `work_items.create` (écriture, `Idempotency-Key`),
  `work_items.delete` (destructive) ;
- Tab (MCP) : `tables.query` (`query_table`), `rows.add` (`add_rows`, champ `idempotency_key`),
  `rows.delete` (`delete_rows`, destructive).
Les routes non « atelier » sont déléguées aux doubles existants (Data Via, Projets).
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

import httpx

from tests.fake_data_via import FakeDataVia
from tests.test_connectors import FakeProjets

FAKE_MCP = str(Path(__file__).parent / "fake_tab_mcp.py")

TABLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"const": "atelier-table/1"},
        "columns": {"type": "array"},
        "rows": {"type": "array"},
    },
    "required": ["format", "columns", "rows"],
}

VIZ_MANIFEST: dict[str, Any] = {
    "contract": "atelier-node/1",
    "app": "viz",
    "name": "Atelier Viz",
    "version": "1.8.0",
    "transport": "http",
    "actions": [
        {
            "id": "datasets.query",
            "label": "Interroger un jeu de données",
            "description": "Agrégation sur un jeu.",
            "kind": "read",
            "http": {"method": "POST", "path": "/api/atelier/query"},
            "mcp_tool": None,
            "input_schema": {
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["dataset_id"],
                "additionalProperties": False,
            },
            "output": {"format": "atelier-table/1", "schema": {}},
            "idempotency": "none",
        },
        {
            "id": "datasets.list",
            "label": "Lister les jeux",
            "kind": "read",
            "http": {"method": "GET", "path": "/api/atelier/datasets"},
            "input_schema": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}, "tags": {"type": "array"}},
            },
            "output": {"format": "json", "schema": {"properties": {"datasets": {}}}},
            "idempotency": "none",
        },
        {
            "id": "datasets.upsert_rows",
            "label": "Publier une table",
            "description": "Crée ou remplace un jeu à partir d'une table atelier-table/1.",
            "kind": "write",
            "http": {"method": "POST", "path": "/api/atelier/datasets/{name}/rows"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "table": TABLE_SCHEMA,
                    "note": {"type": "string"},
                },
                "required": ["name", "table"],
                "additionalProperties": False,
            },
            "output": {"format": "json", "schema": {"properties": {"id": {}, "rows": {}}}},
            "idempotency": "header",
        },
        {
            "id": "datasets.delete",
            "label": "Supprimer un jeu",
            "kind": "destructive",
            "http": {"method": "DELETE", "path": "/api/atelier/datasets/{dataset_id}"},
            "input_schema": {
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
            },
            "output": {"format": "json"},
            "idempotency": "natural",
        },
        # Action mal formée : écartée sans rendre le manifeste inutilisable
        {"id": "Mauvais id", "kind": "read", "http": {"method": "GET", "path": "/api/x"}},
    ],
    "events": [
        {"type": "viz.dataset.refreshed", "label": "Jeu actualisé", "data_schema": {}},
        {"type": "viz.dataset.created", "label": "Jeu créé"},
    ],
}

PROJETS_MANIFEST: dict[str, Any] = {
    "contract": "atelier-node/1",
    "app": "projets",
    "name": "Atelier Projets",
    "version": "2.4.0",
    "transport": "http",
    "actions": [
        {
            "id": "work_items.list",
            "label": "Lister les éléments",
            "kind": "read",
            "http": {"method": "GET", "path": "/api/atelier/projects/{project_id}/work-items"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "status": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["project_id"],
            },
            "output": {
                "format": "atelier-table/1",
                "schema": {
                    "x-columns": [
                        {"key": "id", "label": "Identifiant", "type": "number"},
                        {"key": "titre", "label": "Titre", "type": "string"},
                    ]
                },
            },
            "idempotency": "none",
        },
        {
            "id": "work_items.create",
            "label": "Créer un élément",
            "description": "Crée une TASK, FEATURE ou BUG dans une story.",
            "kind": "write",
            "http": {"method": "POST", "path": "/api/atelier/stories/{story_id}/work-items"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "story_id": {"type": "integer"},
                    "type": {"enum": ["TASK", "FEATURE", "BUG"]},
                    "title": {"type": "string", "minLength": 1},
                    "estimated_hours": {"type": "number"},
                },
                "required": ["story_id", "type", "title"],
                "additionalProperties": False,
            },
            "output": {"format": "json", "schema": {"properties": {"id": {}, "title": {}}}},
            "idempotency": "header",
        },
        {
            "id": "work_items.delete",
            "label": "Supprimer un élément",
            "kind": "destructive",
            "http": {"method": "DELETE", "path": "/api/atelier/work-items/{work_item_id}"},
            "input_schema": {
                "type": "object",
                "properties": {"work_item_id": {"type": "integer"}},
                "required": ["work_item_id"],
            },
            "output": {"format": "json"},
            "idempotency": "natural",
        },
    ],
    "events": [{"type": "projets.work_item.created", "label": "Élément créé"}],
}

TAB_MANIFEST: dict[str, Any] = {
    "contract": "atelier-node/1",
    "app": "tab",
    "name": "Atelier Tab",
    "version": "3.2.0",
    "transport": "mcp",
    "actions": [
        {
            "id": "tables.query",
            "label": "Lire une table",
            "kind": "read",
            "http": None,
            "mcp_tool": "query_table",
            "input_schema": {
                "type": "object",
                "properties": {"table_id": {"type": "string"}},
                "required": ["table_id"],
            },
            "output": {"format": "atelier-table/1"},
            "idempotency": "none",
        },
        {
            "id": "rows.add",
            "label": "Ajouter des lignes",
            "kind": "write",
            "mcp_tool": "add_rows",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "rows": {"type": "array", "items": {"type": "object"}, "minItems": 1},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["table", "rows"],
                "additionalProperties": False,
            },
            "output": {"format": "json"},
            "idempotency": "field",
        },
        {
            "id": "rows.delete",
            "label": "Supprimer des lignes",
            "kind": "destructive",
            "mcp_tool": "delete_rows",
            "input_schema": {
                "type": "object",
                "properties": {"table": {"type": "string"}, "rows": {"type": "array"}},
                "required": ["table", "rows"],
            },
            "output": {"format": "json"},
            "idempotency": "none",
        },
    ],
    "events": [{"type": "tab.table.changed", "label": "Table modifiée"}],
}


def page(events: list[dict[str, Any]], request: httpx.Request) -> dict[str, Any]:
    since = request.url.params.get("since")
    limit = int(request.url.params.get("limit", "100"))
    chosen = [e for e in events if since is None or e["seq"] > int(since)][-limit:]
    body: dict[str, Any] = {
        "events": chosen,
        "next": chosen[-1]["seq"] if chosen else int(since or 0),
        "oldest": events[0]["seq"] if events else 0,
    }
    if since is not None and events and int(since) < events[0]["seq"] - 1:
        body["gap"] = True
    return body


class _Node:
    """Base commune : manifeste, événements, idempotence (§7.4), panne simulée."""

    manifest: dict[str, Any]

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.mode = "ok"  # ok | down | no_contract | redirect | huge
        self.events: list[dict[str, Any]] = []
        self.seen: dict[str, tuple[str, dict[str, Any]]] = {}

    def idempotent(self, request: httpx.Request, body: dict[str, Any], make: Any) -> httpx.Response:
        key = request.headers.get("idempotency-key")
        if key and key in self.seen:
            previous_body, answer = self.seen[key]
            if previous_body != json.dumps(body, sort_keys=True):
                return httpx.Response(
                    409, json={"detail": "Clé déjà utilisée", "code": "IDEMPOTENCY_KEY_REUSED"}
                )
            return httpx.Response(201, json=answer, headers={"Idempotency-Replayed": "true"})
        answer = make()
        if key:
            self.seen[key] = (json.dumps(body, sort_keys=True), answer)
        return httpx.Response(201, json=answer)

    def common(self, request: httpx.Request) -> httpx.Response | None:
        self.requests.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path
        if path == "/api/atelier/manifest":
            if self.mode == "no_contract":
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json=self.manifest)
        if path == "/api/atelier/events":
            return httpx.Response(200, json=page(self.events, request))
        return None


class FakeVizNode(_Node):
    manifest = VIZ_MANIFEST

    def __init__(self) -> None:
        super().__init__()
        self.viz = FakeDataVia()
        self.events = [
            {"seq": i, "type": "viz.dataset.refreshed", "at": "2026-10-21T20:00:00+02:00",
             "subject": {"kind": "dataset", "id": "ds_ventes", "label": "ventes"},
             "data": {"rows": 573, "trigger": "manual"}}
            for i in range(40, 43)
        ]  # fmt: skip
        self.published: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answer = self.common(request)
        if answer is not None:
            return answer
        path, method = request.url.path, request.method
        if self.mode == "redirect":
            return httpx.Response(302, headers={"Location": "http://ailleurs.example/"})
        if (method, path) == ("POST", "/api/atelier/query"):
            body = json.loads(request.content)
            if body["dataset_id"] == "inconnu":
                return httpx.Response(404, json={"detail": "Jeu introuvable", "code": "NOT_FOUND"})
            rows = [{"region": f"Région {i}", "ca": 1000 + i} for i in range(1500)]
            return httpx.Response(
                200,
                json={
                    "format": "atelier-table/1", "name": "query", "label": "Requête",
                    "columns": [{"key": "region", "label": "Région", "type": "string"},
                                {"key": "ca", "label": "CA", "type": "number"}],
                    "rows": rows if self.mode != "huge" else rows * 1000,
                    "total": 1500, "truncated": False,
                },
            )  # fmt: skip
        if (method, path) == ("GET", "/api/atelier/datasets"):
            query = request.url.query.decode()
            return httpx.Response(200, json={"datasets": ["ds_ventes"], "query": query})
        if (
            method == "POST"
            and path.startswith("/api/atelier/datasets/")
            and path.endswith("/rows")
        ):
            body = json.loads(request.content)
            name = path.split("/")[4]

            def make() -> dict[str, Any]:
                self.published.append({"name": name, **body})
                return {"id": f"ds_{name}", "rows": len(body["table"]["rows"])}

            return self.idempotent(request, body, make)
        if method == "DELETE" and path.startswith("/api/atelier/datasets/"):
            return httpx.Response(200, json={"deleted": path.rsplit("/", 1)[1]})
        return self.viz.handler(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class FakeProjetsNode(_Node):
    manifest = PROJETS_MANIFEST

    def __init__(self) -> None:
        super().__init__()
        self.projets = FakeProjets()
        self.created: list[dict[str, Any]] = []
        self.events = [
            {"seq": 5, "type": "projets.work_item.created", "at": "2026-10-21T21:30:00+02:00",
             "subject": {"kind": "work_item", "id": "123", "label": "Écrire la doc"},
             "data": {"project_id": "1", "story_id": "2", "type": "TASK", "status": "OPEN"}},
        ]  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answer = self.common(request)
        if answer is not None:
            return answer
        path, method = request.url.path, request.method
        if method == "GET" and path.startswith("/api/atelier/projects/"):
            return httpx.Response(
                200,
                json={
                    "format": "atelier-table/1", "name": "work-items", "label": "Éléments",
                    "columns": [{"key": "id", "label": "Identifiant", "type": "number"},
                                {"key": "titre", "label": "Titre", "type": "string"}],
                    "rows": [{"id": 12345, "titre": "Moteur Git"}], "total": 1, "truncated": False,
                },
            )  # fmt: skip
        if method == "POST" and path.startswith("/api/atelier/stories/"):
            body = json.loads(request.content)
            story = int(path.split("/")[4])
            if body["title"] == "refus":
                return httpx.Response(
                    422, json={"detail": "Titre refusé par Projets", "code": "VALIDATION"}
                )

            def make() -> dict[str, Any]:
                item = {"id": 30000 + len(self.created), "story_id": story, **body}
                self.created.append(item)
                return item

            return self.idempotent(request, body, make)
        if method == "DELETE" and path.startswith("/api/atelier/work-items/"):
            return httpx.Response(200, json={"deleted": int(path.rsplit("/", 1)[1])})
        return self.projets(request)


def write_tab_manifest(exports: Path, manifest: dict[str, Any] | None = None) -> Path:
    folder = exports / "_atelier"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest or TAB_MANIFEST, ensure_ascii=False))
    return path


def mcp_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(FAKE_MCP)}"
