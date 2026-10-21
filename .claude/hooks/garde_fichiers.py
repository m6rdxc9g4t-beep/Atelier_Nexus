#!/usr/bin/env python3
"""Hook PreToolUse (Edit, Write, MultiEdit, NotebookEdit) : fichiers que Claude ne modifie pas.

- **Secrets** : `.env`, `.env.*` (sauf `.env.example`) et `cuisine-session.json`. Les réglages
  passent par la roue dentée de l'interface ou par l'utilisateur lui-même.
- **Copies verbatim** de la suite : `frontend/src/styles/atelier-ds/` et `frontend/src/styles/brand/`
  (source de vérité : Atelier_Projets/design-system, SUITE.md §1.1).
- **Historique figé**, création permise mais pas de modification :
  - `backend/migrations/versions/` (une migration publiée ne change plus : on en ajoute une) ;
  - `backend/tests/fixtures/` (réponses réelles enregistrées des applications : on ne les retouche
    pas pour faire passer un test).

Code de sortie 2 : l'outil est bloqué et le message est renvoyé à Claude.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import PurePosixPath

VERBATIM = ("frontend/src/styles/atelier-ds/", "frontend/src/styles/brand/")
FROZEN = ("backend/migrations/versions/", "backend/tests/fixtures/")


def relative(path: str, root: str) -> str:
    absolute = os.path.normpath(os.path.join(root, path))
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        return absolute
    return PurePosixPath(*rel.split(os.sep)).as_posix()


def check(tool: str, file_path: str, root: str) -> str | None:
    rel = relative(file_path, root)
    name = PurePosixPath(rel).name
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        return (
            f"{rel} contient des secrets : Claude ne l'écrit pas. Modifiez-le vous-même, ou "
            "passez par les Réglages de l'interface (roue dentée)."
        )
    if name == "cuisine-session.json":
        return f"{rel} contient des jetons de session : Claude ne l'écrit pas."
    if rel.startswith(VERBATIM):
        return (
            f"{rel} est une copie verbatim du design system de la suite (Atelier_Projets/"
            "design-system) : toute évolution se fait à la source, puis dans chaque application."
        )
    if rel.startswith(FROZEN):
        exists = os.path.exists(os.path.join(root, rel))
        if tool != "Write" or exists:
            kind = "migration publiée" if "migrations" in rel else "réponse réelle enregistrée"
            return (
                f"{rel} est une {kind} : ne la modifiez pas. Ajoutez un nouveau fichier "
                "(nouvelle migration Alembic, nouvelle fixture) à la place."
            )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not file_path:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    reason = check(tool, file_path, root)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
