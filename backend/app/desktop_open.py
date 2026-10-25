"""Ouvrir une autre app de la suite, un fichier ou une adresse depuis l'application de bureau.

Contrat docs/apps/windows.md (SUITE.md §9.4) : l'app ouverte ne reçoit **aucune** variable de
Nexus (`DATABASE_URL` de sa base SQLite, `NEXUS_*`, `FRONTEND_DIST`, clés…), seulement un
environnement minimal (`app.core.processes.minimal_environment`). Sans cela, une app comme
Atelier Projets ouverte depuis le menu « Suite Atelier » reçoit la base de Nexus et échoue.

- macOS : `open -b <identifiant>` (apps), `open` (adresses, fichiers ; `-e` : éditeur de texte).
- Windows : lanceur enregistré dans `HKCU\\Software\\Atelier\\Apps\\<app>` (valeur `Lanceur`),
  sinon le navigateur par défaut ; adresses par `rundll32 url.dll,FileProtocolHandler`, dossiers
  par l'Explorateur, fichiers texte par le Bloc-notes.
- Linux : `xdg-open`.

`webbrowser` n'est jamais utilisé tel quel : il hérite de l'environnement de l'app (`open`
sous macOS, `os.startfile` sous Windows, `xdg-open` sous Linux). `CleanBrowser` le remplace
pour pywebview (liens externes de la fenêtre).

Bibliothèque standard uniquement.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from app.core.processes import NO_WINDOW, minimal_environment

#: Clé du registre (HKCU) où chaque app de la suite installée sous Windows s'enregistre
REGISTRY_KEY = r"Software\Atelier\Apps"


def _start(cmd: Sequence[str]) -> bool:
    """Lance sans attendre, environnement minimal ; False si le programme est introuvable."""
    try:
        subprocess.Popen(
            list(cmd),
            env=minimal_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return True


def _run(cmd: Sequence[str]) -> bool:
    """Lance et attend (`open -b` répond aussitôt) ; vrai si le code de retour est 0."""
    try:
        done = subprocess.run(
            list(cmd),
            env=minimal_environment(),
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _system_dir() -> Path:
    return Path(os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows")


# ─── Windows : apps enregistrées ──────────────────────────────────


def registry_launcher(app: str) -> Path | None:
    """Lanceur d'une app de la suite enregistré sous Windows (`Lanceur`), s'il existe."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{REGISTRY_KEY}\{app}") as key:
            value, _ = winreg.QueryValueEx(key, "Lanceur")
    except OSError:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip().strip('"'))
    return path if path.is_absolute() and path.is_file() else None


def launcher_command(launcher: Path, system_dir: Path | None = None) -> list[str]:
    """Commande qui démarre le lanceur inscrit d'une app (SUITE.md §9.6) : **toujours** par le
    shell, `explorer.exe "<Lanceur>"` (le `.lnk` du menu Démarrer). L'Explorateur démarre l'app
    avec l'environnement de la session ; jamais d'exécution directe du chemin."""
    return [str((system_dir or _system_dir()) / "explorer.exe"), str(launcher)]


def open_windows_app(
    app: str,
    *,
    lookup: Callable[[str], Path | None] | None = None,
    start: Callable[[Sequence[str]], bool] | None = None,
) -> bool:
    """Démarre le lanceur enregistré d'une app ; False si elle n'est pas installée."""
    launcher = (lookup or registry_launcher)(app)
    if launcher is None:
        return False
    return (start or _start)(launcher_command(launcher))


# ─── Par système ──────────────────────────────────────────────────

#: Identifiant macOS de chaque app de la suite (clé = nom court, comme sous Windows)
MACOS_BUNDLES = {
    "viz": "fr.atelier-viz.app",
    "tab": "fr.atelier.tab",
    "projets": "local.atelier-projets.desktop",
    "nexus": "fr.atelier-nexus.app",
    "tresorerie": "local.atelier-tresorerie.desktop",
    "cine": "fr.ateliercine.app",
    "savoir": "fr.ateliersavoir.app",
    "cuisine": "fr.ateliercuisine.app",
    "convert": "fr.atelier-convert.app",
}


def open_suite_app(app: str) -> bool:
    """Ouvre l'app de la suite `app` (« viz », « tab »…) si elle est installée ; sinon False."""
    if sys.platform == "darwin":
        bundle = MACOS_BUNDLES.get(app)
        return bool(bundle) and _run(["/usr/bin/open", "-b", str(bundle)])
    if sys.platform == "win32":
        return open_windows_app(app)
    return False


def open_url(url: str) -> bool:
    """Adresse dans le navigateur par défaut, avec un environnement minimal."""
    url = str(url)
    if urlsplit(url).scheme not in {"http", "https", "mailto"} or any(
        c.isspace() or c in '"<>' for c in url
    ):
        return False
    if sys.platform == "darwin":
        return _run(["/usr/bin/open", url])
    if sys.platform == "win32":
        rundll = _system_dir() / "System32" / "rundll32.exe"
        return _start([str(rundll), "url.dll,FileProtocolHandler", url])
    return _start(["xdg-open", url])


def reveal(path: Path, *, text_editor: bool = False) -> bool:
    """Fichier dans l'éditeur de texte (`text_editor`), ou dossier dans le Finder /
    l'Explorateur, avec un environnement minimal."""
    if sys.platform == "darwin":
        return _run(["/usr/bin/open", *(["-e"] if text_editor else []), str(path)])
    if sys.platform == "win32":
        root = _system_dir()
        tool = root / "System32" / "notepad.exe" if text_editor else root / "explorer.exe"
        return _start([str(tool), str(path)])
    return _start(["xdg-open", str(path)])


class CleanBrowser(webbrowser.BaseBrowser):
    """Navigateur de `webbrowser` (liens externes ouverts par pywebview) sans l'environnement
    de l'app."""

    def __init__(self, opener: Callable[[str], bool] = open_url) -> None:
        super().__init__("atelier-propre")
        self._opener = opener

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        return self._opener(url)


def install_clean_browser(opener: Callable[[str], bool] = open_url) -> None:
    """Fait de `CleanBrowser` le navigateur par défaut de `webbrowser` pour ce processus."""
    webbrowser.register("atelier-propre", None, CleanBrowser(opener), preferred=True)
