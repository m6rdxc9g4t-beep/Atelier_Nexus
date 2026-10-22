"""Mise à jour de l'app de bureau depuis le dépôt (docs/apps/mise-a-jour-bureau.md) :
décisions, état du dépôt, étapes avec npm simulé, verrou, environnement Python, lanceurs."""

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import pytest

from app import desktop
from app import desktop_update as du

ROOT = Path(__file__).resolve().parents[2]
STATE = du.RepoState(code="c1", frontend_lock="l1", requirements="r1")
STAMP = {"code": "c1", "frontend_lock": "l1"}


# ─── Décisions ────────────────────────────────────────────────────


def test_plan_nothing_changed() -> None:
    assert du.plan(STATE, STAMP, deps_present=True, build_present=True) == []


def test_plan_commit_or_local_change_rebuilds() -> None:
    changed = du.RepoState(code="c2", frontend_lock="l1", requirements="r1")
    assert du.plan(changed, STAMP, deps_present=True, build_present=True) == ["build"]


def test_plan_lockfile_change_installs_then_builds() -> None:
    changed = du.RepoState(code="c2", frontend_lock="l2", requirements="r1")
    assert du.plan(changed, STAMP, deps_present=True, build_present=True) == ["npm", "build"]


def test_plan_first_time_or_missing_pieces() -> None:
    assert du.plan(STATE, None, deps_present=True, build_present=True) == ["npm", "build"]
    assert du.plan(STATE, STAMP, deps_present=False, build_present=True) == ["npm", "build"]
    assert du.plan(STATE, STAMP, deps_present=True, build_present=False) == ["build"]


def test_venv_needed() -> None:
    assert du.venv_needed("abc", "abc\n", python_present=True) is False
    assert du.venv_needed("abd", "abc\n", python_present=True) is True  # requirements changés
    assert du.venv_needed("abc", None, python_present=True) is True
    assert du.venv_needed("abc", "abc", python_present=False) is True


# ─── Faux dépôt, faux npm ─────────────────────────────────────────


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


#: Fichiers du backend exécutés avant l'environnement de l'app (bibliothèque standard seulement)
BACKEND_FILES = (
    "desktop.py",
    "app/__init__.py",
    "app/core/__init__.py",
    "app/core/processes.py",
    "app/desktop.py",
    "app/desktop_open.py",
    "app/desktop_update.py",
    "app/desktop_launcher.py",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Dépôt minimal : lanceurs et module de mise à jour réels, interface factice."""
    repo = tmp_path / "depot"
    (repo / "backend" / "app" / "core").mkdir(parents=True)
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "scripts" / "macos").mkdir(parents=True)
    for name in BACKEND_FILES:
        shutil.copy(ROOT / "backend" / name, repo / "backend" / name)
    for name in ("launcher.sh", "app_entry.sh"):
        shutil.copy(ROOT / "scripts" / "macos" / name, repo / "scripts" / "macos" / name)
    (repo / "backend" / "requirements.txt").write_text("# aucune dépendance (test)\n")
    (repo / "backend" / "requirements-desktop.txt").write_text("")
    (repo / "frontend" / "package-lock.json").write_text('{"v": 1}\n')
    (repo / "frontend" / "src" / "page.tsx").write_text("v1\n")
    (repo / ".gitignore").write_text("node_modules/\nout/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


FAKE_NPM = """
# Faux npm : journalise l'appel ; FAKE_NPM_FAIL=ci|build fait échouer l'étape
import os, shutil, sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_NPM_CALLS"], "a", encoding="utf-8") as calls:
    calls.write("npm " + " ".join(args) + "\\n")
fail = os.environ.get("FAKE_NPM_FAIL")
if args[:1] == ["ci"]:
    if fail == "ci":
        sys.exit(1)
    Path("node_modules").mkdir(exist_ok=True)
    shutil.copy("package-lock.json", "node_modules/.package-lock.json")
elif args[:1] == ["run"]:
    Path("out").mkdir(exist_ok=True)
    if fail == "build":
        sys.exit(2)
    if os.environ.get("NEXUS_EXPORT") != "1":
        sys.exit(3)
    shutil.copy("src/page.tsx", "out/index.html")
"""


def make_fake_npm(folder: Path) -> Path:
    """Faux npm exécutable : script shell (macOS, Linux) ou `npm.cmd` (Windows) qui lance
    `fake_npm.py` avec le Python des tests."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "fake_npm.py"
    script.write_text(FAKE_NPM, encoding="utf-8")
    if sys.platform == "win32":
        path = folder / "npm.cmd"
        path.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return path
    path = folder / "npm"
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FAKE_NPM_CALLS", str(tmp_path / "npm-calls.txt"))
    monkeypatch.delenv("FAKE_NPM_FAIL", raising=False)
    return make_fake_npm(tmp_path / "bin")


def npm_calls(tmp_path: Path) -> list[str]:
    calls = tmp_path / "npm-calls.txt"
    lines = calls.read_text().splitlines() if calls.exists() else []
    calls.unlink(missing_ok=True)
    return lines


@pytest.fixture
def layout(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> du.Layout:
    home = tmp_path / "Atelier Nexus"
    monkeypatch.setenv("NEXUS_HOME", str(home))
    monkeypatch.setenv("NEXUS_LOG_DIR", str(tmp_path / "logs"))
    return du.Layout(repo=repo, home=home)


def update(layout: du.Layout, npm: Path, statuses: list[str] | None = None) -> list[str]:
    return du.update_interface(
        layout,
        npm_finder=lambda: npm,
        on_status=(statuses if statuses is not None else []).append,
    )


# ─── État du dépôt ────────────────────────────────────────────────


def test_repo_state_follows_commits_and_local_changes(repo: Path) -> None:
    first = du.repo_state(repo)
    (repo / "notes.txt").write_text("non suivi")  # fichier non suivi : ignoré
    assert du.repo_state(repo) == first

    page = repo / "frontend" / "src" / "page.tsx"
    page.write_text("v2\n")  # modification locale non commitée
    local = du.repo_state(repo)
    assert local.code != first.code and local.frontend_lock == first.frontend_lock
    page.write_text("v3\n")  # le contenu compte, pas seulement le nom
    assert du.repo_state(repo).code != local.code

    git(repo, "commit", "-q", "-am", "v3")
    committed = du.repo_state(repo)
    assert committed.code not in {first.code, local.code}

    (repo / "backend" / "requirements.txt").write_text("fastapi\n")
    assert du.repo_state(repo).requirements != committed.requirements


@pytest.mark.skipif(sys.platform == "win32", reason="sha1sum : macOS / Linux")
def test_requirements_hash_matches_former_launcher(repo: Path) -> None:
    """Même empreinte que `cat requirements*.txt | shasum` : un venv existant est réutilisé."""
    files = [str(repo / name) for name in du.REQUIREMENTS]
    shasum = subprocess.run(
        f"cat {' '.join(files)} | sha1sum", shell=True, capture_output=True, text=True, check=True
    )
    assert du.requirements_hash(repo) == shasum.stdout.split()[0]


# ─── Mise à jour de l'interface ───────────────────────────────────


def test_update_steps_only_when_needed(layout: du.Layout, npm: Path, tmp_path: Path) -> None:
    statuses: list[str] = []
    assert update(layout, npm, statuses) == ["npm", "build"]  # première fois
    assert npm_calls(tmp_path) == [
        "npm ci --no-audit --no-fund --loglevel=error",
        "npm run build",
    ]
    assert statuses == [du.LABELS["npm"], du.LABELS["build"]]
    served = du.served_build(layout)
    assert served is not None and (served / "index.html").read_text() == "v1\n"
    assert layout.current.is_symlink() if du.USE_LINKS else layout.current_pointer.is_file()
    assert not (layout.frontend / "out").exists()  # compilation déplacée, pas copiée
    stamp = du.read_stamp(layout.stamp)
    assert stamp is not None and stamp["build"] == served.name

    # Rien n'a changé : aucune commande
    assert update(layout, npm) == []
    assert npm_calls(tmp_path) == []
    assert du.pending_steps(layout) == []

    # Nouveau commit : compilation seule, ancienne compilation retirée
    (layout.frontend / "src" / "page.tsx").write_text("v2\n")
    git(layout.repo, "commit", "-q", "-am", "v2")
    assert update(layout, npm) == ["build"]
    assert npm_calls(tmp_path) == ["npm run build"]
    new = du.served_build(layout)
    assert new is not None and new != served and not served.exists()
    assert (new / "index.html").read_text() == "v2\n"

    # Lockfile changé : npm ci puis compilation
    (layout.frontend / "package-lock.json").write_text('{"v": 2}\n')
    git(layout.repo, "commit", "-q", "-am", "deps")
    assert update(layout, npm) == ["npm", "build"]

    # Modification locale non commitée : compilation
    (layout.frontend / "src" / "page.tsx").write_text("brouillon\n")
    assert update(layout, npm) == ["build"]
    served = du.served_build(layout)
    assert served is not None and (served / "index.html").read_text() == "brouillon\n"
    log = (Path(os.environ["NEXUS_LOG_DIR"]) / du.LOG_NAME).read_text()
    assert "$ " in log and "interface à jour" in log


@pytest.mark.parametrize("step", ["ci", "build"])
def test_failure_keeps_previous_build_and_stamp(
    layout: du.Layout, npm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    update(layout, npm)
    before = du.served_build(layout)
    stamp = layout.stamp.read_text()
    (layout.frontend / "package-lock.json").write_text('{"v": 2}\n')
    (layout.frontend / "src" / "page.tsx").write_text("v2\n")
    git(layout.repo, "commit", "-q", "-am", "v2")

    monkeypatch.setenv("FAKE_NPM_FAIL", step)
    with pytest.raises(du.UpdateError, match="a échoué"):
        update(layout, npm)
    assert du.served_build(layout) == before  # l'ancienne compilation reste servie
    assert before is not None and (before / "index.html").read_text() == "v1\n"
    assert layout.stamp.read_text() == stamp  # tampon inchangé : le prochain lancement réessaie
    assert du.pending_steps(layout) == ["npm", "build"]

    monkeypatch.delenv("FAKE_NPM_FAIL")
    assert update(layout, npm) == ["npm", "build"]


def test_npm_missing(layout: du.Layout) -> None:
    with pytest.raises(du.UpdateError, match="npm"):
        du.update_interface(layout, npm_finder=lambda: None)
    assert du.read_stamp(layout.stamp) is None


def test_npm_environment(tmp_path: Path) -> None:
    env = du.npm_environment(tmp_path / "bin" / "npm", {"PATH": "/usr/bin", "HOME": "/h"})
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")  # node à côté de npm
    assert env["NEXUS_EXPORT"] == "1" and env["NEXT_PUBLIC_API_URL"] == ""
    assert env["HOME"] == "/h"


@pytest.mark.skipif(sys.platform == "win32", reason="emplacements macOS / Linux")
def test_find_npm(tmp_path: Path) -> None:
    def exe(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path

    home = tmp_path / "home"
    none: dict[str, str] = {"PATH": str(tmp_path / "vide")}
    assert du.find_npm(none, home, login_shell=lambda: None, system_dirs=()) is None
    nvm_old = exe(home / ".nvm/versions/node/v9.11.0/bin/npm")
    nvm_new = exe(home / ".nvm/versions/node/v22.3.0/bin/npm")
    assert du.find_npm(none, home, login_shell=lambda: None, system_dirs=()) == nvm_new != nvm_old
    brew = exe(home / ".homebrew/bin/npm")  # Homebrew dans ~/.homebrew
    assert du.find_npm(none, home, login_shell=lambda: None, system_dirs=()) == brew
    shell = tmp_path / "zsh-npm"
    assert (
        du.find_npm(none, home, login_shell=lambda: shell, system_dirs=()) == shell
    )  # PATH du shell zsh
    on_path = exe(tmp_path / "path" / "npm")
    assert du.find_npm({"PATH": str(on_path.parent)}, home) == on_path
    assert du.find_npm({"NEXUS_NPM": str(brew), "PATH": ""}, home) == brew


LINK_MODES = [False] if sys.platform == "win32" else [True, False]


@pytest.mark.parametrize("links", LINK_MODES, ids=lambda v: "lien" if v else "fichier")
def test_publish_replaces_atomically(
    layout: du.Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, links: bool
) -> None:
    """Lien symbolique (macOS, Linux) ou fichier `courante.txt` (Windows)."""
    monkeypatch.setattr(du, "USE_LINKS", links)
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text("a")
    first = du.publish(layout, out)
    assert du.served_build(layout) == first
    (layout.builds / ".tmp-build-crash").mkdir()  # reste d'une mise à jour interrompue
    out.mkdir()
    (out / "index.html").write_text("b")
    second = du.publish(layout, out)
    assert du.served_build(layout) == second
    if links:
        assert os.readlink(layout.current) == second.name  # lien relatif
        kept = ["courante", second.name]
    else:
        assert layout.current_pointer.read_text().strip() == second.name
        kept = ["courante.txt", second.name]
    assert sorted(p.name for p in layout.builds.iterdir()) == sorted(kept)
    assert not first.exists()


def test_pointer_file_is_validated(layout: du.Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows : un fichier `courante.txt` abîmé ou hors du dossier n'est jamais suivi."""
    monkeypatch.setattr(du, "USE_LINKS", False)
    layout.builds.mkdir(parents=True)
    (layout.builds / "build-a").mkdir()
    (layout.builds / "build-a" / "index.html").write_text("x")
    for bad in ("", "..\\..\\ailleurs", "build-a/../../x", "C:build-a", "autre"):
        layout.current_pointer.write_text(bad)
        assert du.served_build(layout) is None
    layout.current_pointer.write_text("build-a\n")
    assert du.served_build(layout) == layout.builds / "build-a"


def test_discard_and_purge(tmp_path: Path) -> None:
    trash = tmp_path / ".a-supprimer"
    folder = tmp_path / "venv.precedent"
    (folder / "Scripts").mkdir(parents=True)
    du.discard(folder, trash)
    assert not folder.exists()
    (trash / "reste-1234").mkdir(parents=True)  # dossier qu'une fenêtre ouverte bloquait
    du.purge(trash)
    assert list(trash.iterdir()) == []


# ─── Plateformes ──────────────────────────────────────────────────


def test_platform_dirs() -> None:
    home = Path("/Users/françois")
    mac = du.platform_dirs("darwin", {}, home)
    assert mac.data == home / "Library/Application Support/Atelier Nexus" == mac.local
    assert mac.logs == home / "Library/Logs/Atelier Nexus"
    env = {"APPDATA": r"C:\Users\François\AppData\Roaming", "LOCALAPPDATA": r"C:\L"}
    win = du.platform_dirs("win32", env, home)
    assert win.data == Path(env["APPDATA"]) / "Atelier Nexus"  # données itinérantes
    assert win.local == Path(r"C:\L") / "Atelier Nexus"  # venv, interface : machine
    assert win.logs == Path(r"C:\L") / "Atelier Nexus" / "Logs"
    assert du.platform_dirs("win32", {}, home).local == home / "AppData/Local/Atelier Nexus"
    linux = du.platform_dirs("linux", {"XDG_DATA_HOME": "/x"}, home)
    assert linux.data == Path("/x/atelier-nexus") == linux.local
    assert linux.logs == Path("/x/atelier-nexus/logs")


def test_local_dir_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NEXUS_LOCAL", raising=False)
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path / "home"))
    assert du.nexus_local() == tmp_path / "home"  # tests, simulation : tout au même endroit
    monkeypatch.setenv("NEXUS_LOCAL", str(tmp_path / "local"))
    assert du.nexus_local() == tmp_path / "local"
    layout = du.Layout(repo=tmp_path, home=tmp_path / "home", local=tmp_path / "local")
    assert (
        layout.venv.parent == layout.builds.parent == layout.state_dir.parent == tmp_path / "local"
    )


def test_venv_python_path() -> None:
    venv = Path("venv")
    assert du.venv_python_path(venv, "darwin") == venv / "bin" / "python"
    assert du.venv_python_path(venv, "win32") == venv / "Scripts" / "python.exe"
    assert du.venv_python_path(venv, "win32", windowed=True) == venv / "Scripts" / "pythonw.exe"
    assert du.venv_python_path(venv, "linux", windowed=True) == venv / "bin" / "python"


def test_windows_npm_search(tmp_path: Path) -> None:
    """§9.3 : PATH, Node.js officiel, nvm-windows, Volta, fnm, installation par utilisateur."""
    home = tmp_path / "home"
    env = {
        "PATH": str(tmp_path / "vide"),
        "ProgramFiles": str(tmp_path / "Program Files"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
    }

    def find() -> Path | None:
        return du.find_npm(env, home, login_shell=lambda: None, platform="win32")

    assert find() is None
    candidates = du.windows_npm_candidates(env, home)
    fnm = home / "AppData" / "Roaming" / "fnm" / "aliases" / "default" / "npm.cmd"
    user = home / "AppData" / "Local" / "Programs" / "nodejs" / "npm.cmd"
    official = tmp_path / "Program Files" / "nodejs" / "npm.cmd"
    assert {fnm, user, official} <= set(candidates)
    user.parent.mkdir(parents=True)
    user.write_text("")
    assert find() == user
    official.parent.mkdir(parents=True)
    official.write_text("")
    assert find() == official  # Node.js officiel d'abord
    env["NVM_HOME"] = str(tmp_path / "nvm")
    for version in ("v18.20.0", "v22.12.0"):
        (tmp_path / "nvm" / version).mkdir(parents=True)
    names = [c.parent.name for c in du.windows_npm_candidates(env, home)]
    assert names.index("v22.12.0") < names.index("v18.20.0")  # version la plus récente d'abord


def test_npm_environment_single_path_on_windows(tmp_path: Path) -> None:
    npm = tmp_path / "nodejs" / "npm.cmd"
    env = du.npm_environment(npm, {"Path": r"C:\Windows", "X": "1"}, platform="win32")
    assert "Path" not in env and env["X"] == "1"
    assert env["PATH"] == f"{npm.parent};C:\\Windows"


def test_console_python(tmp_path: Path) -> None:
    pythonw = tmp_path / "pythonw.exe"
    assert du.console_python(pythonw) == pythonw  # pas de python.exe à côté
    (tmp_path / "python.exe").write_text("")
    assert du.console_python(pythonw) == tmp_path / "python.exe"
    assert du.console_python(tmp_path / "python3") == tmp_path / "python3"


def test_lock_one_update_at_a_time(layout: du.Layout, npm: Path) -> None:
    waited: list[bool] = []
    with du.update_lock(layout.lock):
        with pytest.raises(du.UpdateError, match="autre mise à jour"):
            with du.update_lock(layout.lock, on_wait=lambda: waited.append(True), timeout=0.2):
                pass
    assert waited == [True]

    # Une ouverture qui attend reprend après l'autre, sans refaire le travail
    statuses: list[str] = []
    done: list[list[str]] = []
    with du.update_lock(layout.lock):
        worker = threading.Thread(target=lambda: done.append(update(layout, npm, statuses)))
        worker.start()
        worker.join(0.5)
        assert worker.is_alive() and statuses == [du.LABELS["wait"]]
    worker.join(10)
    assert done == [["npm", "build"]]


# ─── Environnement Python ─────────────────────────────────────────


class FakeRunner:
    """Simule `python -m venv` et `pip install` ; `fail_pip` fait échouer l'installation."""

    def __init__(self, fail_pip: bool = False) -> None:
        self.fail_pip = fail_pip
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path, env: Mapping[str, str], log: IO[str]) -> int:
        self.calls.append(list(cmd))
        if cmd[1:3] == ["-m", "venv"]:
            python = du.venv_python_path(Path(cmd[3]))
            python.parent.mkdir(parents=True)
            python.write_text("nouveau")
            return 0
        return 1 if self.fail_pip else 0


def test_install_venv(layout: du.Layout) -> None:
    runner = FakeRunner()
    base = Path("/usr/bin/python3")
    assert du.install_venv(layout, base, runner=runner) is True
    assert runner.calls[0] == [str(base), "-m", "venv", str(layout.venv)]
    assert runner.calls[1][-4:] == [
        "-r",
        str(layout.repo / "backend/requirements.txt"),
        "-r",
        str(layout.repo / "backend/requirements-desktop.txt"),
    ]
    assert layout.venv_stamp.read_text().strip() == du.requirements_hash(layout.repo)
    assert du.main(["venv", "--check", "--repo", str(layout.repo)]) == 0
    assert du.install_venv(layout, Path("python"), runner=FakeRunner()) is False  # à jour

    # requirements changés : environnement refait
    (layout.repo / "backend" / "requirements.txt").write_text("fastapi\n")
    assert du.main(["venv", "--check", "--repo", str(layout.repo)]) == 1
    assert du.install_venv(layout, Path("python"), runner=FakeRunner()) is True


def test_install_venv_failure_restores_previous(layout: du.Layout) -> None:
    du.install_venv(layout, Path("python"), runner=FakeRunner())
    layout.venv_python.write_text("ancien")
    old_stamp = layout.venv_stamp.read_text()
    (layout.repo / "backend" / "requirements.txt").write_text("fastapi\n")

    with pytest.raises(du.UpdateError, match="dépendances Python"):
        du.install_venv(layout, Path("python"), runner=FakeRunner(fail_pip=True))
    assert layout.venv_python.read_text() == "ancien"  # remis en place
    assert layout.venv_stamp.read_text() == old_stamp
    assert not layout.previous_venv.exists()
    assert du.venv_pending(layout)  # le prochain lancement réessaie


def test_install_venv_failure_without_previous(layout: du.Layout) -> None:
    with pytest.raises(du.UpdateError):
        du.install_venv(layout, Path("python"), runner=FakeRunner(fail_pip=True))
    assert not layout.venv.exists()


# ─── Écran de démarrage ───────────────────────────────────────────


class FakeEvent:
    def wait(self, timeout: float | None = None) -> bool:
        return True


class FakeWindow:
    def __init__(self) -> None:
        self.events = type("Events", (), {"loaded": FakeEvent()})()
        self.js: list[str] = []
        self.html: list[str] = []
        self.destroyed = False

    def evaluate_js(self, script: str) -> None:
        self.js.append(script)

    def load_html(self, content: str) -> None:
        self.html.append(content)

    def destroy(self) -> None:
        self.destroyed = True


def test_splash_then_app(layout: du.Layout, npm: Path) -> None:
    window = FakeWindow()
    opened: list[Path | None] = []

    def run_update(lay: du.Layout, on_status: Any) -> list[str]:
        on_status("Compilation…")
        return update(lay, npm)

    api = desktop.DesktopApi()
    assert desktop.update_in_window(window, layout, api, opened.append, run_update) is True
    assert window.js == [f"setStatus({json.dumps('Compilation…')})"]
    assert opened == [du.served_build(layout)] and opened[0] is not None
    page = desktop.splash_page(du.LABELS["npm"])
    assert "Mise à jour d'Atelier Nexus" in page and "npm ci" in page and "setStatus" in page


def test_failed_update_offers_previous_version(layout: du.Layout, npm: Path) -> None:
    def failing(lay: du.Layout, on_status: Any) -> list[str]:
        raise du.UpdateError("La compilation de l'interface a échoué.")

    # Sans version précédente : message et journal, pas de bouton « Ouvrir quand même »
    window, opened = FakeWindow(), []
    api = desktop.DesktopApi()
    assert desktop.update_in_window(window, layout, api, opened.append, failing) is False
    assert "a échoué" in window.html[0] and "mise-a-jour.log" in window.html[0]
    assert "version précédente</button>" not in window.html[0]
    assert api.open_previous() is False and opened == []

    # Avec une compilation précédente : bouton, ouverture une seule fois
    update(layout, npm)
    window = FakeWindow()
    api.window = window
    assert desktop.update_in_window(window, layout, api, opened.append, failing) is False
    assert "Ouvrir quand même avec la version précédente</button>" in window.html[0]
    assert api.open_previous() is True and opened == [du.served_build(layout)]
    assert api.open_previous() is False
    api.quit_app()
    assert window.destroyed


# ─── Lanceurs (shell) ─────────────────────────────────────────────


def run_script(
    script: Path, *args: str, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=180,
    )


macos_only = pytest.mark.skipif(sys.platform == "win32", reason="lanceur macOS (bash)")


@macos_only
def test_app_entry_requires_the_repo(tmp_path: Path) -> None:
    app = tmp_path / "Atelier Nexus.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    (app / "Resources").mkdir()
    entry = app / "MacOS" / "atelier-nexus"
    shutil.copy(ROOT / "scripts/macos/app_entry.sh", entry)
    done = run_script(entry, env={"NEXUS_REPO": ""})
    assert done.returncode == 1 and "chemin non enregistré" in done.stderr

    (app / "Resources" / "repo-path").write_text(str(tmp_path / "deplace") + "\n")
    done = run_script(entry, env={"NEXUS_REPO": ""})
    assert done.returncode == 1 and "relancez scripts/macos/build_app.sh" in done.stderr

    fake = tmp_path / "depot" / "scripts" / "macos"
    fake.mkdir(parents=True)
    (fake / "launcher.sh").write_text('echo "lanceur $NEXUS_REPO $*"\n')
    (app / "Resources" / "repo-path").write_text(str(tmp_path / "depot") + "\n")
    done = run_script(entry, "--preparer", env={"NEXUS_REPO": ""})
    assert done.stdout.strip() == f"lanceur {tmp_path / 'depot'} --preparer"


@macos_only
def test_launcher_full_simulation(repo: Path, npm: Path, tmp_path: Path) -> None:
    """Simulation complète hors macOS : venv réel (dépendances vides), faux npm, mise à jour."""
    home, logs = tmp_path / "support", tmp_path / "logs"
    env = {
        "NEXUS_HOME": str(home),
        "NEXUS_LOG_DIR": str(logs),
        "NEXUS_PYTHON": sys.executable,
        "NEXUS_NPM": str(npm),
        "NEXUS_REPO": "",
    }
    (home / "nexus.db").parent.mkdir(parents=True)
    (home / "nexus.db").write_text("données")
    launcher = repo / "scripts" / "macos" / "launcher.sh"
    head = du.git(repo, "rev-parse", "HEAD")

    done = run_script(launcher, "--preparer", env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert du.LABELS["build"] in done.stdout and "Interface compilée." in done.stdout
    assert (home / "venv" / "bin" / "python").exists()
    layout = du.Layout(repo=repo, home=home)
    assert du.served_build(layout) is not None
    assert npm_calls(tmp_path) == ["npm ci --no-audit --no-fund --loglevel=error", "npm run build"]

    done = run_script(launcher, "--preparer", env=env)  # rien n'a changé
    assert done.returncode == 0 and "Interface déjà à jour." in done.stdout
    assert npm_calls(tmp_path) == []

    (repo / "frontend" / "src" / "page.tsx").write_text("v2\n")  # échec de compilation
    done = run_script(launcher, "--preparer", env={**env, "FAKE_NPM_FAIL": "build"})
    assert done.returncode == 1 and "La compilation de l'interface a échoué" in done.stderr
    served = du.served_build(layout)
    assert served is not None and (served / "index.html").read_text() == "v1\n"

    assert (home / "nexus.db").read_text() == "données"  # aucune donnée touchée
    assert du.git(repo, "rev-parse", "HEAD") == head  # jamais de git pull


# ─── Lanceur Windows (app/desktop_launcher.py), multiplateforme ───


def test_windows_launcher_full_simulation(repo: Path, npm: Path, tmp_path: Path) -> None:
    """Le lanceur du raccourci Windows en mode « mise à jour seulement » (`--preparer`, comme
    install.ps1 et la CI) : environnement Python réel (dépendances vides), faux npm, puis un
    second lancement qui ne refait rien."""
    home, local, logs = (
        tmp_path / "Roaming" / "Atelier Nexus",
        tmp_path / "Local",
        tmp_path / "logs",
    )
    env = {
        **os.environ,
        "NEXUS_HOME": str(home),
        "NEXUS_LOCAL": str(local),
        "NEXUS_LOG_DIR": str(logs),
        "NEXUS_NPM": str(npm),
        "NEXUS_REPO": "",
    }
    launcher = repo / "backend" / "app" / "desktop_launcher.py"

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(launcher), "--preparer"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )

    done = run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert du.LABELS["venv"] in done.stdout and "Interface compilée." in done.stdout
    layout = du.Layout(repo=repo, home=home, local=local)
    assert layout.venv_python.exists() and du.served_build(layout) is not None
    assert not home.exists() or not (home / "venv").exists()  # venv dans le dossier local
    assert npm_calls(tmp_path) == ["npm ci --no-audit --no-fund --loglevel=error", "npm run build"]
    stamp = layout.stamp.read_text()
    update_log = (logs / du.LOG_NAME).read_text(encoding="utf-8")

    done = run()  # rien n'a changé : ni environnement, ni npm, ni compilation
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Interface déjà à jour." in done.stdout and du.LABELS["venv"] not in done.stdout
    assert npm_calls(tmp_path) == []
    assert layout.stamp.read_text() == stamp
    assert (logs / du.LOG_NAME).read_text(encoding="utf-8") == update_log
