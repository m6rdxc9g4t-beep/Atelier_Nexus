"""Registre des agents codés (« experts ») et fiche publique d'un agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.agents.base import BaseAgent, Privacy
from app.core.llm.types import ProviderName

_REGISTRY: dict[str, type[BaseAgent]] = {}


class AgentNotFoundError(LookupError):
    pass


class AgentToolInfo(BaseModel):
    name: str
    description: str
    requires_approval: bool = False
    sensitive: bool = False


class AgentInfo(BaseModel):
    name: str
    display_name: str
    description: str
    icon: str
    category: str
    starters: list[str]
    source: Literal["builtin", "custom"]
    toolsets: list[str]
    privacy: Privacy
    #: Vrai si l'agent est verrouillé sur le modèle local (déclaré ou boîte sensible)
    local_only: bool
    default_provider: ProviderName | None
    tools: list[AgentToolInfo]
    #: Boîtes déclarées mais écartées (application non configurée)
    unavailable_toolsets: list[str] = []


def register_agent[AgentT: type[BaseAgent]](cls: AgentT) -> AgentT:
    """Décorateur : rend l'agent accessible via l'API."""
    if not cls.name or not cls.name.isidentifier():
        raise ValueError(f"Nom d'agent invalide : {cls.name!r}")
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"Agent déjà enregistré : {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get_agent_class(name: str) -> type[BaseAgent]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise AgentNotFoundError(name) from None


def list_agent_classes() -> list[type[BaseAgent]]:
    return list(_REGISTRY.values())


def builtin_names() -> set[str]:
    return set(_REGISTRY)


def describe(agent: BaseAgent) -> AgentInfo:
    return AgentInfo(
        name=agent.name,
        display_name=agent.display_name,
        description=agent.description,
        icon=agent.icon,
        category=agent.category,
        starters=list(agent.starters),
        source=agent.source,
        toolsets=list(agent.toolsets),
        privacy=agent.privacy,
        local_only=agent.local_only,
        default_provider=agent.default_provider,
        tools=[
            AgentToolInfo(
                name=t.name,
                description=t.description,
                requires_approval=t.requires_approval,
                sensitive=t.sensitive,
            )
            for t in agent.tools.values()
        ],
        unavailable_toolsets=[u.label for u in agent.unavailable],
    )
