"""Lancement d'un workflow v2, partagé par l'API (`POST /api/workflows/{id}/run`) et les
déclencheurs (horaire, événement, test) : même registre d'étapes, même moteur, mêmes garde-fous.

Une écriture lancée par un déclencheur s'arrête sur `awaiting_approval` exactement comme en manuel :
rien ici ne distingue l'origine, sauf les champs `trigger`, `trigger_id`, `trigger_event` de
l'exécution enregistrée.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from app.agents import AgentCatalog, BaseAgent
from app.api.deps import prepare_environment
from app.core.llm import LLMRouter
from app.db.workflows import WorkflowRepository
from app.schemas.triggers import RunOrigin, TriggerEventRef
from app.schemas.workflows_v2 import WorkflowRun, WorkflowV2
from app.tools.environment import ToolEnvironment
from app.workflows_v2.engine import start_run
from app.workflows_v2.steps import StepRegistry


async def build_agent(
    name: str, llm: LLMRouter, catalog: AgentCatalog, env: ToolEnvironment
) -> BaseAgent:
    """Agent prêt à l'emploi (délégation branchée) ; `AgentNotFoundError` s'il n'existe plus."""
    await prepare_environment(env, llm, catalog)
    return await catalog.build(name, llm, env)


@asynccontextmanager
async def step_registry(
    agent_name: str | None,
    llm: LLMRouter,
    catalog: AgentCatalog,
    make_env: Callable[[], ToolEnvironment],
) -> AsyncIterator[tuple[StepRegistry, ToolEnvironment]]:
    """Étapes connues d'un workflow v2 (agent ou suite), environnement fermé à la sortie."""
    env = make_env()
    try:
        agent = await build_agent(agent_name, llm, catalog, env) if agent_name else None
        yield await StepRegistry.build(env, agent), env
    finally:
        await env.aclose()  # ferme aussi les clients des nœuds (env.suite())


async def launch_run(
    workflow: WorkflowV2,
    given: dict[str, str],
    *,
    llm: LLMRouter,
    catalog: AgentCatalog,
    make_env: Callable[[], ToolEnvironment],
    repo: WorkflowRepository,
    trigger: RunOrigin = "manual",
    trigger_id: str | None = None,
    trigger_event: TriggerEventRef | None = None,
) -> WorkflowRun:
    """Crée une exécution persistée qui avance jusqu'à la fin ou jusqu'à la première écriture.
    Lève `WorkflowError` (paramètre manquant ou inconnu) ou `AgentNotFoundError`."""
    async with step_registry(workflow.agent, llm, catalog, make_env) as (registry, env):
        return await start_run(
            workflow,
            given,
            registry,
            env,
            repo,
            trigger=trigger,
            trigger_id=trigger_id,
            trigger_event=trigger_event,
        )
