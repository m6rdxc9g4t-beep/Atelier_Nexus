"""Double d'Atelier Convert pour httpx.MockTransport (contrat `atelier-node/1`).

Le manifeste est celui que produit le code d'Atelier Convert (`build_manifest()`, enregistré dans
`tests/fixtures/convert/manifest.json`, docs/apps/convert.md pour le régénérer) ; routes et
réponses suivent le dépôt de Convert :

- `app/api/routes/atelier.py` : table d'une conversion (`service.table_page`), conversion d'un
  fichier en base64, envoi dans Tab, événements ; `Idempotency-Key` (même clé + autre requête →
  409 `IDEMPOTENCY_KEY_REUSED`, rejeu → en-tête `Idempotency-Replayed`) ;
- `app/api/routes/conversions.py` : historique (`ConversionSummary`), suppression ;
- `app/services/atelier/journal.py` (`page`) : `since` exclusif, `limit`, `types`, `next`,
  `oldest`, `gap`.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx

MANIFEST: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "convert" / "manifest.json").read_text(encoding="utf-8")
)

COLUMNS = [
    {"key": "date", "label": "Date", "type": "date"},
    {"key": "libelle", "label": "Libellé", "type": "string"},
    {"key": "montant", "label": "Montant", "type": "number"},
    {"key": "solde", "label": "Solde", "type": "number"},
]

ROWS = [
    {"date": "2026-10-02", "libelle": "Loyer", "montant": -850.0, "solde": 1150.0},
    {"date": "2026-10-05", "libelle": "Salaire", "montant": 2400.0, "solde": 3550.0},
    {"date": "2026-10-09", "libelle": "Courses", "montant": -96.4, "solde": 3453.6},
]


def snake_key(label: str, fallback: str = "conversion") -> str:
    """`snake_key` de services/convert/values.py (nom d'une table `atelier-table/1`)."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", label) if unicodedata.category(c) != "Mn"
    )
    key = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_") or fallback
    return (f"c_{key}" if key[0].isdigit() else key)[:60]


def summary(cid: str, name: str, filename: str) -> dict[str, Any]:
    """`ConversionSummary` (schemas/convert.py) ; les lignes sont gardées à part."""
    return {
        "id": cid, "name": name, "created_at": "2026-10-24T09:00:00Z",
        "updated_at": "2026-10-24T09:00:00Z",
        "source": {"filename": filename, "kind": "pdf", "size": 48213, "sha256": "0" * 64,
                   "pages": 1, "encoding": None, "delimiter": None, "sheets": [], "ocr": False,
                   "ocr_confidence": None},
        "detected": "Relevé bancaire · 3 opérations", "rows": len(ROWS), "columns": len(COLUMNS),
        "statement": None, "sent": [],
    }  # fmt: skip


class FakeConvert:
    def __init__(self) -> None:
        self.conversions: dict[str, dict[str, Any]] = {
            "a1b2c3d4e5f6": summary("a1b2c3d4e5f6", "Relevé octobre", "releve-octobre.pdf")
        }
        self.rows: dict[str, list[dict[str, Any]]] = {"a1b2c3d4e5f6": list(ROWS)}
        self.events: list[dict[str, Any]] = [
            {"seq": 1, "type": "convert.conversion.created", "at": "2026-10-24T09:00:00Z",
             "subject": {"kind": "conversion", "id": "a1b2c3d4e5f6", "label": "Relevé octobre"},
             "data": {"name": "Relevé octobre", "format": "pdf", "rows": 3, "columns": 4,
                      "statement": True, "ocr": False, "origin": "interface"}},
        ]  # fmt: skip
        self.requests: list[httpx.Request] = []
        self.replays: dict[str, tuple[str, int, Any]] = {}
        self.sent: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content) if request.content else {}
        key = request.headers.get("idempotency-key")
        fingerprint = f"{request.method} {request.url.path} {json.dumps(body, sort_keys=True)}"
        if key and key in self.replays:
            known, status, payload = self.replays[key]
            if known != fingerprint:
                return httpx.Response(
                    409, json={"detail": "Clé déjà utilisée.", "code": "IDEMPOTENCY_KEY_REUSED"}
                )
            return httpx.Response(status, json=payload, headers={"Idempotency-Replayed": "true"})
        status, payload = self.route(request, body)
        if key and status < 300:
            self.replays[key] = (fingerprint, status, payload)
        return httpx.Response(status, json=payload)

    def route(self, request: httpx.Request, body: Any) -> tuple[int, Any]:
        path, method, params = request.url.path, request.method, request.url.params
        if path == "/api/atelier/manifest":
            return 200, MANIFEST
        if path == "/api/health":
            return 200, {"status": "ok", "app": "atelier-convert"}
        if path == "/api/conversions" and method == "GET":
            return 200, list(self.conversions.values())
        if path == "/api/tab" and method == "GET":
            return 200, {
                "found": True,
                "directory": "~/Atelier_Tab",
                "projects": [
                    {"id": "proj_budget", "name": "Budget", "workspace": "Maison", "tables": 2}
                ],
            }
        if path == "/api/atelier/events" and method == "GET":
            return 200, self.events_page(params)
        if path == "/api/atelier/conversions" and method == "POST":
            return self.convert_file(body)
        m = re.fullmatch(r"/api/conversions/([0-9a-f]{12})", path)
        if m and method == "DELETE":
            if self.conversions.pop(m[1], None) is None:
                return 404, {"detail": "Conversion introuvable.", "code": "NOT_FOUND"}
            self.rows.pop(m[1], None)
            return 200, {"deleted": True}
        m = re.fullmatch(r"/api/atelier/conversions/([0-9a-f]{12})/(table|send-to-tab)", path)
        if m:
            conversion = self.conversions.get(m[1])
            if conversion is None:
                return 404, {"detail": "Conversion introuvable.", "code": "NOT_FOUND"}
            if m[2] == "table" and method == "GET":
                return 200, self.table_page(m[1], params)
            if m[2] == "send-to-tab" and method == "POST":
                return self.send_to_tab(conversion, body)
        return 404, {"detail": "Route inconnue.", "code": "NOT_FOUND"}

    def table_page(self, cid: str, params: httpx.QueryParams) -> dict[str, Any]:
        """`service.table_page` : page de lignes, `truncated` dès qu'on n'a pas tout depuis 0."""
        offset, limit = int(params.get("offset") or 0), int(params.get("limit") or 1000)
        all_rows = self.rows[cid]
        rows = all_rows[offset : offset + limit]
        name = self.conversions[cid]["name"]
        return {
            "format": "atelier-table/1", "name": snake_key(name), "label": name,
            "columns": COLUMNS, "rows": rows, "total": len(all_rows),
            "truncated": offset + len(rows) < len(all_rows) or offset > 0,
        }  # fmt: skip

    def convert_file(self, body: dict[str, Any]) -> tuple[int, Any]:
        """`convert_file` : base64 validé, conversion créée (origine « workflow »)."""
        try:
            base64.b64decode(body.get("content_base64", ""), validate=True)
        except (binascii.Error, ValueError):
            return 422, {
                "detail": "content_base64 n'est pas du base64 valide.",
                "code": "VALIDATION",
            }
        cid = f"{len(self.conversions) + 1:012x}"
        self.conversions[cid] = summary(cid, body["filename"], body["filename"])
        self.rows[cid] = list(ROWS)
        result = {"conversion_id": cid, "name": body["filename"], "detected": "Tableau · 3 lignes",
                  "rows": len(ROWS), "columns": len(COLUMNS), "warnings": []}  # fmt: skip
        return 201, result

    def send_to_tab(self, conversion: dict[str, Any], body: dict[str, Any]) -> tuple[int, Any]:
        if body.get("project_id") != "proj_budget":
            return 404, {"detail": "Projet Atelier Tab introuvable.", "code": "NOT_FOUND"}
        name = " ".join((body.get("table_name") or conversion["name"]).split())[:200]
        result = {"table_id": f"tbl_{len(self.sent) + 1}", "table_name": name,
                  "project_id": "proj_budget", "project_name": "Budget", "rows": conversion["rows"],
                  "columns": conversion["columns"], "file": f"tables/tbl_{len(self.sent) + 1}.json"}  # fmt: skip
        self.sent.append(result)
        return 200, result

    def events_page(self, params: httpx.QueryParams) -> dict[str, Any]:
        """`EventJournal.page` : après `since` (exclusif), ou les plus récents."""
        since = int(params["since"]) if params.get("since") is not None else None
        limit = int(params.get("limit") or 100)
        types = {t for t in (params.get("types") or "").split(",") if t} or None
        last = self.events[-1]["seq"] if self.events else 0
        oldest = self.events[0]["seq"] if self.events else last + 1
        matching = [e for e in self.events if types is None or e["type"] in types]
        if since is None:
            chosen = matching[-limit:]
        else:
            chosen = [e for e in matching if e["seq"] > since][:limit]
        gap = since is not None and (since < oldest - 1 or since > last)
        nxt = chosen[-1]["seq"] if chosen else (since if since is not None else last)
        return {"events": chosen, "next": nxt, "oldest": oldest, "gap": gap}
