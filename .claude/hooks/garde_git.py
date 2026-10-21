#!/usr/bin/env python3
"""Hook PreToolUse (Bash) : garde-fous git de CLAUDE.md §4.

Bloque (code de sortie 2, message renvoyé à Claude) :
- un commit ou un push alors que la branche courante est `main` ou `master` ;
- un push qui vise `main` ou `master` (`git push origin main`, `HEAD:main`…) ;
- un push forcé (`--force`, `-f`) ; `--force-with-lease` reste permis sur une branche de travail ;
- la suppression d'une branche protégée (`git branch -D main`, `git push origin :main`).

Lit l'appel d'outil en JSON sur l'entrée standard. Ne dépend que de la bibliothèque standard.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
SEPARATORS = re.compile(r"&&|\|\||;|\||\n")


def current_branch(cwd: str | None) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_args(segment: str) -> list[str] | None:
    """Arguments après `git` (options globales comme `-C dossier` retirées), sinon None."""
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    # Préfixes d'environnement : `GIT_TRACE=1 git push`
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words.pop(0)
    if not words or words[0] != "git":
        return None
    args = words[1:]
    while args and args[0].startswith("-"):
        option = args.pop(0)
        if option in {"-C", "-c", "--git-dir", "--work-tree"} and args:
            args.pop(0)
    return args


def refspecs(push_args: list[str]) -> list[str]:
    positional = [a for a in push_args if not a.startswith("-")]
    return [spec.lstrip("+") for spec in positional[1:]]  # le 1er positionnel est le distant


def target_refs(push_args: list[str]) -> list[str]:
    """Branches visées par un push : la partie destination de chaque refspec."""
    return [
        (spec.split(":", 1)[1] if ":" in spec else spec).removeprefix("refs/heads/")
        for spec in refspecs(push_args)
    ]


def deletes_remote_branch(push_args: list[str]) -> bool:
    """`git push origin :branche` ou `git push --delete origin branche`."""
    if any(a in {"--delete", "-d"} for a in push_args):
        return True
    return any(spec.startswith(":") for spec in refspecs(push_args))


def check(command: str, cwd: str | None) -> str | None:
    """Motif du refus, ou None si la commande est acceptée."""
    branch: str | None = None
    branch_known = False
    for segment in SEPARATORS.split(command):
        args = git_args(segment.strip())
        if not args:
            continue
        sub, rest = args[0], args[1:]
        if sub in {"commit", "push"} and not branch_known:
            branch, branch_known = current_branch(cwd), True
        if sub == "commit" and branch in PROTECTED:
            return (
                f"Commit refusé : la branche courante est « {branch} ». CLAUDE.md §4 : "
                "créez d'abord une branche (git switch -c feat/… ou fix/…)."
            )
        if sub == "push":
            if any(a in {"--force", "-f"} or re.fullmatch(r"-[a-z]*f[a-z]*", a) for a in rest):
                return (
                    "Push forcé refusé. Utilisez --force-with-lease, et seulement sur votre "
                    "branche de travail."
                )
            if deletes_remote_branch(rest):
                return (
                    "Suppression d'une branche distante refusée depuis Claude Code : "
                    "faites-la vous-même sur GitHub."
                )
            targets = target_refs(rest)
            if any(t in PROTECTED for t in targets):
                return (
                    "Push vers main refusé (CLAUDE.md §4) : poussez une branche feat/… ou fix/… "
                    "puis ouvrez une pull request."
                )
            if not targets and branch in PROTECTED:
                return (
                    f"Push refusé : la branche courante est « {branch} ». Passez sur une branche "
                    "de travail avant de pousser."
                )
        if sub == "branch" and any(a in {"-D", "-d", "--delete"} for a in rest):
            if any(a in PROTECTED for a in rest):
                return "Suppression de main / master refusée."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # entrée illisible : on ne bloque pas l'outil pour autant
    if payload.get("tool_name") != "Bash":
        return 0
    command = str((payload.get("tool_input") or {}).get("command") or "")
    reason = check(command, payload.get("cwd"))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
