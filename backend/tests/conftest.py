"""Réglages communs des tests : jamais d'appel réel à Claude Code.

`claude` peut être installé sur la machine de test : sans cette précaution, le mode
« auto » choisirait l'abonnement et les tests dépendraient de l'environnement.
Le cache des manifestes des nœuds de la suite est vidé entre deux tests. Wiki, Formulaire et
Convert sont désactivés par défaut (adresse vide). La tâche de fond des
déclencheurs de workflows est coupée (`TRIGGERS_ENABLED=false`).
"""

import os
from collections.abc import Iterator

import pytest

# Jamais de tâche de fond des déclencheurs pendant les tests : ils appellent `tick()` eux-mêmes
os.environ["TRIGGERS_ENABLED"] = "false"
# Wiki et Formulaire ont une adresse par défaut : vidée ici pour qu'aucun test n'appelle une
# application réelle ; les tests qui en ont besoin passent une adresse et un transport simulé
os.environ["WIKI_BASE_URL"] = ""
os.environ["FORMULAIRE_BASE_URL"] = ""
os.environ["CONVERT_BASE_URL"] = ""

from app.suite.nodes import clear_manifest_cache

# Doubles des workflows v2 et de la carte (fixtures `suite`, `repo`, `client`), importés à la
# demande : ils lancent l'application FastAPI.
pytest_plugins = ["tests.workflow_fixtures"]


@pytest.fixture(autouse=True)
def _no_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: None)
    # Le faux `claude` (tests/fake_claude_cli.py) lit son mode et son journal dans
    # l'environnement, en liste blanche : ces deux variables passent, rien d'autre
    from app.core.llm.providers import claude_code_provider

    extra = ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_LOG")
    monkeypatch.setattr(claude_code_provider, "CLI_ENV", (*claude_code_provider.CLI_ENV, *extra))


@pytest.fixture(autouse=True)
def _fresh_manifests() -> Iterator[None]:
    clear_manifest_cache()
    yield
    clear_manifest_cache()
