"""Réglages communs des tests : jamais d'appel réel à Claude Code.

`claude` peut être installé sur la machine de test : sans cette précaution, le mode
« auto » choisirait l'abonnement et les tests dépendraient de l'environnement.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: None)
