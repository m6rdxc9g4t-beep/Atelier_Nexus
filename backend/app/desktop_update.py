"""Mise à jour de l'application de bureau à partir du dépôt (docs/apps/mise-a-jour-bureau.md).

« Atelier Nexus.app » est un lanceur qui exécute le code du dépôt. Après un `git pull` (ou une
modification locale), le lancement suivant refait, et seulement si nécessaire :

1. l'environnement Python de l'app (`venv`) si `backend/requirements.txt` ou
   `requirements-desktop.txt` ont changé (sous-commande `venv`, lancée par `launcher.sh` avant
   la fenêtre : sans environnement, pas de fenêtre) ;
2. `npm ci` dans `frontend/` si `package-lock.json` a changé ou si `node_modules` manque ;
3. la compilation de l'interface (export statique), publiée dans le dossier de l'app par un
   remplacement atomique : la compilation précédente reste servie tant que la nouvelle n'a pas
   entièrement réussi.

Le tampon (`<dossier de l'app>/mise-a-jour/etat.json`) n'est écrit qu'après une mise à jour
réussie ; un verrou garantit une seule mise à jour à la fois. Jamais de `git pull`, jamais de
donnée touchée : seuls `venv/`, `interface/` et `mise-a-jour/` du dossier de l'app sont écrits.

Bibliothèque standard uniquement : le lanceur exécute ce fichier avec le Python du système
(`python -I backend/app/desktop_update.py venv`) avant que l'environnement de l'app n'existe.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

APP_NAME = "Atelier Nexus"
#: Dépendances Python installées dans l'environnement de l'app (requirements-dev.txt n'y est pas)
REQUIREMENTS = ("backend/requirements.txt", "backend/requirements-desktop.txt")
FRONTEND_LOCK = "frontend/package-lock.json"
LOG_NAME = "mise-a-jour.log"
LOG_MAX_BYTES = 5_000_000
STEP_TIMEOUT = 30 * 60  # secondes, par commande (npm ci, compilation, pip)
LOCK_TIMEOUT = 45 * 60  # attente maximale d'une autre mise à jour

#: Libellés de l'écran de démarrage, dans l'ordre des étapes
LABELS = {
    "wait": "Une autre ouverture d'Atelier Nexus est déjà en train de la mettre à jour…",
    "venv": "Installation des dépendances Python…",
    "npm": "Installation des dépendances de l'interface (npm ci)…",
    "build": "Compilation de l'interface…",
}

#: Code de sortie de `venv` : échec, environnement précédent remis en place
EXIT_VENV_RESTORED = 3
#: Code de sortie de `venv` : échec, aucun environnement utilisable
EXIT_VENV_FAILED = 4

Runner = Callable[[Sequence[str], Path, Mapping[str, str], IO[str]], int]
Status = Callable[[str], None]


class UpdateError(Exception):
    """Échec d'une étape ; le message (en français) s'affiche dans l'écran de démarrage."""


# ─── Dossiers ─────────────────────────────────────────────────────


def nexus_home() -> Path:
    """Dossier des données et réglages de l'utilisateur (`NEXUS_HOME` pour le surcharger)."""
    custom = os.environ.get("NEXUS_HOME")
    if custom:
        return Path(custom).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "atelier-nexus"


def log_dir() -> Path:
    """Dossier des journaux (`NEXUS_LOG_DIR` pour le surcharger)."""
    custom = os.environ.get("NEXUS_LOG_DIR")
    if custom:
        return Path(custom).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    return nexus_home() / "logs"


def display_path(path: Path) -> str:
    """Chemin affiché à l'utilisateur, avec « ~ » pour son dossier personnel."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class Layout:
    """Emplacements du dépôt (code) et du dossier de l'app (environnement, compilation, tampon)."""

    repo: Path
    home: Path

    @property
    def frontend(self) -> Path:
        return self.repo / "frontend"

    @property
    def venv(self) -> Path:
        return self.home / "venv"

    @property
    def venv_python(self) -> Path:
        return self.venv / "bin" / "python"

    @property
    def venv_stamp(self) -> Path:
        # Même fichier et même empreinte que l'ancien lanceur : pas de réinstallation inutile
        return self.venv / ".nexus-requirements"

    @property
    def previous_venv(self) -> Path:
        return self.home / "venv.precedent"

    @property
    def state_dir(self) -> Path:
        return self.home / "mise-a-jour"

    @property
    def stamp(self) -> Path:
        return self.state_dir / "etat.json"

    @property
    def lock(self) -> Path:
        return self.state_dir / "verrou"

    @property
    def builds(self) -> Path:
        return self.home / "interface"

    @property
    def current(self) -> Path:
        """Lien vers la compilation servie (remplacé de façon atomique)."""
        return self.builds / "courante"


# ─── État du dépôt ────────────────────────────────────────────────


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _file_digest(path: Path) -> str:
    try:
        return digest(path.read_bytes())
    except OSError:
        return "absent"


def git(repo: Path, *args: str) -> str | None:
    """Sortie d'une commande git en lecture seule, ou None (pas de git, pas de dépôt)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def requirements_hash(repo: Path) -> str:
    """SHA-1 des fichiers de dépendances mis bout à bout (comme `cat … | shasum`)."""
    h = hashlib.sha1(usedforsecurity=False)
    for name in REQUIREMENTS:
        with contextlib.suppress(OSError):
            h.update((repo / name).read_bytes())
    return h.hexdigest()


@dataclass(frozen=True)
class RepoState:
    """Empreintes du code (commit + modifications locales suivies) et des dépendances."""

    code: str
    frontend_lock: str
    requirements: str


def repo_state(repo: Path) -> RepoState:
    """État du dépôt : `git rev-parse HEAD` + contenu des fichiers suivis modifiés localement."""
    head = (git(repo, "rev-parse", "HEAD") or "sans-git").strip()
    top = Path((git(repo, "rev-parse", "--show-toplevel") or str(repo)).strip())
    changed = sorted(
        name for name in (git(repo, "diff", "--name-only", "-z", "HEAD") or "").split("\0") if name
    )
    parts = [head]
    for name in changed:
        target = top / name
        parts.append(f"{name}:{_file_digest(target) if target.is_file() else 'supprimé'}")
    return RepoState(
        code=digest("\n".join(parts).encode()),
        frontend_lock=_file_digest(repo / FRONTEND_LOCK),
        requirements=requirements_hash(repo),
    )


# ─── Décisions (pures) ────────────────────────────────────────────


def venv_needed(requirements: str, venv_stamp: str | None, python_present: bool) -> bool:
    """Environnement Python à (re)faire : absent, ou dépendances changées depuis son installation."""
    return not python_present or (venv_stamp or "").strip() != requirements


def plan(
    state: RepoState,
    stamp: Mapping[str, Any] | None,
    *,
    deps_present: bool,
    build_present: bool,
) -> list[str]:
    """Étapes de l'interface à faire avant de lancer l'app (vide : tout est à jour).

    - `npm` (`npm ci`) : `node_modules` absent, aucun tampon, ou lockfile changé ;
    - `build` : après `npm`, ou code changé (commit ou modification locale), ou compilation absente.
    """
    steps: list[str] = []
    if not deps_present or stamp is None or stamp.get("frontend_lock") != state.frontend_lock:
        steps.append("npm")
    if steps or stamp is None or stamp.get("code") != state.code or not build_present:
        steps.append("build")
    return steps


def read_stamp(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def served_build(layout: Layout) -> Path | None:
    """Compilation servie (dossier réel), ou None s'il n'y en a pas encore."""
    try:
        target = layout.current.resolve(strict=True)
    except OSError:
        return None
    return target if (target / "index.html").is_file() else None


def deps_present(layout: Layout) -> bool:
    return (layout.frontend / "node_modules" / ".package-lock.json").is_file()


def pending_steps(layout: Layout) -> list[str]:
    """Étapes de l'interface à faire (lecture seule, sans verrou)."""
    return plan(
        repo_state(layout.repo),
        read_stamp(layout.stamp),
        deps_present=deps_present(layout),
        build_present=served_build(layout) is not None,
    )


def venv_pending(layout: Layout) -> bool:
    try:
        stamp: str | None = layout.venv_stamp.read_text(encoding="utf-8")
    except OSError:
        stamp = None
    return venv_needed(requirements_hash(layout.repo), stamp, layout.venv_python.exists())


# ─── Journal, verrou, commandes ───────────────────────────────────


@contextlib.contextmanager
def journal(path: Path) -> Iterator[IO[str]]:
    """Journal de la mise à jour (5 Mo, l'ancien gardé en `.1`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as log:
        yield log


def note(log: IO[str], text: str) -> None:
    log.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} : {text}\n")
    log.flush()


@contextlib.contextmanager
def update_lock(
    path: Path,
    on_wait: Callable[[], None] = lambda: None,
    timeout: float = LOCK_TIMEOUT,
    poll: float = 0.5,
) -> Iterator[None]:
    """Une seule mise à jour à la fois (verrou du système, libéré même si le processus meurt)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        deadline = time.monotonic() + timeout
        waited = False
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not waited:
                    on_wait()
                    waited = True
                if time.monotonic() > deadline:
                    raise UpdateError(
                        "Une autre mise à jour d'Atelier Nexus ne se termine pas. "
                        "Quittez les autres fenêtres de l'application, puis rouvrez-la."
                    ) from None
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_command(cmd: Sequence[str], cwd: Path, env: Mapping[str, str], log: IO[str]) -> int:
    """Exécute une commande, sortie dans le journal ; code de retour (127 : introuvable)."""
    log.write(f"$ {' '.join(cmd)}\n")
    log.flush()
    try:
        done = subprocess.run(
            list(cmd),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=STEP_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.write(f"(arrêtée après {STEP_TIMEOUT} s)\n")
        return 124
    except OSError as exc:
        log.write(f"(impossible de lancer la commande : {exc})\n")
        return 127
    return done.returncode


# ─── Node.js ──────────────────────────────────────────────────────


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.name)[:3])


def login_shell_npm(timeout: float = 15.0) -> Path | None:
    """`npm` vu par le shell de connexion zsh (PATH du Terminal : .zprofile, .zshrc…)."""
    zsh = Path("/bin/zsh")
    if not zsh.exists():
        return None
    for flags in ("-lc", "-lic"):
        try:
            done = subprocess.run(
                [str(zsh), flags, "command -v npm"],
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in reversed(done.stdout.splitlines()):
            candidate = Path(line.strip())
            if candidate.is_absolute() and os.access(candidate, os.X_OK):
                return candidate
    return None


def find_npm(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    login_shell: Callable[[], Path | None] = login_shell_npm,
    system_dirs: Sequence[Path] = (Path("/opt/homebrew/bin"), Path("/usr/local/bin")),
) -> Path | None:
    """`npm` sans dépendre du PATH du Finder : `NEXUS_NPM`, PATH, shell de connexion zsh,
    Homebrew (`~/.homebrew`, `/opt/homebrew`, `/usr/local`), nvm, Volta."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    forced = env.get("NEXUS_NPM")
    if forced:
        return Path(forced) if os.access(forced, os.X_OK) else None
    found = shutil.which("npm", path=env.get("PATH", ""))
    if found:
        return Path(found)
    shell = login_shell()
    if shell:
        return shell
    fixed = [
        home / ".homebrew" / "bin" / "npm",
        *(d / "npm" for d in system_dirs),
        home / ".volta" / "bin" / "npm",
    ]
    nvm = sorted((home / ".nvm" / "versions" / "node").glob("v*"), key=_version_key, reverse=True)
    for candidate in [*fixed, *(d / "bin" / "npm" for d in nvm)]:
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def npm_environment(npm: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environnement de npm : dossier de `npm` (donc de `node`) en tête du PATH, export statique."""
    env = dict(os.environ if base is None else base)
    env["PATH"] = os.pathsep.join([str(npm.parent), env.get("PATH", "/usr/bin:/bin")])
    env.update(NEXUS_EXPORT="1", NEXT_PUBLIC_API_URL="", NEXT_TELEMETRY_DISABLED="1")
    return env


# ─── Mise à jour de l'interface ───────────────────────────────────


def publish(layout: Layout, out: Path) -> Path:
    """Remplace la compilation servie par `out` (déplacé), de façon atomique ; renvoie son dossier."""
    layout.builds.mkdir(parents=True, exist_ok=True)
    name = f"build-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    staging = layout.builds / f".tmp-{name}"
    shutil.move(str(out), str(staging))
    final = layout.builds / name
    staging.rename(final)
    link = layout.builds / ".courante.tmp"
    with contextlib.suppress(FileNotFoundError):
        link.unlink()
    link.symlink_to(name)
    if layout.current.is_dir() and not layout.current.is_symlink():
        shutil.rmtree(layout.current)
    os.replace(link, layout.current)  # un lien remplace l'autre : jamais d'état intermédiaire
    for old in layout.builds.iterdir():
        if old.name not in {name, layout.current.name} and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old, ignore_errors=True)
    return final


def update_interface(
    layout: Layout,
    *,
    on_status: Status = lambda _: None,
    runner: Runner = run_command,
    npm_finder: Callable[[], Path | None] = find_npm,
    log_file: Path | None = None,
) -> list[str]:
    """Fait les étapes nécessaires de l'interface ; renvoie celles qui ont été faites.

    UpdateError en cas d'échec : tampon inchangé, compilation précédente toujours servie.
    """
    with journal(log_file or log_dir() / LOG_NAME) as log:
        with update_lock(layout.lock, on_wait=lambda: on_status(LABELS["wait"])):
            steps = pending_steps(layout)  # relu sous verrou : une autre ouverture a pu le faire
            if not steps:
                return []
            note(log, f"mise à jour de l'interface ({', '.join(steps)}) — {layout.repo}")
            npm = npm_finder()
            if npm is None:
                note(log, "npm introuvable")
                raise UpdateError(
                    "Node.js (npm) est introuvable : installez-le (« brew install node » ou "
                    "https://nodejs.org), puis rouvrez Atelier Nexus."
                )
            env = npm_environment(npm)
            if "npm" in steps:
                on_status(LABELS["npm"])
                cmd = [str(npm), "ci", "--no-audit", "--no-fund", "--loglevel=error"]
                if runner(cmd, layout.frontend, env, log) != 0:
                    note(log, "échec de npm ci")
                    raise UpdateError(
                        "L'installation des dépendances de l'interface (npm ci) a échoué "
                        "(connexion Internet ?)."
                    )
            on_status(LABELS["build"])
            out = layout.frontend / "out"
            shutil.rmtree(out, ignore_errors=True)
            if (
                runner([str(npm), "run", "build"], layout.frontend, env, log) != 0
                or not (out / "index.html").is_file()
            ):
                note(log, "échec de la compilation")
                raise UpdateError("La compilation de l'interface a échoué.")
            final = publish(layout, out)
            # État relu après coup : la compilation peut retoucher des fichiers suivis
            after = repo_state(layout.repo)
            layout.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = layout.stamp.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "code": after.code,
                        "frontend_lock": after.frontend_lock,
                        "requirements": after.requirements,
                        "build": final.name,
                        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, layout.stamp)
            note(log, f"interface à jour : {final.name}")
            return steps


# ─── Environnement Python ─────────────────────────────────────────


def install_venv(
    layout: Layout,
    base_python: Path,
    *,
    runner: Runner = run_command,
    log_file: Path | None = None,
) -> bool:
    """(Ré)installe l'environnement Python si nécessaire ; renvoie True s'il a été refait.

    L'ancien environnement est mis de côté puis remis en place si l'installation échoue
    (UpdateError) : l'app reste utilisable avec ses dépendances précédentes.
    """
    with journal(log_file or log_dir() / LOG_NAME) as log:
        with update_lock(layout.lock):
            if not venv_pending(layout):
                return False
            note(log, f"environnement Python ({base_python}) — {layout.repo}")
            wanted = requirements_hash(layout.repo)
            shutil.rmtree(layout.previous_venv, ignore_errors=True)
            if layout.venv.exists():
                layout.venv.rename(layout.previous_venv)
            env = dict(os.environ)
            python = str(layout.venv_python)
            pip = [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
            requirements = [arg for name in REQUIREMENTS for arg in ("-r", str(layout.repo / name))]
            ok = runner([str(base_python), "-m", "venv", str(layout.venv)], layout.home, env, log)
            if ok == 0:
                ok = runner([*pip, *requirements], layout.home, env, log)
            if ok != 0:
                shutil.rmtree(layout.venv, ignore_errors=True)
                restored = layout.previous_venv.exists()
                if restored:
                    layout.previous_venv.rename(layout.venv)
                note(
                    log,
                    "échec de l'environnement Python" + (" (précédent remis)" if restored else ""),
                )
                raise UpdateError(
                    "L'installation des dépendances Python a échoué (connexion Internet ?)."
                )
            layout.venv_stamp.write_text(wanted + "\n", encoding="utf-8")
            shutil.rmtree(layout.previous_venv, ignore_errors=True)
            note(log, "environnement Python à jour")
            return True


# ─── Ligne de commande (lanceur) ──────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """`venv --check` : 0 si l'environnement est à jour, 1 sinon.
    `venv` : (ré)installe avec ce Python ; 0, EXIT_VENV_RESTORED ou EXIT_VENV_FAILED."""
    parser = argparse.ArgumentParser(description="Mise à jour d'Atelier Nexus (bureau)")
    parser.add_argument("command", choices=["venv"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    layout = Layout(repo=args.repo.resolve(), home=nexus_home())
    if args.check:
        return 1 if venv_pending(layout) else 0
    try:
        install_venv(layout, Path(sys.executable))
    except UpdateError:  # message affiché par le lanceur, détail dans le journal
        return EXIT_VENV_RESTORED if layout.venv_python.exists() else EXIT_VENV_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
