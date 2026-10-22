"""Point d'entrée du raccourci « Atelier Nexus » sous Windows (docs/apps/windows.md).

Copié par scripts/windows/install.ps1 dans %LOCALAPPDATA%\\Atelier Nexus\\lanceur\\, à côté du
fichier `repo-path` (chemin du dépôt). Le raccourci l'exécute sans console :
    "<Python du système>\\pythonw.exe" -I "%LOCALAPPDATA%\\Atelier Nexus\\lanceur\\atelier-nexus.pyw"
Il lance backend/app/desktop_launcher.py **du dépôt** : le code exécuté est toujours celui du
dépôt, après un git pull rouvrir l'app suffit (équivalent de scripts/macos/app_entry.sh).
Bibliothèque standard uniquement.
"""

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "Atelier Nexus"


def alert(message: str) -> None:
    """Boîte de message (pythonw n'a pas de console), sinon la sortie d'erreur."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10 | 0x10000)
    except Exception:  # noqa: BLE001 — hors Windows
        print(f"{APP_NAME} : {message}", file=sys.stderr)


def main() -> int:
    repo = os.environ.get("NEXUS_REPO", "").strip()
    if not repo:
        try:
            repo = (HERE / "repo-path").read_text(encoding="utf-8-sig").strip()
        except OSError:
            repo = ""
    launcher = Path(repo) / "backend" / "app" / "desktop_launcher.py" if repo else None
    if launcher is None or not launcher.is_file():
        alert(
            f"Le dépôt d'Atelier Nexus est introuvable ({repo or 'chemin non enregistré'}). "
            "S'il a été déplacé, relancez depuis son nouvel emplacement :\n"
            r"powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1"
        )
        return 1
    os.environ["NEXUS_REPO"] = repo
    sys.argv = [str(launcher), *sys.argv[1:]]
    runpy.run_path(str(launcher), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
