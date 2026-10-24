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
    #: Nom lisible (« Convert · conversion d'un fichier ») : `app/tools/labels.py`, complété par
    #: les extensions ; l'interface l'utilise pour les outils qu'elle ne connaît pas
    label: str
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


#: Extensions déjà appliquées à un agent fourni : (agent, source)
_EXTENDED: set[tuple[str, str]] = set()


def extend_agent(
    name: str,
    *,
    source: str,
    toolsets: tuple[str, ...] = (),
    instructions: str = "",
    starters: tuple[str, ...] = (),
) -> type[BaseAgent]:
    """Ajoute à un agent FOURNI des boîtes à outils, des consignes et des exemples (extensions).

    Une extension complète ainsi un agent existant (ex. le Data Analyst reçoit Convert et les
    écritures Viz d'`Agent_DatAnalyst`) au lieu d'en créer un second. Idempotent par `source`.
    Refuse (ValueError, rien n'est modifié) : agent inconnu ou personnalisé, boîte inconnue, ou
    boîte sensible sur un agent qui n'est pas déjà verrouillé sur le modèle local — une extension
    ne peut pas faire basculer un agent en « 100 % local » à l'insu de l'utilisateur.
    """
    from app.tools.toolsets import get_toolset

    try:
        cls = get_agent_class(name)
    except AgentNotFoundError:
        raise ValueError(f"Agent fourni inconnu : {name}") from None
    if (name, source) in _EXTENDED:
        return cls
    for toolset_id in toolsets:
        toolset = get_toolset(toolset_id)  # KeyError si inconnue
        if toolset.sensitive and cls.privacy != "local_only":
            raise ValueError(
                f"Boîte sensible « {toolset_id} » refusée pour « {name} » (agent non local)."
            )
    cls.toolsets = tuple(dict.fromkeys((*cls.toolsets, *toolsets)))
    if instructions.strip():
        cls.system_prompt = f"{cls.system_prompt.rstrip()}\n\n{instructions.strip()}\n"
    cls.starters = tuple(dict.fromkeys((*cls.starters, *starters)))
    _EXTENDED.add((name, source))
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
                label=t.label,
                description=t.description,
                requires_approval=t.requires_approval,
                sensitive=t.sensitive,
            )
            for t in agent.tools.values()
        ],
        unavailable_toolsets=[u.label for u in agent.unavailable],
    )
