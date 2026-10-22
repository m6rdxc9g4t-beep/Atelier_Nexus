"""Programmes externes lancés par Nexus, identiques sous macOS, Linux et Windows.

Bibliothèque standard uniquement (importé par l'application de bureau avant ses dépendances).

- `minimal_environment` : environnement transmis à une autre application de la suite, à un
  fichier ou une adresse ouverts par Nexus, et aux serveurs lancés pour les agents (contrat
  docs/apps/windows.md, SUITE.md §9.4) : utilisateur, dossier personnel, langue, fuseau,
  dossiers temporaires, variables système de Windows et `PATH` du système. Jamais
  `DATABASE_URL`, `NEXUS_*`, `PYTHON*`, ni aucune clé.
- `NO_WINDOW` : sous Windows, l'app tourne sans console (`pythonw.exe`) ; un programme console
  lancé sans ce drapeau ouvrirait une fenêtre noire.
- `windows_command` : sous Windows, un script `.cmd` passe par `cmd.exe`, qui réinterprète ses
  arguments (guillemets, `&`, `%`…). Un « shim » npm (`claude.cmd`, `npm.cmd`…) est donc
  remplacé par `node.exe <script.js>` ; les arguments ne passent jamais par `cmd.exe`.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

#: Windows : aucune fenêtre de console pour un programme lancé par l'app ; 0 ailleurs
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

#: Variables transmises partout (le nom compte, la casse aussi hors Windows)
PORTABLE_VARS = ("HOME", "USER", "LOGNAME", "LANG", "TZ", "TMPDIR")
#: Windows (liste exacte de SUITE.md §9.6, noms insensibles à la casse) : utilisateur, dossiers
#: du profil et variables système sans lesquelles beaucoup de programmes échouent
WINDOWS_VARS = (
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERNAME",
    "USERDOMAIN",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
)
#: Windows : variables ajoutées à l'environnement de la CLI Claude (SUITE.md §9.6)
CLAUDE_WINDOWS_VARS = (
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERNAME",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "PROGRAMDATA",
)
#: Linux : session graphique (xdg-open)
LINUX_SESSION_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")

#: PATH du système : celui que reçoit une app ouverte depuis le Finder (launchd)
MACOS_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
LINUX_PATH = "/usr/local/bin:/usr/bin:/bin"

_WINDOWS_ENV_KEYS = (
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ("HKCU", "Environment"),
)


def _expand_windows(value: str, env: Mapping[str, str]) -> str:
    """`%VAR%` remplacé à partir de `env` (noms insensibles à la casse), sinon laissé tel quel."""
    upper = {k.upper(): v for k, v in env.items()}
    return re.sub(r"%([^%]+)%", lambda m: upper.get(m.group(1).upper(), m.group(0)), value)


def windows_registry_path() -> list[str]:
    """PATH machine puis utilisateur lus dans le registre (non développés), ou [] hors Windows."""
    if sys.platform != "win32":
        return []
    import winreg

    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    parts: list[str] = []
    for root, key in _WINDOWS_ENV_KEYS:
        try:
            with winreg.OpenKey(roots[root], key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Path")
        except OSError:
            continue
        if isinstance(value, str) and value:
            parts.append(value)
    return parts


def system_path(
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    registry: Callable[[], list[str]] = windows_registry_path,
) -> str:
    """`PATH` du système, sans les dossiers ajoutés par l'application ou son lanceur.

    Windows : PATH machine + utilisateur du registre (ce qu'obtient une app ouverte depuis le
    menu Démarrer) ; à défaut, les dossiers de Windows. macOS : celui de launchd.
    """
    env = os.environ if env is None else env
    if platform == "win32":
        parts = [_expand_windows(v, env) for v in registry()]
        joined = ";".join(p.strip(";") for p in parts if p.strip(";"))
        if joined:
            return joined
        root = env.get("SystemRoot") or env.get("SYSTEMROOT") or r"C:\Windows"
        return ";".join([rf"{root}\System32", root, rf"{root}\System32\Wbem"])
    return MACOS_PATH if platform == "darwin" else LINUX_PATH


def minimal_environment(
    source: Mapping[str, str] | None = None,
    *,
    platform: str = sys.platform,
    path: str | None = None,
    registry: Callable[[], list[str]] = windows_registry_path,
) -> dict[str, str]:
    """Environnement minimal (liste blanche, SUITE.md §9.4) ; `path` remplace le PATH système."""
    source = os.environ if source is None else source
    wanted = set(PORTABLE_VARS)
    if platform == "win32":
        wanted |= set(WINDOWS_VARS)
    elif platform.startswith("linux"):
        wanted |= set(LINUX_SESSION_VARS)
    env: dict[str, str] = {}
    for key, value in source.items():
        name = key.upper() if platform == "win32" else key
        if name in wanted or name.startswith("LC_"):
            env[key] = value
    env["PATH"] = path if path is not None else system_path(platform, source, registry)
    return env


# ─── Windows : scripts .cmd ───────────────────────────────────────

_WINDOWS_ARG = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_SHIM_TARGET = re.compile(r'"%~?dp0%?\\([^"%]+\.(?:js|cjs|mjs|exe))"', re.IGNORECASE)


def resolve_cmd_shim(script: Path, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """`node.exe <script.js>` (ou l'exécutable) que lance un shim npm `.cmd`, sinon [].

    Shims de `npm install -g` (`"%dp0%\\node_modules\\…\\cli.js"`) et `npm.cmd` de Node.js
    (`node_modules\\npm\\bin\\npm-cli.js`, à côté de `node.exe`).
    """
    folder = script.parent
    npm_cli = folder / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if script.stem.lower() == "npm" and npm_cli.is_file():
        target: Path | None = npm_cli
    else:
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        found = [m for m in _SHIM_TARGET.findall(text) if m.lower() != "node.exe"]
        target = folder.joinpath(*found[-1].split("\\")) if found else None
    if target is None or not target.is_file():
        return []
    if target.suffix.lower() == ".exe":
        return [str(target)]
    node = folder / "node.exe"
    node_path = str(node) if node.is_file() else which("node")
    return [node_path, str(target)] if node_path else []


def pick_environment(
    source: Mapping[str, str], names: Sequence[str], platform: str = sys.platform
) -> dict[str, str]:
    """Variables de `source` dont le nom est dans `names` ou commence par `LC_` (noms
    insensibles à la casse sous Windows)."""
    windows = platform == "win32"
    wanted = {n.upper() for n in names} if windows else set(names)
    return {
        k: v
        for k, v in source.items()
        if (k.upper() if windows else k) in wanted or k.upper().startswith("LC_")
    }


def windows_command(cmd: Sequence[str], platform: str = sys.platform) -> list[str]:
    """Sous Windows, remplace un shim npm `.cmd`/`.bat` par la commande qu'il lance."""
    command = list(cmd)
    if platform != "win32" or not command:
        return command
    if Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
        direct = resolve_cmd_shim(Path(command[0]))
        if direct:
            return [*direct, *command[1:]]
    return command


def is_batch(path: str) -> bool:
    """Script de `cmd.exe` (ses arguments seraient réinterprétés)."""
    return Path(path).suffix.lower() in {".cmd", ".bat"}


def split_command(text: str, platform: str = sys.platform) -> list[str]:
    """Commande d'un réglage (`TAB_MCP_COMMAND`) découpée en arguments.

    Un chemin de fichier existant est pris tel quel (espaces compris) ; sous Windows, les
    barres obliques inverses sont gardées et les guillemets entourant un argument retirés.
    """
    text = text.strip()
    if not text:
        return []
    if Path(text.strip('"')).is_file():
        return [text.strip('"')]
    if platform == "win32":
        # Guillemets doubles (ou simples, copiés d'une commande macOS) ; barres obliques gardées
        return [a or b or c for a, b, c in _WINDOWS_ARG.findall(text)]
    return shlex.split(text)


def kill_tree(pid: int) -> None:
    """Windows : arrête un processus et ses enfants (`cmd.exe` n'arrête pas `node.exe`)."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        pass
