"""Ouvrir une autre app de la suite, une adresse ou un fichier avec un environnement propre
(docs/apps/windows.md, SUITE.md §9.4) — sous-processus simulés, sur chaque système.

Défaut corrigé : Atelier Projets, ouvert depuis le menu « Suite Atelier » de Nexus, recevait
le `DATABASE_URL` de Nexus (base SQLite) et sa mise à jour échouait.
"""

import os
import subprocess
import sys
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import pytest

from app import desktop, desktop_open
from app.core import processes

#: Variables de Nexus et de son lanceur qui ne doivent jamais passer à une autre app
LEAKY = {
    "DATABASE_URL": "sqlite+aiosqlite:////Users/u/Library/Application Support/Atelier Nexus/nexus.db",
    "NEXUS_HOME": "/Users/u/Library/Application Support/Atelier Nexus",
    "NEXUS_LOG_DIR": "/Users/u/Library/Logs/Atelier Nexus",
    "NEXUS_REPO": "/Users/u/atelier_nexus",
    "FRONTEND_DIST": "/x/out",
    "DB_AUTO_MIGRATE": "true",
    "APP_ENV": "production",
    "TAB_MCP_COMMAND": "/Applications/Atelier_Tab.app/Contents/Resources/atelier-mcp",
    "ANTHROPIC_API_KEY": "sk-secret",
    "PORT": "8100",
    "PYTHONPATH": "/x",
    "PYTHONHOME": "/x",
    "VIRTUAL_ENV": "/x/venv",
    "ATELIER_TAB_DATA": "/x",
    "ELECTRON_RUN_AS_NODE": "1",
}
KEPT = {
    "HOME": "/Users/u",
    "USER": "u",
    "LANG": "fr_FR.UTF-8",
    "LC_CTYPE": "UTF-8",
    "TZ": "Europe/Paris",
}


@pytest.fixture
def leaky_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {**LEAKY, **KEPT}.items():
        monkeypatch.setenv(key, value)


class Recorder:
    """Remplace subprocess.run / Popen : garde la commande et l'environnement."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.returncode = returncode

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((list(cmd), dict(kwargs["env"])))
        return subprocess.CompletedProcess(cmd, self.returncode, b"", b"")


def assert_clean(env: dict[str, str]) -> None:
    leaked = {k for k in env if k.upper() in LEAKY or k.upper().startswith("NEXUS_")}
    assert not leaked, f"variables transmises : {sorted(leaked)}"


# ─── Environnement minimal ────────────────────────────────────────


def test_minimal_environment_posix() -> None:
    source = {**LEAKY, **KEPT, "PATH": "/x/venv/bin:/opt/homebrew/bin:/usr/bin"}
    env = processes.minimal_environment(source, platform="darwin")
    assert_clean(env)
    assert {k: env[k] for k in KEPT} == KEPT
    assert env["PATH"] == processes.MACOS_PATH  # celui d'une app ouverte depuis le Finder
    linux = processes.minimal_environment({**source, "DISPLAY": ":0"}, platform="linux")
    assert linux["DISPLAY"] == ":0" and linux["PATH"] == processes.LINUX_PATH


def test_minimal_environment_windows() -> None:
    source = {
        **{k.upper(): v for k, v in LEAKY.items()},
        "USERPROFILE": r"C:\Users\François",
        "USERNAME": "François",
        "APPDATA": r"C:\Users\François\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\François\AppData\Local",
        "SystemRoot": r"C:\Windows",
        "COMSPEC": r"C:\Windows\system32\cmd.exe",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "ProgramFiles": r"C:\Program Files",
        "TEMP": r"C:\Temp",
        "PATH": r"C:\Users\François\AppData\Local\Atelier Nexus\venv\Scripts;C:\Windows",
    }
    registry = [
        r"%SystemRoot%\system32;%SystemRoot%;C:\Program Files\nodejs\;",
        r"%USERPROFILE%\.local\bin",
    ]
    env = processes.minimal_environment(source, platform="win32", registry=lambda: registry)
    assert_clean(env)
    for key in ("USERPROFILE", "USERNAME", "APPDATA", "LOCALAPPDATA", "SystemRoot", "COMSPEC"):
        assert env[key] == source[key]  # noms insensibles à la casse sous Windows
    # PATH du registre (machine + utilisateur), développé : sans le venv de l'app
    assert env["PATH"] == (
        r"C:\Windows\system32;C:\Windows;C:\Program Files\nodejs\;C:\Users\François\.local\bin"
    )
    fallback = processes.minimal_environment(source, platform="win32", registry=lambda: [])
    assert fallback["PATH"].startswith(r"C:\Windows\System32;C:\Windows")


def test_registry_path_is_read_on_windows() -> None:
    if sys.platform != "win32":
        assert processes.windows_registry_path() == []
        return
    path = processes.system_path()
    assert "system32" in path.lower()


# ─── macOS : open -b ──────────────────────────────────────────────


def test_open_suite_app_macos_clean_env(leaky_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le défaut de ce matin : `open -b` héritait de DATABASE_URL."""
    run = Recorder()
    monkeypatch.setattr(desktop_open.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert desktop_open.open_suite_app("projets") is True
    cmd, env = run.calls[0]
    assert cmd == ["/usr/bin/open", "-b", "local.atelier-projets.desktop"]
    assert_clean(env)
    assert env["HOME"] == "/Users/u" and env["LANG"] == "fr_FR.UTF-8"

    # Par le pont JavaScript, comme le menu « Suite Atelier »
    api = desktop.DesktopApi(open_url=lambda url: pytest.fail(f"navigateur : {url}"))
    assert api.open_external("http://127.0.0.1:4174/") is True
    assert run.calls[1][0][-1] == "local.atelier-projets.desktop"
    assert_clean(run.calls[1][1])

    assert desktop_open.open_suite_app("convert") is True
    assert run.calls[2][0] == ["/usr/bin/open", "-b", "fr.atelier-convert.app"]
    assert_clean(run.calls[2][1])

    run.returncode = 1  # app absente : False, le navigateur prend le relais
    assert desktop_open.open_suite_app("viz") is False
    assert desktop_open.open_suite_app("inconnue") is False


def test_open_url_and_reveal_macos(leaky_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Recorder()
    monkeypatch.setattr(desktop_open.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert desktop_open.open_url("https://atelier-cuisine-iota.vercel.app") is True
    assert desktop_open.reveal(Path("/x/.env"), text_editor=True) is True
    assert desktop_open.reveal(Path("/x")) is True
    assert [c for c, _ in run.calls] == [
        ["/usr/bin/open", "https://atelier-cuisine-iota.vercel.app"],
        ["/usr/bin/open", "-e", str(Path("/x/.env"))],
        ["/usr/bin/open", str(Path("/x"))],
    ]
    for _, env in run.calls:
        assert_clean(env)
    # Jamais autre chose qu'une adresse web, ni de caractère qui sortirait de l'argument
    assert desktop_open.open_url("file:///etc/passwd") is False
    assert desktop_open.open_url('https://x.test/" & calc') is False
    assert len(run.calls) == 3


# ─── Windows : registre, navigateur, Explorateur ──────────────────


def test_launcher_always_opened_by_explorer() -> None:
    """§9.6 : toujours `explorer.exe "<Lanceur>"`, jamais l'exécution directe du chemin."""
    root = Path("C:/Windows")
    for name in ("Atelier Viz.lnk", "Atelier Tab.exe", "lanceur.vbs", "lancer.cmd", "x.ps1"):
        launcher = Path("C:/Users/François/AppData/Roaming/Microsoft/Windows/Start Menu") / name
        assert desktop_open.launcher_command(launcher, root) == [
            str(root / "explorer.exe"),
            str(launcher),
        ]


def test_open_windows_app_reads_registry_then_browser(
    leaky_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    popen = Recorder()
    monkeypatch.setattr(desktop_open.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(desktop_open, "registry_launcher", lambda app: None)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")

    api = desktop.DesktopApi()  # valeurs par défaut : registre puis navigateur
    assert api.open_external("http://127.0.0.1:4174/") is True
    cmd, env = popen.calls[0]  # Projets non enregistré : adresse dans le navigateur
    assert cmd[1:] == ["url.dll,FileProtocolHandler", "http://127.0.0.1:4174/"]
    assert cmd[0].lower().endswith("rundll32.exe")
    assert_clean(env)

    launcher = tmp_path / "Atelier Projets.lnk"
    launcher.write_text("")
    looked: list[str] = []

    def lookup(app: str) -> Path | None:
        looked.append(app)
        return launcher

    monkeypatch.setattr(desktop_open, "registry_launcher", lookup)
    assert api.open_external("http://127.0.0.1:4174/") is True
    cmd, env = popen.calls[1]
    assert looked == ["projets"] and cmd[-1] == str(launcher) and cmd[0].endswith("explorer.exe")
    assert len(cmd) == 2
    assert_clean(env)

    assert desktop_open.reveal(tmp_path / ".env", text_editor=True) is True
    assert popen.calls[2][0][0].endswith("notepad.exe")
    assert_clean(popen.calls[2][1])


@pytest.mark.skipif(sys.platform != "win32", reason="registre de Windows")
def test_registry_launcher_on_windows(tmp_path: Path) -> None:
    import winreg

    app = f"test-nexus-{uuid.uuid4().hex[:8]}"
    key_path = rf"{desktop_open.REGISTRY_KEY}\{app}"
    launcher = tmp_path / "Atelier Test.lnk"
    launcher.write_text("")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "Lanceur", 0, winreg.REG_SZ, str(launcher))
        winreg.SetValueEx(key, "Nom", 0, winreg.REG_SZ, "Atelier Test")
    try:
        assert desktop_open.registry_launcher(app) == launcher
        launcher.unlink()
        assert desktop_open.registry_launcher(app) is None  # lanceur disparu : navigateur
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    assert desktop_open.registry_launcher(app) is None


# ─── webbrowser (liens ouverts par pywebview) ─────────────────────


def test_clean_browser_replaces_webbrowser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "_tryorder", list(getattr(webbrowser, "_tryorder", None) or []))
    monkeypatch.setattr(webbrowser, "_browsers", dict(getattr(webbrowser, "_browsers", {})))
    desktop_open.install_clean_browser(lambda url: opened.append(url) or True)
    assert webbrowser.open("https://example.org") is True
    assert opened == ["https://example.org"]


# ─── Au lancement de Nexus : variables héritées ignorées ──────────


def test_inherited_database_url_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nexus ouvert par une autre app (ou un terminal) avec la base de cette autre app."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "file:/Users/u/atelier_projets/backend/prisma/dev.db")
    monkeypatch.setenv("FRONTEND_DIST", "/ailleurs/out")
    monkeypatch.delenv("TAB_MCP_COMMAND", raising=False)
    home = tmp_path / "home"
    desktop.prepare_home(home)
    desktop.configure_environment(home, None, tab_mcp=tmp_path / "absent")
    assert os.environ["DATABASE_URL"] == f"sqlite+aiosqlite:///{home / 'nexus.db'}"
    assert "FRONTEND_DIST" not in os.environ


def test_tab_mcp_default_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    assert desktop.tab_mcp_default("darwin") == desktop.TAB_MCP_APP
    monkeypatch.setenv("LOCALAPPDATA", str(Path("C:/Users/François/AppData/Local")))
    expected = Path(
        "C:/Users/François/AppData/Local/Programs/Atelier_Tab/resources/atelier-mcp.cmd"
    )
    assert desktop.tab_mcp_default("win32") == expected
