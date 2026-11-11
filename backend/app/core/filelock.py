"""Verrous de fichier du système, identiques sous macOS, Linux et Windows.

Bibliothèque standard uniquement (importé par l'application de bureau avant ses dépendances).

Un verrou du système est libéré par le système lui-même quand le processus qui le tient
s'arrête, même brutalement : jamais de verrou périmé à nettoyer, contrairement à un fichier
témoin. Il est attaché au fichier ouvert (`flock`, `msvcrt.locking`) : deux ouvertures du même
fichier s'excluent, y compris dans un même processus.
"""

from __future__ import annotations

import contextlib
import sys
from typing import IO


def try_lock(handle: IO[bytes]) -> bool:
    """Verrou exclusif sans attente : `flock` (macOS, Linux), `msvcrt.locking` (Windows)."""
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        with contextlib.suppress(OSError):
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
