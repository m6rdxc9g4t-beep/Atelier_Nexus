"""Application de bureau (Étape 9) : dossier de l'utilisateur, réglages, pont JavaScript,
interface servie par le backend."""

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import desktop


def test_prepare_home_creates_private_env_once(tmp_path: Path) -> None:
    home = tmp_path / "Atelier Nexus"
    env_file = desktop.prepare_home(home)
    text = env_file.read_text()
    assert "\nDATABASE_URL=" not in text  # la base du docker-compose est neutralisée
    assert "ANTHROPIC_API_KEY=" in text and "Application de bureau" in text
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    env_file.write_text("ANTHROPIC_API_KEY=sk-test\n")
    desktop.prepare_home(home)
    assert env_file.read_text() == "ANTHROPIC_API_KEY=sk-test\n"  # jamais écrasé


def test_env_value(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('A=\n# B=1\nB = "x y"\nC=z\n')
    assert desktop.env_value(env, "A") is None
    assert desktop.env_value(env, "B") == "x y"
    assert desktop.env_value(tmp_path / "absent", "C") is None


def test_configure_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("DATABASE_URL", "FRONTEND_DIST", "TAB_MCP_COMMAND", "DB_AUTO_MIGRATE", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    desktop.prepare_home(home)
    mcp = tmp_path / "atelier-mcp"
    mcp.write_text("#!/bin/sh\n")
    dist = tmp_path / "out"

    desktop.configure_environment(home, dist, tab_mcp=mcp)
    assert os.environ["DATABASE_URL"] == f"sqlite+aiosqlite:///{home / 'nexus.db'}"
    assert os.environ["FRONTEND_DIST"] == str(dist)
    assert os.environ["TAB_MCP_COMMAND"] == str(mcp)  # Atelier Tab installé : écriture activée
    assert Path.cwd() == home  # .env lu dans le dossier de l'utilisateur

    # Une commande choisie dans le .env l'emporte sur la détection
    monkeypatch.delenv("TAB_MCP_COMMAND")
    (home / ".env").write_text("TAB_MCP_COMMAND=node /autre/atelier-mcp.mjs\n")
    desktop.configure_environment(home, None, tab_mcp=mcp)
    assert "TAB_MCP_COMMAND" not in os.environ


def test_suite_links_open_installed_apps() -> None:
    assert desktop.suite_bundle_for("http://127.0.0.1:8000/") == "fr.atelier-viz.app"
    assert desktop.suite_bundle_for("http://localhost:5051") == "fr.ateliersavoir.app"
    assert desktop.suite_bundle_for("https://example.org:8000") is None
    assert desktop.suite_bundle_for("http://127.0.0.1") is None

    opened: list[str] = []
    api = desktop.DesktopApi(open_url=opened.append, open_app=lambda b: b == "fr.atelier.tab")
    assert api.open_external("http://127.0.0.1:4175") and opened == []  # app Tab ouverte
    assert api.open_external("http://127.0.0.1:4000") and opened == ["http://127.0.0.1:4000"]
    assert api.open_external("file:///etc/passwd") is False


class FakeWindow:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def create_file_dialog(self, dialog_type: object, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.answer


def test_save_file(tmp_path: Path) -> None:
    target = tmp_path / "mesure.dax"
    api = desktop.DesktopApi()
    assert api.save_file("x", "")["error"] == "Fenêtre indisponible."
    api.window = FakeWindow([str(target)])
    data = base64.b64encode(b"CA Total = SUM(Ventes[Montant])").decode()
    assert api.save_file("../../mesure.dax", data) == {"saved": str(target)}
    assert target.read_text() == "CA Total = SUM(Ventes[Montant])"
    assert api.window.calls[0]["save_filename"] == "mesure.dax"  # chemin retiré du nom
    assert api.save_file("a.txt", "%%%")["error"] == "Contenu du fichier invalide."
    api.window = FakeWindow(None)
    assert api.save_file("a.txt", data) == {"saved": None}


def test_backend_serves_the_interface(tmp_path: Path) -> None:
    """Interface compilée servie à la racine, routes /api prioritaires (processus séparé :
    les réglages sont lus à l'import de main)."""
    dist = tmp_path / "out"
    dist.mkdir()
    (dist / "index.html").write_text('<!doctype html><div id="nexus">ok</div>')
    (dist / "404.html").write_text("introuvable")
    script = """
from fastapi.testclient import TestClient
from main import app
c = TestClient(app)
r = c.get("/")
assert r.status_code == 200 and 'id="nexus"' in r.text, r.text
assert c.get("/api/health").json()["status"] == "ok"
assert c.get("/api/agents").status_code == 200
assert c.get("/page-inconnue").status_code == 404
print("ok")
"""
    env = {**os.environ, "FRONTEND_DIST": str(dist), "DB_AUTO_MIGRATE": "false"}
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("ok")


def test_interface_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_FRONTEND_DIST", str(tmp_path))
    monkeypatch.setattr(desktop, "BACKEND", tmp_path / "backend")
    assert desktop.interface_dir() is None
    (tmp_path / "index.html").write_text("x")
    assert desktop.interface_dir() == tmp_path


def test_versioned_url(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x")
    assert desktop.versioned_url("http://127.0.0.1:8100", tmp_path).startswith(
        "http://127.0.0.1:8100/?v="
    )
    assert desktop.versioned_url("http://x", None) == "http://x/?v=0"


def test_window_matches_the_brand() -> None:
    """Fond de fenêtre et page d'erreur aux couleurs de la charte néon (orange de Nexus)."""
    constants = (
        Path(__file__).resolve().parents[2] / "frontend/src/components/theme/theme-constants.ts"
    ).read_text(encoding="utf-8")
    for theme, color in desktop.WINDOW_BACKGROUND.items():
        assert f'{theme}: "{color}"' in constants
    assert desktop.system_appearance() in desktop.WINDOW_BACKGROUND
    page = desktop.error_page("<port occupé>")
    assert "&lt;port occupé&gt;" in page
    assert desktop.WINDOW_BACKGROUND["light"] in page and desktop.WINDOW_BACKGROUND["dark"] in page
