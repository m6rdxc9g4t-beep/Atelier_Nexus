"""Dépendances partagées : catalogue d'agents, dépôt des agents personnalisés, environnement."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.agents import AgentCatalog
from app.core.config import get_settings
from app.core.llm.router import LLMRouter
from app.db.conversations import ConversationRepository
from app.db.repository import CustomAgentRepository
from app.db.session import get_sessionmaker
from app.tools.environment import ToolEnvironment


@lru_cache
def get_custom_repository() -> CustomAgentRepository:
    return CustomAgentRepository(get_sessionmaker())


@lru_cache
def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository(get_sessionmaker())


def get_catalog() -> AgentCatalog:
    """Surchargeable dans les tests (dépôt en mémoire)."""
    return AgentCatalog(get_custom_repository())


def make_environment() -> ToolEnvironment:
    return ToolEnvironment(get_settings())


def get_env_factory() -> Callable[[], ToolEnvironment]:
    """Fabrique d'environnement, une par exécution (surchargeable : transports simulés)."""
    return make_environment


async def prepare_environment(
    env: ToolEnvironment, router: LLMRouter, catalog: AgentCatalog
) -> ToolEnvironment:
    """Branche la délégation : routeur, catalogue et liste des agents délégables."""
    env.router = router
    env.catalog = catalog
    agents = await catalog.agents(router, env, delegated=True)
    env.delegation_roster = [
        (a.name, a.description, a.local_only) for a in agents if "delegation" not in a.toolsets
    ]
    return env
