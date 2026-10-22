"""Lanceur de l'application de bureau sous Windows (docs/apps/windows.md, SUITE.md §8 et §9).

Équivalent de `scripts/macos/launcher.sh`. Le raccourci « Atelier Nexus » (menu Démarrer,
Bureau) exécute, sans console, `pythonw.exe -I <point d'entrée>` (le Python du système trouvé
par `scripts/windows/install.ps1`) ; le point d'entrée (`scripts/windows/app_entry.pyw`, copié
dans `%LOCALAPPDATA%\\Atelier Nexus\\lanceur`) lance ce fichier **du dépôt**. Après un
`git pull`, rouvrir l'app suffit :

1. environnement Python de l'app (`%LOCALAPPDATA%\\Atelier Nexus\\venv`) : créé au premier
   lancement, refait quand `backend/requirements*.txt` changent (`desktop_update.install_venv`),
   avant la fenêtre (elle en dépend), avec une petite fenêtre d'attente ; en cas d'échec,
   l'ancien est remis en place et l'utilisateur peut ouvrir l'app avec la version précédente ;
2. la fenêtre : `<venv>\\Scripts\\pythonw.exe backend\\desktop.py --mise-a-jour` (écran
   « Mise à jour… » pour `npm ci` et la compilation), sortie dans `atelier-nexus.log`.

`--preparer` : mise à jour seulement, dans la console (`install.ps1`, CI) ; code de sortie 0 si
l'app est prête, sans rien ouvrir. Jamais de `git pull`, jamais de donnée touchée.

Bibliothèque standard uniquement (exécuté par le Python du système, avant l'environnement).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Protocol, TypeVar

if __package__ in (None, ""):  # exécuté comme script par le point d'entrée du raccourci
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import desktop_update as du  # noqa: E402
from app.core.processes import NO_WINDOW  # noqa: E402

APP_LOG_NAME = "atelier-nexus.log"
APP_LOG_MAX_BYTES = 5_000_000
MIN_PYTHON = (3, 12)
INSTALL_HINT = r"powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1"
#: Couleurs de la fenêtre d'attente : charte néon dans l'orange de Nexus (cf. app/desktop.py)
SPLASH_COLORS = {"bg": "#fbf3f2", "text": "#33221f", "muted": "#766263"}

T = TypeVar("T")


class Ui(Protocol):
    """Messages du lanceur : fenêtres de Windows, ou console (`--preparer`)."""

    def alert(self, message: str) -> None: ...

    def ask_previous(self, message: str) -> bool: ...

    def busy(self, text: str, work: Callable[[], T]) -> T: ...


class ConsoleUi:
    """`--preparer` : étapes sur la sortie standard, erreurs sur la sortie d'erreur."""

    def alert(self, message: str) -> None:
        print(f"Atelier Nexus : {message}", file=sys.stderr, flush=True)

    def ask_previous(self, message: str) -> bool:
        self.alert(message)
        return False

    def busy(self, text: str, work: Callable[[], T]) -> T:
        print(text, flush=True)
        return work()


class WindowsUi:
    """Boîtes de message de Windows et fenêtre d'attente (tkinter, si installé)."""

    MB_YESNO = 0x04
    MB_ICONERROR = 0x10
    MB_ICONWARNING = 0x30
    MB_SETFOREGROUND = 0x10000
    IDYES = 6

    def __init__(self, icon: Path | None = None) -> None:
        self.icon = icon

    def _box(self, message: str, flags: int) -> int:
        if sys.platform != "win32":
            ConsoleUi().alert(message)
            return 0
        import ctypes

        flags |= self.MB_SETFOREGROUND
        return int(ctypes.windll.user32.MessageBoxW(None, message, du.APP_NAME, flags))

    def alert(self, message: str) -> None:
        self._box(message, self.MB_ICONERROR)

    def ask_previous(self, message: str) -> bool:
        question = f"{message}\n\nOuvrir quand même avec la version précédente ?"
        return self._box(question, self.MB_YESNO | self.MB_ICONWARNING) == self.IDYES

    def busy(self, text: str, work: Callable[[], T]) -> T:
        """Exécute `work` dans un fil pendant qu'une petite fenêtre indique l'étape."""
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:  # Python sans tkinter : pas de fenêtre, le travail se fait quand même
            return work()
        result: list[T] = []
        error: list[BaseException] = []

        def target() -> None:
            try:
                result.append(work())
            except BaseException as exc:  # noqa: BLE001 — relancée dans le fil principal
                error.append(exc)

        worker = threading.Thread(target=target, name="nexus-venv", daemon=True)
        try:
            root = tk.Tk()
        except tk.TclError:  # pas de session graphique
            worker.start()
            worker.join()
        else:
            self._splash(root, ttk, text)
            worker.start()

            def poll() -> None:
                if worker.is_alive():
                    root.after(200, poll)
                else:
                    root.destroy()

            root.after(200, poll)
            root.mainloop()
            worker.join()
        if error:
            raise error[0]
        return result[0]

    def _splash(self, root: Any, ttk: Any, text: str) -> None:
        colors = SPLASH_COLORS
        root.title(du.APP_NAME)
        root.resizable(False, False)
        root.configure(background=colors["bg"], padx=28, pady=22)
        root.protocol("WM_DELETE_WINDOW", lambda: None)  # le travail ne s'interrompt pas
        if self.icon and self.icon.is_file():
            with contextlib.suppress(Exception):
                root.iconbitmap(str(self.icon))
        style = ttk.Style(root)
        style.configure("Nexus.TLabel", background=colors["bg"], foreground=colors["text"])
        style.configure("Hint.TLabel", background=colors["bg"], foreground=colors["muted"])
        ttk.Label(
            root,
            text=f"Mise à jour d'{du.APP_NAME}…",
            style="Nexus.TLabel",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(root, text=text, style="Nexus.TLabel", font=("Segoe UI", 10)).pack(
            anchor="w", pady=(6, 10)
        )
        bar = ttk.Progressbar(root, mode="indeterminate", length=360)
        bar.pack(fill="x")
        bar.start(12)
        ttk.Label(
            root, text="Cela peut prendre 2 à 3 minutes.", style="Hint.TLabel", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(10, 0))
        root.update_idletasks()
        width, height = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        root.geometry(f"+{x}+{y}")


Spawn = Callable[[Sequence[str], Path, IO[str]], None]
Run = Callable[[Sequence[str], Path], int]


def spawn_window(cmd: Sequence[str], cwd: Path, log: IO[str]) -> None:
    """Lance la fenêtre sans l'attendre ; sorties dans le journal (pythonw n'en a pas)."""
    subprocess.Popen(
        list(cmd),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=NO_WINDOW,
    )


def run_in_console(cmd: Sequence[str], cwd: Path) -> int:
    """`--preparer` : exécute dans la console courante et renvoie le code de sortie."""
    return subprocess.run(list(cmd), cwd=cwd, check=False).returncode


@contextlib.contextmanager
def app_log(path: Path) -> Iterator[IO[str]]:
    """Journal de l'app (5 Mo, l'ancien gardé en `.1`), ouvert en ajout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        if path.stat().st_size > APP_LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as log:
        yield log


def launch(
    layout: du.Layout,
    argv: Sequence[str],
    *,
    ui: Ui,
    base_python: Path,
    install: Callable[[du.Layout, Path], bool] | None = None,
    spawn: Spawn = spawn_window,
    run: Run = run_in_console,
    platform: str = sys.platform,
) -> int:
    """Environnement Python puis fenêtre (ou mise à jour seule avec `--preparer`)."""
    prepare = "--preparer" in argv
    backend = layout.repo / "backend"
    log_file = du.log_dir() / du.LOG_NAME
    shown_log = du.display_path(log_file)
    if (
        not (backend / "desktop.py").is_file()
        or not (backend / "app" / "desktop_update.py").is_file()
    ):
        ui.alert(
            f"Le dépôt d'Atelier Nexus est introuvable ou incomplet ({layout.repo}). "
            f"Relancez {INSTALL_HINT} depuis le dépôt."
        )
        return 1
    if du.venv_pending(layout):
        install_venv = install or (lambda lay, py: du.install_venv(lay, py))
        try:
            ui.busy(du.LABELS["venv"], lambda: install_venv(layout, du.console_python(base_python)))
        except du.UpdateError as exc:
            message = f"{exc} Journal : {shown_log}"
            if not layout.venv_python.exists():
                ui.alert(message)
                return du.EXIT_VENV_FAILED
            if not ui.ask_previous(
                f"{exc} L'environnement précédent est conservé ; le prochain lancement "
                f"réessaiera. Journal : {shown_log}"
            ):
                return du.EXIT_VENV_RESTORED
    desktop = str(backend / "desktop.py")
    if prepare:
        python = du.venv_python_path(layout.venv, platform)
        return run([str(python), desktop, "--mise-a-jour", *argv], backend)
    pythonw = du.venv_python_path(layout.venv, platform, windowed=True)
    if not pythonw.exists():
        pythonw = du.venv_python_path(layout.venv, platform)
    with app_log(du.log_dir() / APP_LOG_NAME) as log:
        log.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} : lancement ({layout.repo})\n")
        log.flush()
        spawn([str(pythonw), desktop, "--mise-a-jour", *argv], backend, log)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée du raccourci (pythonw) et de `--preparer` (python, console)."""
    args = list(sys.argv[1:] if argv is None else argv)
    du.utf8_output()
    prepare = "--preparer" in args
    repo = Path(os.environ.get("NEXUS_REPO") or Path(__file__).resolve().parents[2])
    icon = repo / "scripts" / "windows" / "AtelierNexus.ico"
    ui: Ui = ConsoleUi() if prepare or sys.platform != "win32" else WindowsUi(icon)
    if sys.version_info < MIN_PYTHON:
        ui.alert(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent est nécessaire "
            f"(celui-ci : {sys.version.split()[0]}). Installez-le (winget install "
            f"Python.Python.3.13), puis relancez {INSTALL_HINT}."
        )
        return 1
    layout = du.Layout(repo=repo.resolve(), home=du.nexus_home(), local=du.nexus_local())
    return launch(layout, args, ui=ui, base_python=Path(sys.executable))


if __name__ == "__main__":
    sys.exit(main())
