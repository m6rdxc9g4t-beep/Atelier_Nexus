"""Doubles des nœuds de la suite (contrat atelier-node/1) pour httpx.MockTransport et MCP.

Manifestes de Viz, Projets et Tab : noms d'actions SUPPOSÉS, choisis pour exercer le moteur
(les vrais manifestes en diffèrent : voir `REAL_MANIFESTS`) :
- Viz : `datasets.query` (lecture, table), `datasets.list` (GET avec requête),
  `datasets.upsert_rows` (écriture, `Idempotency-Key`), `datasets.delete` (destructive) ;
- Projets : `work_items.list` (lecture, table), `work_items.create` (écriture, `Idempotency-Key`),
  `work_items.delete` (destructive) ;
- Tab (MCP) : `tables.query` (`query_table`), `rows.add` (`add_rows`, champ `idempotency_key`),
  `rows.delete` (`delete_rows`, destructive).
Les routes non « atelier » sont déléguées aux doubles existants (Data Via, Projets).

Convert : manifeste RÉEL (`tests/fixtures/convert/manifest.json`, capturé une fois avec
`build_manifest()` dans le venv d'Atelier_Convert, version 0.1.0), jamais retouché. Le double
répond aux routes de ce manifeste (`FakeConvertNode`).

`REAL_MANIFESTS` : manifestes réels de Viz (0.1.0, `build_manifest()`), Projets (0.1.0,
`buildManifest()` du backend compilé) et Tab (0.6.0, `_atelier/manifest.json` écrit par l'app),
enregistrés dans `tests/fixtures/<app>/manifest.json` : la bibliothèque des modèles de workflows
est validée contre eux (`tests/test_workflow_library.py`).
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
FIX = Path(__file__).parent / "fixtures"


def _recorded(app: str) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((FIX / app / "manifest.json").read_text("utf-8"))
    return manifest


CONVERT_MANIFEST = _recorded("convert")
REAL_MANIFESTS: dict[str, dict[str, Any]] = {
    app: _recorded(app) for app in ("viz", "projets", "tab", "convert")
}

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

#: data_schema des événements (§7.1) : propriétés de premier niveau → chemins `data.x` des filtres
PROJETS_EVENTS: list[dict[str, Any]] = [
    {"type": "projets.work_item.created", "label": "Élément créé",
     "data_schema": {"type": "object", "properties": {
         "project_id": {"type": "string"}, "story_id": {"type": "string"},
         "type": {"type": "string"}, "status": {"type": "string"}}}},
    {"type": "projets.work_item.status_changed", "label": "Statut changé",
     "data_schema": {"type": "object", "properties": {
         "project_id": {"type": "string"}, "from": {"type": "string"},
         "to": {"type": "string"}}}},
    {"type": "projets.time_entry.created", "label": "Temps saisi",
     "data_schema": {"type": "object", "properties": {
         "project_id": {"type": "string"}, "hours": {"type": "number"},
         "spent_on": {"type": "string"}}}},
    {"type": "projets.work_item.deleted", "label": "Élément supprimé", "data_schema": "illisible"},
]  # fmt: skip

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
    "events": PROJETS_EVENTS,
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
    """Réponse §7.3 / §7.7 : `since` exclusif, sans `since` les plus récents, `next` = dernier
    seq rendu (sinon `since`, sinon le dernier connu), `gap` si des événements ont été retirés
    ou si `since` dépasse le dernier seq connu (journal remis à zéro)."""
    since_raw = request.url.params.get("since")
    since = int(since_raw) if since_raw is not None else None
    limit = int(request.url.params.get("limit", "100"))
    types = [t for t in request.url.params.get("types", "").split(",") if t]
    last = events[-1]["seq"] if events else 0
    pool = [e for e in events if not types or e["type"] in types]
    if since is None:
        chosen = pool[-limit:]
    else:
        chosen = [e for e in pool if e["seq"] > since][:limit]
    body: dict[str, Any] = {
        "events": chosen,
        "next": chosen[-1]["seq"] if chosen else (since if since is not None else last),
        "oldest": events[0]["seq"] if events else last + 1,
    }
    if since is not None and ((events and since < events[0]["seq"] - 1) or since > last):
        body["gap"] = True
    return body


def event(
    seq: int,
    type_: str = "projets.work_item.status_changed",
    *,
    subject_id: str = "123",
    label: str = "Écrire la doc",
    **data: Any,
) -> dict[str, Any]:
    """Événement Projets au format §7.3 (`data` : identifiants en chaînes)."""
    return {
        "seq": seq,
        "type": type_,
        "at": f"2026-10-22T09:{seq % 60:02d}:00+02:00",
        "subject": {"kind": "work_item", "id": subject_id, "label": label},
        "data": data,
    }


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


#: Identifiants de conversion (12 caractères hexadécimaux, comme Convert)
RELEVE_ID = "0123456789ab"
BRUT_ID = "abcdef012345"


def convert_event(seq: int, conversion_id: str = RELEVE_ID, **data: Any) -> dict[str, Any]:
    """Événement `convert.conversion.created` au format §7.3 (champs du manifeste réel)."""
    return {
        "seq": seq,
        "type": "convert.conversion.created",
        "at": f"2026-10-24T10:{seq % 60:02d}:00+02:00",
        "subject": {"kind": "conversion", "id": conversion_id, "label": "Relevé octobre"},
        "data": {"name": "Relevé octobre", "format": "pdf", "rows": 3, "columns": 5,
                 "statement": True, "ocr": False, "origin": "interface"} | data,
    }  # fmt: skip


class FakeConvertNode(_Node):
    """Atelier Convert (API sur 8010, préfixe `/api`) : routes de son manifeste réel.

    Deux conversions : un relevé bancaire reconnu (`RELEVE_ID`, colonnes normalisées Date,
    Libellé, Débit, Crédit, Montant) et un CSV brut (`BRUT_ID`). Écritures idempotentes
    (`Idempotency-Key`, rejeu, 409)."""

    manifest = CONVERT_MANIFEST

    COLUMNS = [
        {"key": "date", "label": "Date", "type": "date"},
        {"key": "libelle", "label": "Libellé", "type": "string"},
        {"key": "debit", "label": "Débit", "type": "number"},
        {"key": "credit", "label": "Crédit", "type": "number"},
        {"key": "montant", "label": "Montant", "type": "number"},
    ]
    ROWS = [
        {"date": "2026-10-01", "libelle": "Loyer", "debit": 850.0, "credit": None, "montant": -850.0},
        {"date": "2026-10-03", "libelle": "Salaire", "debit": None, "credit": 2400.0, "montant": 2400.0},
        {"date": "2026-10-12", "libelle": "Courses", "debit": 92.4, "credit": None, "montant": -92.4},
    ]  # fmt: skip

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []
        self.converted: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.events = [convert_event(seq) for seq in (1, 2, 3)]
        self.conversions: dict[str, dict[str, Any]] = {
            RELEVE_ID: {
                "id": RELEVE_ID, "name": "Relevé octobre",
                "created_at": "2026-10-24T10:00:00+02:00", "updated_at": "2026-10-24T10:05:00+02:00",
                "source": {"filename": "releve-octobre.pdf", "kind": "pdf", "size": 48213,
                           "sha256": "0" * 64, "pages": 2, "ocr": False},
                "detected": "Relevé bancaire · 3 opérations", "rows": 3, "columns": 5,
                "statement": {"transactions": 3, "start": "2026-10-01", "end": "2026-10-12",
                              "total_debit": 942.4, "total_credit": 2400.0,
                              "balance_check": "ok", "bank": "Banque Exemple"},
                "sent": [],
            },
            BRUT_ID: {
                "id": BRUT_ID, "name": "Export brut",
                "created_at": "2026-10-20T09:00:00+02:00", "updated_at": "2026-10-20T09:00:00+02:00",
                "source": {"filename": "export.csv", "kind": "csv", "size": 1200, "sha256": "1" * 64},
                "detected": "Tableau · 2 lignes", "rows": 2, "columns": 2, "statement": None,
                "sent": [],
            },
        }  # fmt: skip

    def _table(self, conversion_id: str, request: httpx.Request) -> dict[str, Any]:
        offset = int(request.url.params.get("offset", "0"))
        limit = int(request.url.params.get("limit", "1000"))
        name, label, columns, rows = "releve_octobre", "Relevé octobre", self.COLUMNS, self.ROWS
        if conversion_id == BRUT_ID:
            name, label = "export_brut", "Export brut"
            columns = [{"key": "ref", "label": "Réf", "type": "string"},
                       {"key": "qte", "label": "Qté", "type": "number"}]  # fmt: skip
            rows = [{"ref": "A", "qte": 1}, {"ref": "B", "qte": 2}]
        chosen = rows[offset : offset + limit]
        return {
            "format": "atelier-table/1", "name": name, "label": label, "columns": columns,
            "rows": chosen, "total": len(rows), "truncated": offset + len(chosen) < len(rows),
        }  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answer = self.common(request)
        if answer is not None:
            return answer
        path, method = request.url.path, request.method
        parts = path.strip("/").split("/")
        not_found = httpx.Response(
            404, json={"detail": "Conversion introuvable", "code": "NOT_FOUND"}
        )
        if (method, path) == ("GET", "/api/conversions"):
            listed = sorted(self.conversions.values(), key=lambda c: c["updated_at"], reverse=True)
            return httpx.Response(200, json=listed)
        if (method, path) == ("GET", "/api/tab"):
            return httpx.Response(
                200,
                json={"found": True, "directory": "/Users/test/Atelier_Tab",
                      "projects": [{"id": "proj_budget", "name": "Budget", "workspace": "Maison",
                                    "tables": 2}]},
            )  # fmt: skip
        if (
            method == "GET"
            and parts[:3] == ["api", "atelier", "conversions"]
            and parts[-1] == "table"
        ):
            if parts[3] not in self.conversions:
                return not_found
            return httpx.Response(200, json=self._table(parts[3], request))
        if (method, path) == ("POST", "/api/atelier/conversions"):
            body = json.loads(request.content)

            def convert() -> dict[str, Any]:
                result = {
                    "conversion_id": "fedcba987654", "name": body["filename"].rsplit(".", 1)[0],
                    "detected": "Tableau · 1 ligne", "rows": 1, "columns": 1, "warnings": [],
                }  # fmt: skip
                self.converted.append(result)
                return result

            return self.idempotent(request, body, convert)
        if (
            method == "POST"
            and parts[:3] == ["api", "atelier", "conversions"]
            and parts[-1] == "send-to-tab"
        ):
            conversion = self.conversions.get(parts[3])
            if conversion is None:
                return not_found
            body = json.loads(request.content)

            def send() -> dict[str, Any]:
                result = {
                    "table_id": f"tbl_{len(self.sent) + 1:03d}",
                    "table_name": body.get("table_name") or conversion["name"],
                    "project_id": body["project_id"], "project_name": "Budget",
                    "rows": conversion["rows"], "columns": conversion["columns"],
                    "file": f"tables/tbl_{len(self.sent) + 1:03d}.json",
                }  # fmt: skip
                self.sent.append({"conversion_id": parts[3], **result})
                return result

            return self.idempotent(request, body, send)
        if method == "DELETE" and parts[:2] == ["api", "conversions"] and len(parts) == 3:
            if self.conversions.pop(parts[2], None) is None:
                return not_found
            self.deleted.append(parts[2])
            return httpx.Response(200, json={"deleted": True})
        return httpx.Response(404, json={"detail": "Not Found"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def write_tab_manifest(exports: Path, manifest: dict[str, Any] | None = None) -> Path:
    folder = exports / "_atelier"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest or TAB_MANIFEST, ensure_ascii=False))
    return path


def mcp_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(FAKE_MCP)}"
