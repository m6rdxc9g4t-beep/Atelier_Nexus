"""Application de bureau : le serveur Nexus et son interface dans une fenêtre native.

Lancée par « Atelier Nexus.app » (scripts/macos/launcher.sh, avec --mise-a-jour), par le
raccourci « Atelier Nexus » de Windows (app/desktop_launcher.py, docs/apps/windows.md), ou à la
main :
    python desktop.py               # fenêtre native (pywebview), sinon navigateur
    python desktop.py --navigateur  # dans le navigateur par défaut
    python desktop.py --preparer    # met l'interface à jour depuis le dépôt, sans rien ouvrir

- Mise à jour au lancement (`--mise-a-jour`, docs/apps/mise-a-jour-bureau.md) : si le dépôt a
  changé depuis la dernière compilation, écran « Mise à jour… » (npm ci, compilation : voir
  app/desktop_update.py), puis l'interface. En cas d'échec, ouverture possible avec la
  compilation précédente.

- Données et réglages dans le dossier de l'utilisateur (`NEXUS_HOME`, par défaut
  ~/Library/Application Support/Atelier Nexus, sous Windows %APPDATA%\\Atelier Nexus) : `.env`
  (créé au premier lancement à partir de `.env.example`), base SQLite `nexus.db`, cache de la
  fenêtre. Rien dans l'application. Une variable héritée qui désignerait d'autres données
  (`DATABASE_URL`, `FRONTEND_DIST`) est ignorée.
- Le serveur écoute sur 127.0.0.1 uniquement, port 8100 s'il est libre, sinon un port libre :
  l'interface est compilée avec des adresses relatives et fonctionne sur n'importe quel port.
- Fermer la fenêtre (ou ⌘Q) arrête le serveur.
- Pont JavaScript (`window.pywebview.api`) : « Enregistrer sous » natif pour les artefacts et
  ouverture des liens externes (une autre app de la suite s'ouvre si elle est installée, avec
  un environnement minimal : app/desktop_open.py).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import html
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.desktop_open import (
    MACOS_BUNDLES,
    install_clean_browser,
    open_suite_app,
    open_url,
)
from app.desktop_open import reveal as open_path
from app.desktop_update import (
    LABELS,
    LOG_NAME,
    Layout,
    UpdateError,
    display_path,
    log_dir,
    nexus_home,
    nexus_local,
    pending_steps,
    served_build,
    update_interface,
    utf8_output,
)

APP_NAME = "Atelier Nexus"
HOST = "127.0.0.1"
PREFERRED_PORT = 8100
WINDOW_SIZE = (1440, 900)
MIN_SIZE = (960, 620)
BACKEND = Path(__file__).resolve().parents[1]
APP_LOG_NAME = "atelier-nexus.log"
#: Icône de la fenêtre et des raccourcis sous Windows (générée depuis scripts/macos/icon.png)
WINDOWS_ICON = BACKEND.parent / "scripts" / "windows" / "AtelierNexus.ico"
#: Identifiant de l'app pour la barre des tâches de Windows (regroupement, épinglage)
WINDOWS_APP_ID = "Atelier.Nexus"
# Fond de la fenêtre avant l'affichage de l'interface : --atelier-bg de la charte néon dans
# l'orange de Nexus (frontend/src/components/theme/theme-constants.ts, THEME_COLORS).
WINDOW_BACKGROUND = {"light": "#fbf3f2", "dark": "#120c0d"}

log = logging.getLogger("atelier_nexus.desktop")

# Requêtes vers le serveur local sans proxy (macOS appliquerait sinon le proxy système).
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ─── Dossiers et réglages ─────────────────────────────────────────


def interface_dir(served: Path | None = None) -> Path | None:
    """Interface compilée : `NEXUS_FRONTEND_DIST`, sinon la compilation servie par l'app
    (`served`, voir app/desktop_update.py), sinon `frontend/out` à côté du backend."""
    for candidate in (
        os.environ.get("NEXUS_FRONTEND_DIST"),
        served,
        BACKEND.parent / "frontend" / "out",
    ):
        if candidate and (Path(candidate) / "index.html").is_file():
            return Path(candidate)
    return None


DESKTOP_DEFAULTS = """
# ─── Application de bureau ───────────────────────────────────────
# Base locale SQLite dans ce dossier (fixée par l'application, ne pas modifier ici).
# Clé Claude : ANTHROPIC_API_KEY ci-dessus. Sans clé, seuls les modèles locaux (Ollama) servent.
"""


def prepare_home(home: Path) -> Path:
    """Crée le dossier et son `.env` au premier lancement ; renvoie le chemin du `.env`."""
    home.mkdir(parents=True, exist_ok=True)
    env_file = home / ".env"
    if not env_file.exists():
        example = BACKEND / ".env.example"
        text = example.read_text(encoding="utf-8") if example.is_file() else ""
        # La base du docker-compose (PostgreSQL) n'a pas de sens ici : SQLite est imposée
        lines = [
            ("# " + line) if line.startswith("DATABASE_URL=") else line
            for line in text.splitlines()
        ]
        env_file.write_text("\n".join(lines) + "\n" + DESKTOP_DEFAULTS, encoding="utf-8")
        with contextlib.suppress(OSError):
            env_file.chmod(0o600)  # contiendra la clé API
    return env_file


TAB_MCP_APP = Path("/Applications/Atelier_Tab.app/Contents/Resources/atelier-mcp")


def tab_mcp_default(platform: str = sys.platform) -> Path:
    """Serveur MCP livré avec l'app Atelier Tab installée, selon le système (utilisé seulement
    s'il existe). Windows : emplacement par défaut d'une installation par utilisateur
    (`%LOCALAPPDATA%\\Programs\\Atelier_Tab\\resources\\atelier-mcp.cmd`, SUITE.md §9.6) ;
    sinon, réglage TAB_MCP_COMMAND du `.env`."""
    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "Programs" / "Atelier_Tab" / "resources" / "atelier-mcp.cmd"
    return TAB_MCP_APP


#: Variables héritées qui désigneraient d'autres données que celles de Nexus (SUITE.md §9.4) :
#: jamais lues au lancement de l'app de bureau (ex. la base d'Atelier Projets)
INHERITED_DATA_VARS = ("DATABASE_URL", "FRONTEND_DIST")


def env_value(env_file: Path, key: str) -> str | None:
    """Valeur non vide d'une clé du `.env` (lecture simple, sans interprétation)."""
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() == key and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def configure_environment(home: Path, dist: Path | None, tab_mcp: Path | None = None) -> None:
    """Variables lues par `Settings` : à poser AVANT d'importer `main` (réglages mis en cache)."""
    tab_mcp = tab_mcp_default() if tab_mcp is None else tab_mcp
    for name in INHERITED_DATA_VARS:
        if os.environ.pop(name, None) is not None:
            log.info("Variable héritée ignorée : %s", name)
    # Atelier Tab installé : écriture par son serveur MCP sans réglage, sauf choix contraire du .env
    if (
        tab_mcp.is_file()
        and "TAB_MCP_COMMAND" not in os.environ
        and env_value(home / ".env", "TAB_MCP_COMMAND") is None
    ):
        os.environ["TAB_MCP_COMMAND"] = str(tab_mcp)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{home / 'nexus.db'}"
    os.environ["DB_AUTO_MIGRATE"] = "true"
    os.environ.setdefault("APP_ENV", "production")
    if dist is not None:
        os.environ["FRONTEND_DIST"] = str(dist)
    # `.env` lu dans le dossier courant (SettingsConfigDict(env_file=".env"))
    os.chdir(home)


# ─── Serveur ──────────────────────────────────────────────────────


def port_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
        return True


def find_port(preferred: int = PREFERRED_PORT, host: str = HOST) -> int:
    """Le port préféré s'il est libre, sinon un port libre choisi par le système."""
    if preferred > 0 and port_free(preferred, host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        port: int = s.getsockname()[1]
        return port


def probe(base_url: str, timeout: float = 0.6) -> bool:
    """Vrai si un serveur Nexus répond sur `/api/health`."""
    try:
        with _local.open(f"{base_url}/api/health", timeout=timeout) as r:  # noqa: S310 — local
            data = json.loads(r.read())
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(data, dict) and data.get("status") == "ok"


class ServerThread:
    """Uvicorn dans un fil d'exécution, arrêté proprement."""

    def __init__(self, app: Any, port: int, host: str = HOST) -> None:
        import uvicorn

        self.url = f"http://{host}:{port}"
        self.server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
        )
        self.thread = threading.Thread(target=self._run, name="nexus-server", daemon=True)
        self.error: BaseException | None = None

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:  # noqa: BLE001 — remonté à start()
            self.error = exc

    def start(self, timeout: float = 60.0) -> None:
        """Démarre et attend que l'API réponde (migrations comprises) ; RuntimeError sinon."""
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started and probe(self.url):
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        self.stop()
        reason = f" : {self.error}" if self.error else ""
        raise RuntimeError(f"Le serveur local n'a pas démarré{reason}.")

    def stop(self, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout)


def reinstall_hint() -> str:
    """Commande d'installation à relancer (réparation), selon le système."""
    if sys.platform == "win32":
        return r"powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1"
    return "scripts/macos/build_app.sh"


def start_server(dist: Path | None) -> tuple[str, ServerThread | None, str | None]:
    """(adresse, serveur, message d'erreur éventuel). Réglages et dossiers déjà préparés."""
    if dist is None:
        return "", None, f"Interface introuvable : relancez {reinstall_hint()} depuis le dépôt."
    from main import app

    server = ServerThread(app, find_port())
    try:
        server.start()
    except RuntimeError as exc:
        return "", None, str(exc)
    log.info("Serveur démarré sur %s", server.url)
    return server.url, server, None


# ─── Pont JavaScript ──────────────────────────────────────────────

#: Port de l'interface d'une app de la suite → nom court de l'app (« viz », « tab »… :
#: clé du registre Windows et de MACOS_BUNDLES)
SUITE_APPS = {
    8000: "viz",
    4175: "tab",
    4174: "projets",
    5050: "tresorerie",
    4000: "cine",
    47321: "cine",
    5051: "savoir",
    8010: "convert",  # Atelier Convert : API et interface d'aperçu sur le même port
}
#: Apps en ligne de la suite (adresse HTTPS hébergée) → app de bureau qui l'enveloppe
SUITE_ONLINE_APPS = {
    "atelier-cuisine-iota.vercel.app": "cuisine",  # Atelier Cuisine (Tauri)
}
#: Port → identifiant de l'application macOS (compatibilité)
SUITE_BUNDLES = {port: MACOS_BUNDLES[app] for port, app in SUITE_APPS.items()}
SUITE_ONLINE_BUNDLES = {host: MACOS_BUNDLES[app] for host, app in SUITE_ONLINE_APPS.items()}
_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def suite_app_for(url: str) -> str | None:
    """App de la suite à ouvrir pour une adresse (locale, ou en ligne connue en HTTPS sur le
    port par défaut) : son nom court, sinon None."""
    try:
        parts = urlsplit(str(url))
        port = parts.port
    except ValueError:
        return None
    if parts.scheme == "https" and port is None and parts.hostname in SUITE_ONLINE_APPS:
        return SUITE_ONLINE_APPS[parts.hostname]
    if parts.scheme not in {"http", "https"} or parts.hostname not in _LOCAL_HOSTS or port is None:
        return None
    return SUITE_APPS.get(port)


def suite_bundle_for(url: str) -> str | None:
    """Identifiant de l'application macOS à ouvrir pour une adresse de la suite, sinon None."""
    app = suite_app_for(url)
    return MACOS_BUNDLES.get(app) if app else None


class DesktopApi:
    """Fonctions appelables depuis la page : `window.pywebview.api.<nom>(...)`."""

    def __init__(
        self,
        open_url: Callable[[str], Any] = open_url,
        open_app: Callable[[str], bool] = open_suite_app,
    ) -> None:
        self.window: Any = None
        self.save_dialog: Any = None  # webview.FileDialog.SAVE, renseigné au lancement
        self._open_url = open_url
        self._open_app = open_app
        # Après une mise à jour échouée : ouvre l'app avec la compilation précédente
        self._open_previous: Callable[[], None] | None = None

    def save_file(self, name: str, data_base64: str) -> dict[str, Any]:
        """Boîte « Enregistrer sous » puis écriture ; {"saved": chemin | None}."""
        if self.window is None:
            return {"saved": None, "error": "Fenêtre indisponible."}
        safe = Path(str(name)).name or "artefact.txt"
        try:
            content = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            return {"saved": None, "error": "Contenu du fichier invalide."}
        result = self.window.create_file_dialog(
            self.save_dialog, directory=str(Path.home() / "Downloads"), save_filename=safe
        )
        if not result:
            return {"saved": None}
        target = Path(result if isinstance(result, str) else result[0])
        try:
            target.write_bytes(content)
        except OSError as exc:
            return {"saved": None, "error": f"Écriture impossible : {exc}"}
        return {"saved": str(target)}

    def open_external(self, url: str) -> bool:
        """Lien http(s) ou mailto dans le navigateur ; une app de la suite s'ouvre si installée
        (environnement minimal dans les deux cas : app/desktop_open.py)."""
        if urlsplit(str(url)).scheme not in {"http", "https", "mailto"}:
            return False
        app = suite_app_for(url)
        if app and self._open_app(app):
            return True
        self._open_url(str(url))
        return True

    def open_previous(self) -> bool:
        """Bouton « Ouvrir quand même avec la version précédente » de la page d'échec."""
        action, self._open_previous = self._open_previous, None  # une seule fois
        if action is None:
            return False
        action()
        return True

    def quit_app(self) -> None:
        """Bouton « Quitter » de la page d'échec."""
        if self.window is not None:
            self.window.destroy()


# ─── Lancement ────────────────────────────────────────────────────


def system_appearance() -> str:
    """« dark » si le système est en apparence sombre (macOS, Windows), sinon « light »."""
    if sys.platform == "win32":
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                light, _ = winreg.QueryValueEx(handle, "AppsUseLightTheme")
        except OSError:
            return "light"
        return "dark" if light == 0 else "light"
    if sys.platform != "darwin":
        return "light"
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "light"
    return "dark" if "dark" in result.stdout.lower() else "light"


# Page d'erreur aux couleurs de la charte (jetons --atelier-* calculés pour l'orange de Nexus).
_ERROR_CSS = (
    ":root{color-scheme:light dark;--bg:#fbf3f2;--text:#33221f;--muted:#766263;--ink:#7f3a20}"
    "@media (prefers-color-scheme:dark){:root{--bg:#120c0d;--text:#f7eeec;--muted:#b69a97;"
    "--ink:#f07b4c}}"
    "body{font:15px -apple-system,system-ui,sans-serif;display:grid;place-items:center;"
    "height:90vh;margin:0;background:var(--bg);color:var(--text)}"
    "h1{font-size:18px;color:var(--ink)}.hint{color:var(--muted);font-size:13px}"
)


def log_hint() -> str:
    return f"Journal : {display_path(log_dir() / APP_LOG_NAME)}"


def error_page(message: str) -> str:
    return (
        f'<!doctype html><meta charset="utf-8"><title>{APP_NAME}</title>'
        f"<style>{_ERROR_CSS}</style>"
        f'<body><div style="max-width:34rem;padding:2rem">'
        f"<h1>{APP_NAME} ne peut pas démarrer</h1>"
        f"<p>{html.escape(message)}</p>"
        f'<p class="hint">{html.escape(log_hint())}</p></div>'
    )


_SPLASH_CSS = (
    "main{text-align:center}h1{letter-spacing:.04em;margin:18px 0 6px}"
    ".ring{width:34px;height:34px;margin:0 auto;border-radius:50%;"
    "border:3px solid color-mix(in srgb,var(--muted) 35%,transparent);border-top-color:var(--ink);"
    "animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}"
    "button{font:inherit;padding:.5rem .9rem;border-radius:8px;margin:.3rem;cursor:pointer;"
    "border:1px solid var(--ink);background:transparent;color:var(--text)}"
    "button.primary{background:var(--ink);color:var(--bg)}"
)
_UPDATE_HINT = "Première ouverture ou mise à jour du dépôt : cela peut prendre quelques minutes."


def splash_page(status: str) -> str:
    """Écran de démarrage « Mise à jour… » ; `setStatus(texte)` change l'étape affichée."""
    return (
        f'<!doctype html><html lang="fr"><meta charset="utf-8"><title>{APP_NAME}</title>'
        f"<style>{_ERROR_CSS}{_SPLASH_CSS}</style>"
        '<body><main><div class="ring" aria-hidden="true"></div>'
        f"<h1>Mise à jour d'{APP_NAME}…</h1>"
        f'<p id="status" role="status">{html.escape(status)}</p>'
        f'<p class="hint">{html.escape(_UPDATE_HINT)}</p></main>'
        "<script>window.setStatus=function(t){document.getElementById('status').textContent=t}"
        "</script>"
    )


def update_failed_page(message: str, log_file: Path, previous: bool) -> str:
    """Échec de la mise à jour : message, journal, « Ouvrir quand même » si une version existe."""
    open_previous = (
        '<button class="primary" onclick="this.disabled=true;this.textContent=\'Ouverture…\';'
        'window.pywebview.api.open_previous()">'
        "Ouvrir quand même avec la version précédente</button>"
        if previous
        else ""
    )
    retry = (
        "La version précédente reste disponible ; le prochain lancement réessaiera la mise à jour."
        if previous
        else "Le prochain lancement réessaiera la mise à jour."
    )
    return (
        f'<!doctype html><html lang="fr"><meta charset="utf-8"><title>{APP_NAME}</title>'
        f"<style>{_ERROR_CSS}{_SPLASH_CSS}</style>"
        '<body><div style="max-width:36rem;padding:2rem">'
        f"<h1>La mise à jour d'{APP_NAME} a échoué</h1>"
        f"<p>{html.escape(message)}</p>"
        f"<p>{html.escape(retry)}</p>"
        f'<p class="hint">Journal : {html.escape(display_path(log_file))}</p>'
        f"<p>{open_previous}"
        '<button onclick="window.pywebview.api.quit_app()">Quitter</button></p></div>'
    )


def update_in_window(
    window: Any,
    layout: Layout,
    api: DesktopApi,
    open_app: Callable[[Path | None], None],
    update: Callable[..., list[str]] = update_interface,
) -> bool:
    """Fil de l'écran de démarrage : mise à jour, puis l'app ; sinon la page d'échec."""
    with contextlib.suppress(Exception):
        window.events.loaded.wait(10)

    def status(text: str) -> None:
        with contextlib.suppress(Exception):
            window.evaluate_js(f"setStatus({json.dumps(text)})")

    try:
        update(layout, on_status=status)
    except UpdateError as exc:
        message = str(exc)
    except Exception as exc:  # noqa: BLE001 — affiché plutôt qu'une fenêtre figée
        log.exception("Mise à jour interrompue")
        message = f"Erreur inattendue : {exc}"
    else:
        open_app(served_build(layout))
        return True
    log.error("Mise à jour échouée : %s", message)
    previous = served_build(layout)
    if previous is not None:
        api._open_previous = lambda: open_app(previous)
    window.load_html(update_failed_page(message, log_dir() / LOG_NAME, previous is not None))
    return False


def prepare_in_console(layout: Layout) -> int:
    """Mise à jour dans le terminal (`--preparer`, mode navigateur) ; 0 si l'interface est prête."""
    try:
        done = update_interface(layout, on_status=lambda text: print(text, flush=True))
    except UpdateError as exc:
        print(f"Erreur : {exc}\nJournal : {log_dir() / LOG_NAME}", file=sys.stderr)
        return 1
    print("Interface compilée." if done else "Interface déjà à jour.", flush=True)
    return 0


def versioned_url(url: str, dist: Path | None) -> str:
    """Adresse marquée de la date de compilation : une mise à jour n'est jamais masquée par le cache."""
    try:
        version = int((dist / "index.html").stat().st_mtime) if dist else 0
    except OSError:
        return url
    return f"{url.rstrip('/')}/?v={version}"


def reveal(path: Path, *, text_editor: bool = False) -> None:
    """Ouvre un fichier dans l'éditeur de texte (`text_editor`) ou un dossier dans le Finder
    (l'Explorateur sous Windows), avec un environnement minimal."""
    open_path(path, text_editor=text_editor)


#: Client Edge Update du moteur WebView2 (Evergreen) dans le registre
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_installed() -> bool:
    """Windows : vrai si le moteur WebView2 (requis par pywebview) est installé."""
    if sys.platform != "win32":
        return True
    import winreg

    places = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_WEBVIEW2_CLIENT}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\{_WEBVIEW2_CLIENT}"),
    )
    for root, key in places:
        try:
            with winreg.OpenKey(root, key) as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
        except OSError:
            continue
        if isinstance(version, str) and version not in {"", "0.0.0.0"}:
            return True
    return False


def _windows_app_identity() -> None:
    """Windows : identifiant propre dans la barre des tâches (sinon regroupé avec Python)."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)


def ensure_streams(log_file: Path) -> None:
    """Sans console (`pythonw.exe`), `sys.stdout` / `sys.stderr` valent None : uvicorn et la
    journalisation échoueraient. Ils sont alors dirigés vers le journal de l'app."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stream = log_file.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _name_macos_app() -> None:
    """« Atelier Nexus » dans la barre des menus (au lieu de « Python »)."""
    if sys.platform != "darwin":
        return
    with contextlib.suppress(Exception):
        from Foundation import NSBundle  # type: ignore[import-not-found]

        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME


def _interrupt(*_: object) -> None:
    raise KeyboardInterrupt


def _settings_menu(env_file: Path, home: Path) -> list[Any]:
    """Menu « Réglages » de la fenêtre (vide si pywebview ne gère pas les menus)."""
    with contextlib.suppress(Exception):
        from webview.menu import Menu, MenuAction  # type: ignore[import-not-found]

        return [
            Menu(
                "Réglages",
                [
                    MenuAction(
                        "Ouvrir le fichier de réglages (.env)…",
                        lambda: reveal(env_file, text_editor=True),
                    ),
                    MenuAction("Afficher le dossier des données", lambda: reveal(home)),
                ],
            )
        ]
    return []


def run(argv: list[str] | None = None) -> int:
    """Point d'entrée de l'application de bureau."""
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — application de bureau")
    parser.add_argument("--navigateur", action="store_true", help="ouvrir dans le navigateur")
    parser.add_argument(
        "--mise-a-jour",
        action="store_true",
        help="mettre l'interface à jour depuis le dépôt avant d'ouvrir (lanceur de l'app)",
    )
    parser.add_argument(
        "--preparer", action="store_true", help="mettre l'interface à jour puis quitter"
    )
    args = parser.parse_args(argv)
    ensure_streams(log_dir() / APP_LOG_NAME)
    utf8_output()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s"
    )
    # Liens ouverts par pywebview ou `webbrowser` : sans l'environnement de l'app (§9.4)
    install_clean_browser()

    home = nexus_home()
    env_file = prepare_home(home)
    layout = Layout(repo=BACKEND.parent, home=home, local=nexus_local())
    if args.preparer:
        return prepare_in_console(layout)
    steps = pending_steps(layout) if args.mise_a_jour else []
    pending = bool(steps)
    sys.path.insert(0, str(BACKEND))  # `main` et `app` importables hors du dossier courant

    webview: Any = None
    if not args.navigateur:
        _name_macos_app()
        _windows_app_identity()
        try:
            import webview  # type: ignore[import-not-found,no-redef]
        except ImportError:
            log.warning("pywebview absent : navigateur utilisé.")
        if webview is not None and sys.platform == "win32" and not webview2_installed():
            # Sans WebView2, pywebview prendrait le moteur d'Internet Explorer : interface cassée
            log.warning(
                "WebView2 absent : navigateur utilisé (winget install Microsoft.EdgeWebView2Runtime)."
            )
            webview = None

    servers: list[ServerThread] = []

    def serve(dist: Path | None) -> tuple[str, str | None]:
        """Démarre le serveur sur une compilation de l'interface : (adresse, erreur)."""
        configure_environment(home, dist)
        url, server, error = start_server(dist)
        if server is not None:
            servers.append(server)
        return url, error

    try:
        if webview is None:
            if pending and prepare_in_console(layout) != 0:
                if served_build(layout) is None:
                    return 1
                print("Ouverture avec la version précédente.", file=sys.stderr)
            dist = interface_dir(served_build(layout))
            url, error = serve(dist)
            if error:
                log.error(error)
                print(error, file=sys.stderr)
                return 1
            open_url(url)
            print(f"{APP_NAME} : {url} — Ctrl+C pour arrêter.")
            signal.signal(signal.SIGTERM, _interrupt)
            with contextlib.suppress(KeyboardInterrupt):
                while servers and servers[0].thread.is_alive():
                    time.sleep(0.5)
            return 0

        api = DesktopApi()
        api.save_dialog = webview.FileDialog.SAVE
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        url, error, dist = "", None, None
        if not pending:
            dist = interface_dir(served_build(layout))
            url, error = serve(dist)
        if pending:
            first_url, first_html = None, splash_page(LABELS[steps[0]])
        elif error:
            first_url, first_html = None, error_page(error)
        else:
            first_url, first_html = versioned_url(url, dist), None
        window = webview.create_window(
            APP_NAME,
            url=first_url,
            html=first_html,
            js_api=api,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=MIN_SIZE,
            text_select=True,
            zoomable=True,
            # Pas d'éclair blanc au lancement : fond du kit, clair ou sombre comme le système
            background_color=WINDOW_BACKGROUND[system_appearance()],
        )
        api.window = window

        def open_app(built: Path | None) -> None:
            """Après l'écran de démarrage : serveur puis interface (ou page d'erreur)."""
            target = interface_dir(built)
            app_url, app_error = serve(target)
            if app_error:
                window.load_html(error_page(app_error))
            else:
                window.load_url(versioned_url(app_url, target))

        storage = home / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        # Windows : icône de l'app sur la fenêtre et dans la barre des tâches
        windows: dict[str, Any] = {}
        if sys.platform == "win32" and WINDOWS_ICON.is_file():
            windows["icon"] = str(WINDOWS_ICON)
        # Stockage persistant : thème, dernière conversation de chaque agent…
        webview.start(
            (lambda: update_in_window(window, layout, api, open_app)) if pending else None,
            private_mode=False,
            storage_path=str(storage),
            menu=_settings_menu(env_file, home),
            **windows,
        )
        return 1 if error else 0
    finally:
        for server in servers:
            log.info("Arrêt du serveur.")
            server.stop()
