"""Jeux de travail d'une conversation, gardés en mémoire du backend.

Pourquoi en mémoire : en validation `every_step`, chaque appel d'outil validé arrive dans une
nouvelle requête ; l'état de tour (`ToolContext.state`) est alors perdu. Les jeux chargés sont
donc rangés par conversation, dans le processus du backend, avec des limites :

- au plus `MAX_FRAMES` jeux par conversation (le plus ancien sort) ;
- au plus `MAX_CONVERSATIONS` conversations (la moins récemment utilisée sort) ;
- un jeu inutilisé depuis `TTL` est oublié.

Rien n'est écrit sur disque : un redémarrage de Nexus vide les jeux de travail, l'outil le dit
et l'agent recharge la source. Les jeux d'une conversation ne sont jamais visibles d'une autre.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from app.analysis.frame import Frame

MAX_FRAMES = 8
MAX_CONVERSATIONS = 32
TTL = 6 * 3600.0
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
_NO_CONVERSATION = "_hors_conversation"


class FrameNotFoundError(LookupError):
    pass


@dataclass
class _Entry:
    frame: Frame
    used: float


class FrameStore:
    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._data: OrderedDict[str, OrderedDict[str, _Entry]] = OrderedDict()
        self._clock = clock or time.monotonic

    def _bucket(self, conversation_id: str | None) -> OrderedDict[str, _Entry]:
        key = conversation_id or _NO_CONVERSATION
        bucket = self._data.get(key)
        if bucket is None:
            bucket = OrderedDict()
            self._data[key] = bucket
            while len(self._data) > MAX_CONVERSATIONS:
                self._data.popitem(last=False)
        self._data.move_to_end(key)
        now = self._clock()
        for name in [n for n, e in bucket.items() if now - e.used > TTL]:
            del bucket[name]
        return bucket

    def put(self, conversation_id: str | None, frame: Frame) -> list[str]:
        """Range le jeu (remplace un jeu du même nom) ; renvoie les noms évincés."""
        bucket = self._bucket(conversation_id)
        bucket[frame.name] = _Entry(frame, self._clock())
        bucket.move_to_end(frame.name)
        evicted: list[str] = []
        while len(bucket) > MAX_FRAMES:
            name, _ = bucket.popitem(last=False)
            evicted.append(name)
        return evicted

    def get(self, conversation_id: str | None, name: str) -> Frame:
        bucket = self._bucket(conversation_id)
        entry = bucket.get(name)
        if entry is None:
            known = ", ".join(f"« {n} »" for n in bucket) or "aucun"
            raise FrameNotFoundError(
                f"Jeu de travail « {name} » introuvable (jeux chargés : {known}). Charge-le avec "
                "`analyse_charger` ; après un redémarrage de Nexus, les jeux sont à recharger."
            )
        entry.used = self._clock()
        bucket.move_to_end(name)
        return entry.frame

    def list(self, conversation_id: str | None) -> list[Frame]:
        return [e.frame for e in self._bucket(conversation_id).values()]

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
