"""Double d'Atelier Convert pour httpx.MockTransport (contrat `atelier-node/1`).

Le manifeste est celui que produit le code d'Atelier Convert (`build_manifest()`, enregistré dans
`tests/fixtures/convert/manifest.json`) ; les routes et les réponses suivent
`backend/app/api/routes/atelier.py`, `routes/conversions.py` et `app/schemas/atelier.py` du dépôt :
mêmes chemins, même `Idempotency-Key` (même clé + autre requête → 409), même journal d'événements.
"""

from __future__ import annotations

import json
import re
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


class FakeConvert:
    def __init__(self) -> None:
        self.conversions: dict[str, dict[str, Any]] = {
            "a1b2c3d4e5f6": {
                "id": "a1b2c3d4e5f6", "name": "Relevé octobre", "created_at": "2026-10-24T09:00:00Z",
                "updated_at": "2026-10-24T09:00:00Z",
                "source": {"filename": "releve-octobre.pdf", "format": "pdf", "size": 48213},
                "detected": "Relevé bancaire · 3 opérations", "rows": 3, "columns": 4,
                "statement": None, "sent": [],
                "table_rows": [
                    {"date": "2026-10-02", "libelle": "Loyer", "montant": -850.0, "solde": 1150.0},
                    {"date": "2026-10-05", "libelle": "Salaire", "montant": 2400.0, "solde": 3550.0},
                    {"date": "2026-10-09", "libelle": "Courses", "montant": -96.4, "solde": 3453.6},
                ],
            },
        }  # fmt: skip
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
            return 200, [
                {k: v for k, v in c.items() if k != "table_rows"} for c in self.conversions.values()
            ]
        if path == "/api/tab" and method == "GET":
            return 200, {"found": True, "directory": "~/Atelier_Tab", "projects": [
                {"id": "proj_budget", "name": "Budget", "workspace": "Maison", "tables": 2}]}  # fmt: skip
        if path == "/api/atelier/events" and method == "GET":
            since = int(params.get("since") or 0)
            types = [t for t in (params.get("types") or "").split(",") if t]
            events = [
                e for e in self.events if e["seq"] > since and (not types or e["type"] in types)
            ]
            last = self.events[-1]["seq"] if self.events else 0
            return 200, {
                "events": events,
                "next": events[-1]["seq"] if events else max(since, last),
                "oldest": 1,
                "gap": False,
            }
        m = re.fullmatch(r"/api/atelier/conversions/([0-9a-f]{12})/(table|send-to-tab)", path)
        if m:
            conversion = self.conversions.get(m[1])
            if conversion is None:
                return 404, {"detail": "Conversion introuvable.", "code": "NOT_FOUND"}
            if m[2] == "table" and method == "GET":
                offset, limit = int(params.get("offset") or 0), int(params.get("limit") or 1000)
                rows = conversion["table_rows"][offset : offset + limit]
                return 200, {"format": "atelier-table/1", "name": f"conversion-{m[1]}",
                             "label": conversion["name"], "columns": COLUMNS, "rows": rows,
                             "total": len(conversion["table_rows"]),
                             "truncated": offset + len(rows) < len(conversion["table_rows"])}  # fmt: skip
            if m[2] == "send-to-tab" and method == "POST":
                if body.get("project_id") != "proj_budget":
                    return 404, {"detail": "Projet d'Atelier Tab introuvable.", "code": "NOT_FOUND"}
                result = {"table_id": f"tbl_{len(self.sent) + 1}", "table_name": body.get("table_name") or conversion["name"],
                          "project_id": "proj_budget", "project_name": "Budget", "rows": conversion["rows"],
                          "columns": conversion["columns"], "file": "tables/tbl_1.json"}  # fmt: skip
                self.sent.append(result)
                return 200, result
        return 404, {"detail": "Route inconnue.", "code": "NOT_FOUND"}
