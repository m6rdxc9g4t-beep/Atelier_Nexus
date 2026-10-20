"""Registre des agents disponibles dans le hub."""

from __future__ import annotations

from pydantic import BaseModel

from app.agents.base import BaseAgent

_REGISTRY: dict[str, type[BaseAgent]] = {}


class AgentNotFoundError(LookupError):
    pass


class ToolInfo(BaseModel):
    name: str
    description: str


class AgentInfo(BaseModel):
    name: str
    display_name: str
    description: str
    tools: list[ToolInfo]


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
    return sorted(_REGISTRY.values(), key=lambda c: c.name)


def describe(agent: BaseAgent) -> AgentInfo:
    return AgentInfo(
        name=agent.name,
        display_name=agent.display_name,
        description=agent.description,
        tools=[ToolInfo(name=t.name, description=t.description) for t in agent.tools.values()],
    )
