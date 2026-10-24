"""Jeux de travail d'une conversation (ou d'une exécution de workflow), en mémoire du backend.

Pourquoi en mémoire : en validation `every_step`, chaque appel d'outil validé arrive dans une
nouvelle requête ; l'état de tour (`ToolContext.state`) est alors perdu. Les jeux chargés sont
donc rangés par **portée** dans le processus du backend :

- `conv:<conversation_id>` pour une conversation ;
- `run:<run_id>` pour une exécution de workflow v2, `launch:<launch_id>` pour un lancement v1 ;
- sans aucune de ces clés, pas de portée : l'outil refuse (jamais de seau partagé entre
  utilisateurs ou exécutions).

Limites : `MAX_FRAMES` jeux par portée, `MAX_SCOPES` portées, `MAX_TOTAL_CELLS` cellules au
total (les jeux les moins récemment utilisés sortent d'abord), oubli après `TTL` sans usage
(purge à chaque accès, toutes portées). Rien n'est écrit sur disque : un redémarrage de Nexus vide
les jeux, l'outil le dit et l'agent recharge la source.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.analysis.frame import Frame

MAX_FRAMES = 8
MAX_SCOPES = 32
MAX_TOTAL_CELLS = 12_000_000
TTL = 6 * 3600.0
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")


class FrameNotFoundError(LookupError):
    pass


class FrameScopeError(LookupError):
    """Appel sans conversation ni exécution identifiée : aucun jeu ne peut être rangé."""


def scope_of(conversation_id: str | None, extras: dict[str, Any] | None = None) -> str:
    """Portée des jeux d'un appel d'outil (voir le docstring du module)."""
    extras = extras or {}
    if conversation_id:
        return f"conv:{conversation_id}"
    if extras.get("run_id"):
        return f"run:{extras['run_id']}"
    if extras.get("launch_id"):
        return f"launch:{extras['launch_id']}"
    raise FrameScopeError(
        "Analyse impossible hors d'une conversation enregistrée : ouvre une conversation "
        "(historique activé) puis recommence."
    )


@dataclass
class _Entry:
    frame: Frame
    used: float

    @property
    def cells(self) -> int:
        return self.frame.rows * max(1, len(self.frame.columns))


class FrameStore:
    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._data: OrderedDict[str, OrderedDict[str, _Entry]] = OrderedDict()
        self._clock = clock or time.monotonic

    # ─── Entretien ────────────────────────────────────────────────

    def _purge(self) -> None:
        now = self._clock()
        for scope in list(self._data):
            bucket = self._data[scope]
            for name in [n for n, e in bucket.items() if now - e.used > TTL]:
                del bucket[name]
            if not bucket:
                del self._data[scope]

    def _total_cells(self) -> int:
        return sum(e.cells for b in self._data.values() for e in b.values())

    def _evict_oldest(self, keep: tuple[str, str]) -> tuple[str, str] | None:
        """Retire le jeu le moins récemment utilisé, sauf `keep` ; renvoie (portée, nom)."""
        candidates = [
            (e.used, scope, name)
            for scope, b in self._data.items()
            for name, e in b.items()
            if (scope, name) != keep
        ]
        if not candidates:
            return None
        _, scope, name = min(candidates)
        del self._data[scope][name]
        if not self._data[scope]:
            del self._data[scope]
        return scope, name

    # ─── Accès ────────────────────────────────────────────────────

    def put(self, scope: str, frame: Frame) -> list[str]:
        """Range le jeu (remplace un jeu du même nom) ; renvoie les noms évincés de CETTE portée."""
        self._purge()
        bucket = self._data.get(scope)
        if bucket is None:
            bucket = self._data[scope] = OrderedDict()
        self._data.move_to_end(scope)
        bucket[frame.name] = _Entry(frame, self._clock())
        bucket.move_to_end(frame.name)
        evicted: list[str] = []
        while len(bucket) > MAX_FRAMES:
            name, _ = bucket.popitem(last=False)
            evicted.append(name)
        while len(self._data) > MAX_SCOPES:
            oldest = next(iter(self._data))
            if oldest == scope:
                break
            del self._data[oldest]
        while self._total_cells() > MAX_TOTAL_CELLS:
            gone = self._evict_oldest(keep=(scope, frame.name))
            if gone is None:
                break
            if gone[0] == scope:
                evicted.append(gone[1])
        return evicted

    def get(self, scope: str, name: str) -> Frame:
        self._purge()
        bucket = self._data.get(scope, OrderedDict())
        entry = bucket.get(name)
        if entry is None:
            known = ", ".join(f"« {n} »" for n in bucket) or "aucun"
            raise FrameNotFoundError(
                f"Jeu de travail « {name} » introuvable (jeux chargés : {known}). Charge-le avec "
                "`analyse_charger` ; après un redémarrage de Nexus ou 6 h sans usage, les jeux "
                "sont à recharger."
            )
        entry.used = self._clock()
        bucket.move_to_end(name)
        self._data.move_to_end(scope)
        return entry.frame

    def list(self, scope: str) -> list[Frame]:
        self._purge()
        bucket = self._data.get(scope)
        return [e.frame for e in bucket.values()] if bucket else []

    def drop(self, scope: str) -> None:
        """Oublie tous les jeux d'une portée (conversation supprimée)."""
        self._data.pop(scope, None)

    def clear(self) -> None:
        self._data.clear()


#: Magasin du processus (un backend Nexus = un processus)
FRAMES = FrameStore()


def frame_name(raw: str) -> str:
    """Nom de jeu sûr : minuscules, chiffres et `_` (« Ventes 2026.csv » → `ventes_2026`)."""
    from app.tools.formatting import snake_key

    base = raw.rsplit(".", 1)[0] if "." in raw[-6:] else raw
    key = snake_key(base)[:40].strip("_") or "jeu"
    return key if NAME.match(key) else "jeu"
