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


def call(name: str, args: dict) -> dict:
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
