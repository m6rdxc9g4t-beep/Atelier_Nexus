"""Processus Nexus vivants sur une même base SQLite.

L'application de bureau n'a pas de garde d'instance unique : une deuxième ouverture (deuxième
clic sur le raccourci, `python desktop.py` depuis le dépôt) démarre un second serveur sur un
port libre, avec le même `nexus.db`. Un nettoyage de démarrage qui suppose « rien ne s'exécute
encore » (`WorkflowRepository.fail_interrupted_runs`) serait alors faux : il fermerait une
exécution que le premier processus est en train de mener.

Chaque processus tient donc, tant qu'il sert, un verrou du système sur un fichier à lui dans
`<base>.instances/`. Au démarrage, un fichier qu'on ne peut pas verrouiller appartient à un
processus vivant ; un fichier qu'on verrouille est le reste d'un processus arrêté (le système a
libéré son verrou, même après un arrêt brutal) et il est retiré. Aucun battement, aucun
identifiant de processus à interpréter.

Dans le doute (deux démarrages au même instant, dossier illisible), la réponse est « pas
seul » : le nettoyage attend le démarrage suivant, il ne ferme jamais une exécution vivante.

Une base qui n'est pas un fichier SQLite (PostgreSQL du docker-compose, SQLite en mémoire) n'a
pas de garde : un seul serveur l'utilise, le comportement est celui d'avant.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
from pathlib import Path
from typing import IO

from app.core.filelock import try_lock, unlock

log = logging.getLogger("atelier_nexus.instances")

SUFFIX = ".instances"
#: Essais pour poser son propre témoin (un autre démarrage peut le tenir un instant en le sondant)
CLAIM_ATTEMPTS = 5


def instances_dir(database_url: str) -> Path | None:
    """Dossier des témoins d'une base SQLite sur disque (`<base>.instances`), sinon None."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        url = make_url(database_url)
    except ArgumentError:
        return None
    name = url.database
    if not url.drivername.startswith("sqlite") or not name or name == ":memory:":
        return None
    if name.startswith("file:"):  # adresse d'URI SQLite : pas un chemin simple
        return None
    path = Path(name).resolve()
    return path.with_name(path.name + SUFFIX)


def _same_file(handle: IO[bytes], path: Path) -> bool:
    """Le fichier ouvert est-il encore celui du chemin (pas retiré entre-temps) ?"""
    try:
        opened, named = os.fstat(handle.fileno()), path.stat()
    except OSError:
        return False
    return (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino)


class InstanceGuard:
    """Témoin de ce processus sur une base. `acquire()` au démarrage, `release()` à l'arrêt."""

    def __init__(self, directory: Path | None) -> None:
        self.directory = directory
        self._handle: IO[bytes] | None = None
        self._path: Path | None = None

    @classmethod
    def for_database(cls, database_url: str) -> InstanceGuard:
        return cls(instances_dir(database_url))

    def acquire(self) -> bool:
        """Pose le témoin de ce processus ; vrai si aucun autre processus vivant n'utilise la
        base (seul cas où un nettoyage de démarrage est sûr)."""
        if self.directory is None:
            return True
        if self._handle is not None:
            return self._others(self.directory) == 0
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            claimed = self._claim(self.directory)
        except OSError as exc:
            log.warning("Témoin d'instance impossible à poser (%s)", exc)
            return False
        if not claimed:
            log.warning("Témoin d'instance impossible à poser")
            return False
        # Témoin posé AVANT de regarder les autres : deux démarrages simultanés se voient
        # l'un l'autre (aucun ne nettoie) plutôt que de se croire seuls tous les deux.
        return self._others(self.directory) == 0

    def _claim(self, directory: Path) -> bool:
        for _ in range(CLAIM_ATTEMPTS):
            path = directory / f"{os.getpid()}-{secrets.token_hex(6)}.lock"
            handle = path.open("xb")
            # Un autre démarrage a pu sonder (verrouiller) puis retirer ce fichier tout neuf
            # avant notre verrou : on en pose alors un autre.
            if try_lock(handle) and _same_file(handle, path):
                self._handle, self._path = handle, path
                return True
            handle.close()
            with contextlib.suppress(OSError):
                path.unlink()
        return False

    def _others(self, directory: Path) -> int:
        """Nombre d'autres processus vivants ; retire les témoins des processus arrêtés."""
        try:
            paths = sorted(directory.glob("*.lock"))
        except OSError:
            return 1  # dossier illisible : dans le doute, pas seul
        alive = 0
        for path in paths:
            if path == self._path:
                continue
            try:
                handle = path.open("r+b")
            except FileNotFoundError:
                continue  # retiré entre-temps par son propriétaire ou un autre démarrage
            except OSError:
                alive += 1  # illisible (Windows : fichier tenu) : dans le doute, vivant
                continue
            with handle:
                if not try_lock(handle):
                    alive += 1
                    continue
                # Verrou obtenu : plus personne ne tient ce témoin. Retiré sous le verrou
                # (POSIX) ; sous Windows un fichier ouvert ne se retire pas, on réessaie après.
                with contextlib.suppress(OSError):
                    path.unlink()
                unlock(handle)
            with contextlib.suppress(OSError):
                path.unlink()
        return alive

    def release(self) -> None:
        """Retire le témoin (arrêt propre). Sans effet s'il n'a pas été posé."""
        handle, path = self._handle, self._path
        self._handle = self._path = None
        if handle is None:
            return
        # Retrait avant de lâcher le verrou : un démarrage voisin ne voit jamais ce fichier
        # « libre » (sous Windows, le retrait n'aboutit qu'une fois le fichier fermé).
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink()
        with contextlib.suppress(OSError):
            unlock(handle)
        handle.close()
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink()
