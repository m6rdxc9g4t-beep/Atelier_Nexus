"""Catalogue unifié : agents codés (registre) + agents personnalisés (base de données)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from app.agents.base import BaseAgent
from app.agents.custom import ConfigurableAgent
from app.agents.registry import (
    AgentInfo,
    AgentNotFoundError,
    describe,
    get_agent_class,
    list_agent_classes,
)
from app.core.llm.router import LLMRouter
from app.schemas.agents import CustomAgentDefinition

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

logger = logging.getLogger(__name__)


class CustomAgentSource(Protocol):
    async def list(self) -> list[CustomAgentDefinition]: ...

    async def get(self, name: str) -> CustomAgentDefinition | None: ...


class AgentCatalog:
    def __init__(self, custom: CustomAgentSource | None = None) -> None:
        self.custom = custom

    async def _custom_definitions(self) -> list[CustomAgentDefinition]:
        if self.custom is None:
            return []
        try:
            return await self.custom.list()
        except Exception as exc:  # base indisponible : les experts restent utilisables
            logger.warning("Agents personnalisés indisponibles : %s", exc)
            return []

    async def build(
        self,
        name: str,
        router: LLMRouter,
        env: ToolEnvironment | None,
        *,
        delegated: bool = False,
    ) -> BaseAgent:
        try:
            return get_agent_class(name)(router, env, delegated=delegated)
        except AgentNotFoundError:
            pass
        definition = None
        if self.custom is not None:
            try:
                definition = await self.custom.get(name)
            except Exception as exc:  # base indisponible : seul un expert peut être trouvé
                logger.warning("Agent « %s » introuvable (base indisponible : %s)", name, exc)
        if definition is None:
            raise AgentNotFoundError(name)
        return ConfigurableAgent(definition, router, env, delegated=delegated)

    async def agents(
        self, router: LLMRouter, env: ToolEnvironment | None, *, delegated: bool = False
    ) -> list[BaseAgent]:
        built: list[BaseAgent] = [
            cls(router, env, delegated=delegated) for cls in list_agent_classes()
        ]
        built += [
            ConfigurableAgent(d, router, env, delegated=delegated)
            for d in await self._custom_definitions()
        ]
        return built

    async def infos(self, router: LLMRouter, env: ToolEnvironment | None) -> list[AgentInfo]:
        return [describe(a) for a in await self.agents(router, env)]
