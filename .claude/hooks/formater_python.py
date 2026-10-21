#!/usr/bin/env python3
"""Hook PostToolUse (Edit, Write, MultiEdit) : formate le fichier Python modifié du backend.

`ruff format` puis le tri des imports (`ruff check --select I --fix`), comme la CI le vérifie.
Utilise le ruff de `backend/.venv` s'il existe, sinon celui du PATH. Ne bloque jamais :
un fichier non formaté sera signalé par `ruff check` / la CI, pas par ce hook.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def ruff_binary(backend: str) -> str | None:
    for candidate in (
        os.path.join(backend, ".venv", "bin", "ruff"),
        os.path.join(backend, ".venv", "Scripts", "ruff.exe"),
    ):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ruff")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = str((payload.get("tool_input") or {}).get("file_path") or "")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    backend = os.path.join(root, "backend")
    absolute = os.path.normpath(os.path.join(root, file_path))
    if not absolute.endswith(".py") or not absolute.startswith(backend + os.sep):
        return 0
    if not os.path.exists(absolute):
        return 0
    ruff = ruff_binary(backend)
    if ruff is None:
        return 0
    for args in (["format", absolute], ["check", "--select", "I", "--fix", absolute]):
        try:
            subprocess.run([ruff, *args], cwd=backend, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
