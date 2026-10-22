"""Réglages communs des tests : jamais d'appel réel à Claude Code.

`claude` peut être installé sur la machine de test : sans cette précaution, le mode
« auto » choisirait l'abonnement et les tests dépendraient de l'environnement.
Le cache des manifestes des nœuds de la suite est vidé entre deux tests.
"""

from collections.abc import Iterator

import pytest

from app.suite.nodes import clear_manifest_cache

# Doubles des workflows v2 et de la carte (fixtures `suite`, `repo`, `client`), importés à la
# demande : ils lancent l'application FastAPI.
pytest_plugins = ["tests.workflow_fixtures"]


@pytest.fixture(autouse=True)
def _no_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: None)


@pytest.fixture(autouse=True)
def _fresh_manifests() -> Iterator[None]:
    clear_manifest_cache()
    yield
    clear_manifest_cache()
