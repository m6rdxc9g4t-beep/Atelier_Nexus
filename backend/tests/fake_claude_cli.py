#!/usr/bin/env python3
"""Faux programme `claude` (Claude Code) pour les tests : mêmes options, même sortie JSON.

FAKE_CLAUDE_MODE : text | tool | login | limit | limit_401 | limit_login | too_long | slow |
auth_off | expired | echo | crash.
Chaque appel est consigné dans FAKE_CLAUDE_LOG (PID, arguments, entrée standard, variables
sensibles, dossier courant) — `auth status` compris, sur une ligne `{"auth_status": true}`.
`expired` : jeton du forfait refusé (401) ; `echo` et `crash` répètent le jeton reçu dans leur
message d'erreur (sortie JSON, puis sortie d'erreur brute) : Nexus doit le masquer.
`limit_401`, `limit_login` : limite du forfait dont le message ressemble à un refus (« 401 » dans
l'heure de remise à zéro, « /login » pour changer de compte) ; `too_long` : conversation trop
longue, « 401 » dans le nombre de jetons — ni l'une ni l'autre n'est un jeton refusé.
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
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"auth_status": True, "args": args}) + "\n")
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
                    "pid": os.getpid(),
                    "args": args,
                    "stdin": stdin,
                    "cwd_empty": not os.listdir("."),
                    "env": {
                        k: os.environ.get(k)
                        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")
                    },
                    # Authentification : jeton du forfait, dossiers de l'utilisateur
                    "auth": {
                        k: os.environ.get(k)
                        for k in (
                            "CLAUDE_CODE_OAUTH_TOKEN",
                            "CLAUDE_OAUTH_TOKEN",
                            "HOME",
                            "CLAUDE_CONFIG_DIR",
                        )
                    },
                    "env_names": sorted(os.environ),
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
received = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
if mode == "expired":
    out(
        {
            "type": "result",
            "is_error": True,
            "result": 'API Error: 401 {"type":"error","error":{"type":"authentication_error",'
            '"message":"OAuth token has expired. Please obtain a new token."}}',
        },
        1,
    )
if mode == "echo":
    out({"type": "result", "is_error": True, "result": f"Panne interne avec {received} !"}, 1)
if mode == "crash":
    print("x" * 380 + f" jeton {received} fin", file=sys.stderr)
    sys.exit(2)
if mode == "limit":
    out(
        {"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1760900000"},
        1,
    )
if mode == "limit_401":
    out(
        {"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1794010000"},
        1,
    )
if mode == "limit_login":
    out(
        {
            "type": "result",
            "is_error": True,
            "result": "You've hit your usage limit · resets 3pm · /login to switch accounts",
        },
        1,
    )
if mode == "too_long":
    out(
        {
            "type": "result",
            "is_error": True,
            "result": "Prompt is too long: 240117 tokens > 200000 maximum",
        },
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
