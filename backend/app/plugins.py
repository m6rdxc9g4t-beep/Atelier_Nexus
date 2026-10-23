"""Extensions de Nexus : paquets Python externes qui ajoutent boîtes à outils et agents.

Une extension est un module importable (installé dans l'environnement du backend, ex.
`pip install -e ../Agent_DatAnalyst`) **nommé explicitement** dans `NEXUS_PLUGINS`
(séparés par des virgules). Rien n'est découvert ni chargé automatiquement : installer un paquet
ne suffit pas à lui donner la main sur Nexus.

Contrat (docs/extensions.md) : le module expose `register()`, appelé une seule fois après
l'enregistrement des agents fournis. Il y enregistre ses boîtes (`register_toolset`), ses agents
(`register_agent`) et leurs libellés. Les règles de Nexus s'appliquent à l'identique : écritures
`requires_approval`, données sensibles `sensitive` (modèle local imposé), validation en
`APPROVAL_MODE=every_step`.

Une extension absente ou en erreur est signalée dans les journaux et écartée : Nexus démarre
quand même avec ses agents fournis.
"""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Nom de module Python (paquet.sous_module), jamais un chemin
MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


@dataclass(frozen=True)
class PluginState:
    name: str
    loaded: bool
    error: str | None = None


_STATES: dict[str, PluginState] = {}


def parse_plugin_list(raw: str) -> list[str]:
    """`"a, b,a"` → `["a", "b"]` (ordre conservé, sans doublon ni vide)."""
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def load_plugins(names: Iterable[str]) -> list[PluginState]:
    """Importe chaque extension et appelle son `register()` (une seule fois par processus)."""
    out: list[PluginState] = []
    for name in names:
        if name in _STATES:
            out.append(_STATES[name])
            continue
        state = _load(name)
        _STATES[name] = state
        out.append(state)
    return out


def _load(name: str) -> PluginState:
    if not MODULE_NAME.match(name):
        logger.error("Extension « %s » ignorée : nom de module invalide.", name)
        return PluginState(name, False, "nom de module invalide")
    try:
        module = importlib.import_module(name)
        register = getattr(module, "register", None)
        if not callable(register):
            raise TypeError("le module n'expose pas de fonction register()")
        register()
    except Exception as exc:  # une extension cassée ne doit jamais empêcher Nexus de démarrer
        logger.exception("Extension « %s » non chargée", name)
        return PluginState(name, False, f"{type(exc).__name__} : {exc}")
    logger.info("Extension « %s » chargée.", name)
    return PluginState(name, True)


def plugin_states() -> list[PluginState]:
    return list(_STATES.values())
