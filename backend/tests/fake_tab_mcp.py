"""Faux serveur MCP d'Atelier Tab (stdio, une ligne JSON par message) pour les tests.

Reproduit le protocole et les réponses du vrai serveur (`desktop/mcp-server.ts`) :
`initialize`, `tools/list`, `tools/call` avec un résultat JSON en texte, `isError` pour un
refus. Comportement choisi par FAKE_MODE : normal, crash (s'arrête après l'initialisation),
slow (ne répond pas), noisy (journal et notifications avant chaque réponse).
Chaque message reçu et l'environnement sont consignés dans FAKE_LOG.
"""

import json
import os
import sys
import time

# Comme le vrai serveur (Node.js) : UTF-8 sur l'entrée et la sortie, quel que soit le système
sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

MODE = os.environ.get("FAKE_MODE", "normal")
LOG = os.environ.get("FAKE_LOG")


def log(entry: object) -> None:
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def reply(message_id: object, result: object) -> None:
    if MODE == "noisy":
        sys.stdout.write("journal: appel reçu\n")
        sys.stdout.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}) + "\n"
        )
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}, ensure_ascii=False)
        + "\n"
    )
    sys.stdout.flush()


def text(payload: object, error: bool = False) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": body}], "isError": error}


#: Manifeste atelier-node/1 de Tab (même contenu que tests/fake_suite.py:TAB_MANIFEST)
MANIFEST_FILE = os.environ.get("FAKE_MANIFEST")
EVENTS = [
    {"seq": 7, "type": "tab.table.changed", "at": "2026-10-21T21:00:00+02:00",
     "subject": {"kind": "table", "id": "tbl_planning_lots", "label": "Planning & Lots"},
     "data": {"revision": 3, "rows": 3, "project": "Rénovation Urbaine 2026"}},
    {"seq": 8, "type": "tab.table.changed", "at": "2026-10-21T21:05:00+02:00",
     "subject": {"kind": "table", "id": "tbl_materiaux", "label": "Matériaux"},
     "data": {"revision": 1, "rows": 2, "project": "Rénovation Urbaine 2026"}},
]  # fmt: skip
TABLE = {
    "format": "atelier-table/1", "name": "tbl_planning_lots", "label": "Planning & Lots",
    "columns": [{"key": "_ligne", "label": "Ligne", "type": "number"},
                {"key": "task_name", "label": "Lot / Tâche", "type": "string"},
                {"key": "cost_ht", "label": "Coût HT", "type": "number"}],
    "rows": [{"_ligne": 1, "task_name": "Gros œuvre", "cost_ht": 45000},
             {"_ligne": 2, "task_name": "Charpente bois", "cost_ht": 28500}],
    "total": 2, "truncated": False,
}  # fmt: skip
#: Réponses déjà données par clé d'idempotence (rejouées à l'identique, §7.4)
SEEN: dict[str, dict] = {}


def call(name: str, args: dict) -> dict:
    if name == "atelier_manifest":
        if MODE == "nocontract" or not MANIFEST_FILE:
            return text("Outil inconnu : atelier_manifest", error=True)
        with open(MANIFEST_FILE, encoding="utf-8") as fh:
            return text(json.load(fh))
    if name == "atelier_events":
        since = args.get("since")
        events = [e for e in EVENTS if since is None or e["seq"] > since][: args.get("limit", 100)]
        return text({"events": events, "next": events[-1]["seq"] if events else since or 0,
                     "oldest": 7})  # fmt: skip
    if name == "query_table":
        if args.get("table_id") == "tbl_inconnue":
            return text({"detail": "Table introuvable", "code": "NOT_FOUND"}, error=True)
        return text(TABLE)
    if name == "add_rows" and args.get("idempotency_key"):
        key = args["idempotency_key"]
        if key in SEEN:
            return text(SEEN[key] | {"replayed": True})
        SEEN[key] = {"added": [{"row": 4 + i, "id": f"rec_new{i}", "cells": dict(r)}
                               for i, r in enumerate(args["rows"])]}  # fmt: skip
        return text(SEEN[key])
    if name == "set_cells":
        if args["table"] == "tbl_inconnue":
            return text("Table « tbl_inconnue » introuvable", error=True)
        return text(
            {
                "updated": [
                    {"cell": f"{c['column']}{c['row']}", "value": c["value"]} for c in args["cells"]
                ]
                + [{"cell": "D2", "value": "#DIV/0!", "error": "Division par zéro"}]
            }
        )
    if name == "add_rows":
        return text(
            {
                "added": [
                    {"row": 4 + i, "id": f"rec_new{i}", "cells": dict(r)}
                    for i, r in enumerate(args["rows"])
                ]
            }
        )
    if name == "delete_rows":
        return text({"deleted": len(args["rows"]), "remaining_rows": 2})
    if name == "add_column":
        return text(
            {"added": {"letter": "G", "id": "fld_x", "label": args["label"], "type": args["type"]}}
        )
    if name == "create_table":
        return text(
            {
                "table_id": "tbl_nouvelle",
                "columns": [
                    {"letter": chr(65 + i), "label": c["label"]}
                    for i, c in enumerate(args.get("columns") or [])
                ],
            }
        )
    return text(f"Outil inconnu : {name}", error=True)


log(
    {
        "env": {
            k: v
            for k, v in os.environ.items()
            if k in ("ATELIER_TAB_DATA", "ANTHROPIC_API_KEY", "SECRET_NEXUS")
        }
    }
)
for line in sys.stdin:
    message = json.loads(line)
    log(message)
    method = message.get("method")
    if method == "initialize":
        reply(
            message["id"],
            {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "atelier-tab", "version": "test"},
                "capabilities": {"tools": {}},
            },
        )
        if MODE == "crash":
            sys.stderr.write("Erreur : dossier de données illisible\n")
            sys.stderr.flush()
            sys.exit(3)
    elif method == "tools/list":
        reply(
            message["id"],
            {
                "tools": [
                    {"name": n}
                    for n in ("set_cells", "add_rows", "delete_rows", "add_column", "create_table")
                ]
            },
        )
    elif method == "tools/call":
        if MODE == "slow":
            time.sleep(30)
        reply(
            message["id"], call(message["params"]["name"], message["params"].get("arguments", {}))
        )
