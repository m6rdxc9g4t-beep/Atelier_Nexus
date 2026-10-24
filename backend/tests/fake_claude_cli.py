#!/usr/bin/env python3
"""Faux programme `claude` (Claude Code) pour les tests : mêmes options, même sortie JSON.

FAKE_CLAUDE_MODE : text | tool | loose | native | legacy | noresult | replay | login | limit |
slow | auth_off. Chaque appel est
consigné dans FAKE_CLAUDE_LOG (arguments, entrée standard, variables sensibles, dossier courant).
Sortie `--output-format stream-json` (comme Claude Code 2.1.310) : ligne `system`, lignes
`assistant` (texte libre éventuel, appel à StructuredOutput), ligne `result` finale.
« loose » : la réponse est écrite en texte libre hors de l'objet, l'objet ne garde qu'une phrase ;
« native » : appel direct refusé (« No such tool available ») avant l'objet ; « legacy » : ancienne
version sans `structured_output` ; « noresult » : flux interrompu sans ligne `result` ;
« replay » : vraie sortie de Claude Code 2.1.310, anonymisée (tests/fixtures/claude_code/).
"""

import json
import os
import sys
import time

# Comme Claude Code : UTF-8 sur l'entrée et la sortie, quel que soit le système
sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

mode = os.environ.get("FAKE_CLAUDE_MODE", "text")
args = sys.argv[1:]
log = os.environ.get("FAKE_CLAUDE_LOG")

if args[:2] == ["auth", "status"]:
    print(
        json.dumps(
            {
                "loggedIn": mode != "auth_off",
                "authMethod": "claude.ai" if mode != "auth_off" else "none",
            }
        )
    )
    sys.exit(0 if mode != "auth_off" else 1)

stdin = sys.stdin.read()
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "args": args,
                    "stdin": stdin,
                    "cwd_empty": not os.listdir("."),
                    "env": {
                        k: os.environ.get(k)
                        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")
                    },
                    "env_names": sorted(os.environ),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


STREAM = "--output-format" in args and args[args.index("--output-format") + 1] == "stream-json"


def emit(*events: dict) -> None:
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


def out(payload: dict, code: int = 0, loose: str = "") -> None:
    # Le provider demande toujours stream-json (avec --verbose, exigé par Claude Code)
    assert STREAM and "--verbose" in args
    content = [{"type": "text", "text": loose}] if loose else []
    if "structured_output" in payload:
        content.append(
            {"type": "tool_use", "name": "StructuredOutput", "input": payload["structured_output"]}
        )
    emit(
        {"type": "system", "subtype": "init", "tools": ["StructuredOutput"]},
        {"type": "assistant", "message": {"content": content}},
        payload,
    )
    sys.exit(code)


usage = {
    "input_tokens": 3,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 7,
    "output_tokens": 20,
}
if "--input-format" in args:
    # Entrée stream-json (conversation avec images) : sortie stream-json, ligne `result` finale
    assert args[args.index("--input-format") + 1] == "stream-json"
    assert args[args.index("--output-format") + 1] == "stream-json" and "--verbose" in args
    message = json.loads(stdin.strip().splitlines()[-1])["message"]
    kinds = [b["type"] for b in message["content"]]
    print(json.dumps({"type": "system", "subtype": "init"}))
    print(json.dumps({"type": "assistant", "message": {"content": []}}))
    print(
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "usage": usage,
                "structured_output": {"text": "Blocs reçus : " + ",".join(kinds), "tool_calls": []},
            }
        )
    )
    sys.exit(0)
if mode == "slow":
    time.sleep(30)
if mode == "login":
    out({"type": "result", "is_error": True, "result": "Invalid API key · Please run /login"}, 1)
if mode == "limit":
    out(
        {"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1760900000"},
        1,
    )
if mode == "tool" and "## Résultat de" not in stdin:
    out(
        {
            "type": "result",
            "is_error": False,
            "usage": usage,
            "structured_output": {
                "text": "Je regarde la date.",
                "tool_calls": [
                    {
                        "name": "current_datetime",
                        "arguments": json.dumps({"timezone": "Europe/Paris"}),
                    }
                ],
            },
        }
    )
if mode == "replay":
    fixture = os.path.join(
        os.path.dirname(__file__), "fixtures", "claude_code", "stream_tool_call.jsonl"
    )
    with open(fixture, encoding="utf-8") as fh:
        sys.stdout.write(fh.read())
    sys.exit(0)
if mode == "noresult":
    emit({"type": "system", "subtype": "init", "session_id": "secret-session", "cwd": "/Users/moi"})
    print("Erreur réseau : connexion interrompue", file=sys.stderr)
    sys.exit(int(os.environ.get("FAKE_CLAUDE_CODE", "1")))
if mode == "native":
    emit(
        {"type": "system", "subtype": "init", "tools": ["StructuredOutput"]},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Je vais regarder le tableau de bord."},
            {"type": "tool_use", "name": "projets_dashboard", "input": {"project_id": 1}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "No such tool available"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "StructuredOutput", "input": {
                "text": "Je consulte le tableau de bord.",
                "tool_calls": [{"name": "projets_dashboard", "arguments": "{\"project_id\": 1}"}],
            }},
        ]}},
        {"type": "result", "is_error": False, "usage": usage, "structured_output": {
            "text": "Je consulte le tableau de bord.",
            "tool_calls": [{"name": "projets_dashboard", "arguments": "{\"project_id\": 1}"}],
        }},
    )  # fmt: skip
    sys.exit(0)
if mode == "legacy":
    answer = json.dumps({"text": "Ligne 1\nLigne « 2 »", "tool_calls": []}, ensure_ascii=False)
    emit(
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}},
        {"type": "result", "is_error": False, "usage": usage, "result": answer},
    )
    sys.exit(0)
if mode == "loose":
    out(
        {
            "type": "result",
            "is_error": False,
            "usage": usage,
            "structured_output": {"text": "Je n'ai rien écrit pour l'instant.", "tool_calls": []},
        },
        loose="## Comité du 24/10\n\nAvancement : 71 %.",
    )
final = "Nous sommes le 20 octobre." if "## Résultat de" in stdin else "Bonjour !"
out(
    {
        "type": "result",
        "is_error": False,
        "usage": usage,
        "structured_output": {"text": final, "tool_calls": []},
    }
)
