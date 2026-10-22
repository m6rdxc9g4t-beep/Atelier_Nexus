"""Lanceur de l'app de bureau sous Windows (app/desktop_launcher.py) : environnement Python
avant la fenêtre, choix après un échec, fenêtre sans console, mode « mise à jour seulement »."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any, TypeVar

import pytest

from app import desktop_launcher as dl
from app import desktop_update as du

T = TypeVar("T")


class FakeUi:
    def __init__(self, previous: bool = False) -> None:
        self.previous = previous
        self.alerts: list[str] = []
        self.questions: list[str] = []
        self.busy_texts: list[str] = []

    def alert(self, message: str) -> None:
        self.alerts.append(message)

    def ask_previous(self, message: str) -> bool:
        self.questions.append(message)
        return self.previous

    def busy(self, text: str, work: Callable[[], T]) -> T:
        self.busy_texts.append(text)
        return work()


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> du.Layout:
    repo = tmp_path / "dépôt avec espaces"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "desktop.py").write_text("")
    (repo / "backend" / "app" / "desktop_update.py").write_text("")
    (repo / "backend" / "requirements.txt").write_text("fastapi\n")
    monkeypatch.setenv("NEXUS_LOG_DIR", str(tmp_path / "Logs"))
    return du.Layout(repo=repo, home=tmp_path / "Roaming", local=tmp_path / "Local")


class Calls:
    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.ran: list[list[str]] = []

    def spawn(self, cmd: Sequence[str], cwd: Path, log: IO[str]) -> None:
        assert cwd.name == "backend"
        self.spawned.append(list(cmd))

    def run(self, cmd: Sequence[str], cwd: Path) -> int:
        self.ran.append(list(cmd))
        return 0


def make_venv(layout: du.Layout) -> None:
    """Faux environnement, aux chemins de Windows et du système qui exécute les tests."""
    for platform in ("win32", "linux"):
        for windowed in (False, True):
            python = du.venv_python_path(layout.venv, platform, windowed=windowed)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("")


def launch(layout: du.Layout, ui: FakeUi, calls: Calls, *args: str, **kw: Any) -> int:
    return dl.launch(
        layout,
        list(args),
        ui=ui,
        base_python=Path("C:/Python313/pythonw.exe"),
        spawn=calls.spawn,
        run=calls.run,
        platform="win32",
        **kw,
    )


def test_installs_venv_then_opens_window_without_console(layout: du.Layout) -> None:
    ui, calls, installed = FakeUi(), Calls(), []

    def install(lay: du.Layout, python: Path) -> bool:
        installed.append(python)
        make_venv(lay)
        lay.venv_stamp.write_text(du.requirements_hash(lay.repo) + "\n")
        return True

    assert launch(layout, ui, calls, install=install) == 0
    assert ui.busy_texts == [du.LABELS["venv"]] and installed
    pythonw = du.venv_python_path(layout.venv, "win32", windowed=True)
    assert calls.spawned == [
        [str(pythonw), str(layout.repo / "backend" / "desktop.py"), "--mise-a-jour"]
    ]
    log = (Path(du.log_dir()) / dl.APP_LOG_NAME).read_text(encoding="utf-8")
    assert "lancement" in log and str(layout.repo) in log

    # Environnement à jour : la fenêtre s'ouvre directement
    ui = FakeUi()
    assert launch(layout, ui, calls, install=lambda *_: pytest.fail("refait")) == 0
    assert ui.busy_texts == [] and len(calls.spawned) == 2


def test_prepare_mode_runs_in_console(layout: du.Layout) -> None:
    make_venv(layout)
    layout.venv_stamp.write_text(du.requirements_hash(layout.repo) + "\n")
    calls = Calls()
    assert launch(layout, FakeUi(), calls, "--preparer") == 0
    python = du.venv_python_path(layout.venv, "win32")
    assert calls.ran == [
        [str(python), str(layout.repo / "backend" / "desktop.py"), "--mise-a-jour", "--preparer"]
    ]
    assert calls.spawned == []


def test_venv_failure(layout: du.Layout) -> None:
    def failing(lay: du.Layout, python: Path) -> bool:
        raise du.UpdateError(
            "L'installation des dépendances Python a échoué (connexion Internet ?)."
        )

    # Aucun environnement : message, rien n'est ouvert
    ui, calls = FakeUi(), Calls()
    assert launch(layout, ui, calls, install=failing) == du.EXIT_VENV_FAILED
    assert "a échoué" in ui.alerts[0] and du.LOG_NAME in ui.alerts[0] and calls.spawned == []

    # Environnement précédent remis en place : « Ouvrir quand même » ou quitter
    make_venv(layout)
    ui = FakeUi(previous=False)
    assert launch(layout, ui, calls, install=failing) == du.EXIT_VENV_RESTORED
    assert "précédent est conservé" in ui.questions[0] and calls.spawned == []
    ui = FakeUi(previous=True)
    assert launch(layout, ui, calls, install=failing) == 0
    assert len(calls.spawned) == 1


def test_incomplete_repo(layout: du.Layout) -> None:
    (layout.repo / "backend" / "desktop.py").unlink()
    ui = FakeUi()
    assert launch(layout, ui, Calls()) == 1
    assert "introuvable ou incomplet" in ui.alerts[0] and "install.ps1" in ui.alerts[0]


def test_console_ui(capsys: pytest.CaptureFixture[str]) -> None:
    ui = dl.ConsoleUi()
    assert ui.busy("Étape…", lambda: 42) == 42
    assert ui.ask_previous("Échec") is False
    out = capsys.readouterr()
    assert out.out == "Étape…\n" and "Atelier Nexus : Échec" in out.err


ENTRY = Path(__file__).resolve().parents[2] / "scripts" / "windows" / "app_entry.pyw"


def test_app_entry_runs_the_repo_launcher(tmp_path: Path) -> None:
    """Point d'entrée du raccourci (copié dans %LOCALAPPDATA%\\Atelier Nexus\\lanceur) : lance
    le lanceur du dépôt enregistré dans `repo-path` (BOM toléré), arguments transmis."""
    lanceur = tmp_path / "lanceur"
    lanceur.mkdir()
    shutil.copy(ENTRY, lanceur / "atelier-nexus.pyw")
    repo = tmp_path / "depot avec espaces"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "app" / "desktop_launcher.py").write_text(
        'import os, sys\nprint("lanceur", os.environ["NEXUS_REPO"], *sys.argv[1:])\n'
    )
    (lanceur / "repo-path").write_bytes(("﻿" + str(repo) + "\r\n").encode("utf-8"))
    env = {**os.environ, "NEXUS_REPO": ""}
    entry = [sys.executable, "-I", str(lanceur / "atelier-nexus.pyw")]
    done = subprocess.run(
        [*entry, "--preparer"], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f"lanceur {repo} --preparer"

    if sys.platform != "win32":  # sous Windows, une boîte de message bloquerait le test
        (lanceur / "repo-path").write_text(str(tmp_path / "deplace"))
        done = subprocess.run(entry, env=env, capture_output=True, text=True, timeout=60)
        assert (
            done.returncode == 1 and "introuvable" in done.stderr and "install.ps1" in done.stderr
        )
