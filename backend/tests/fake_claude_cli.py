#!/usr/bin/env python3
"""Faux programme `claude` (Claude Code) pour les tests : mêmes options, même sortie JSON.

FAKE_CLAUDE_MODE : text | tool | login | limit | slow | auth_off. Chaque appel est consigné
dans FAKE_CLAUDE_LOG (arguments, entrée standard, variables sensibles, dossier courant).
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
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def out(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
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
final = "Nous sommes le 20 octobre." if "## Résultat de" in stdin else "Bonjour !"
out(
    {
        "type": "result",
        "is_error": False,
        "usage": usage,
        "structured_output": {"text": final, "tool_calls": []},
    }
)
