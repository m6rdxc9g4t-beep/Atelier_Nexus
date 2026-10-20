"""Garde-fous d'architecture (règles de CLAUDE.md vérifiées par la CI)."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
PROVIDERS = APP / "core" / "llm" / "providers"
SDKS = {"anthropic", "ollama"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_llm_sdks_only_imported_by_providers() -> None:
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if PROVIDERS not in path.parents and _imported_roots(path) & SDKS
    ]
    assert not offenders, (
        "Appels directs à anthropic/ollama interdits hors de app/core/llm/providers "
        f"(passer par LLMRouter) : {offenders}"
    )


def test_agents_inherit_base_agent() -> None:
    from app.agents import BaseAgent, list_agent_classes

    assert list_agent_classes(), "aucun agent enregistré"
    for cls in list_agent_classes():
        assert issubclass(cls, BaseAgent)
