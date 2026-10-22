"""Tests sous Windows : un faux programme écrit en Python doit être un `.exe` (Windows ne lance
pas un script `.py` directement, et Nexus refuse les scripts `.cmd` pour Claude Code)."""

import sys
import tempfile
from pathlib import Path


def console_exe(script: str) -> str:
    """Sous Windows, `<script>.exe` (lanceur de pip/distlib qui exécute le script avec ce Python) ;
    ailleurs, le script lui-même (exécutable grâce à sa ligne `#!`)."""
    if sys.platform != "win32":
        return script
    from pip._vendor.distlib.scripts import ScriptMaker

    target = Path(tempfile.mkdtemp(prefix="nexus-faux-"))
    maker = ScriptMaker(str(Path(script).parent), str(target), add_launchers=True)
    maker.executable = sys.executable
    made = maker.make(Path(script).name)
    return next(p for p in made if p.lower().endswith(".exe"))
