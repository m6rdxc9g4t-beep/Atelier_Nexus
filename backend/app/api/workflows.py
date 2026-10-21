"""Workflows rejouables : capture depuis une conversation, enregistrement, exécution sans modèle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.agents import AgentCatalog, AgentNotFoundError, BaseAgent
from app.api.deps import (
    get_catalog,
    get_env_factory,
    get_workflow_repository,
    prepare_environment,
)
from app.core.llm import LLMRouter, get_llm_router
from app.db.repository import StorageError
from app.db.workflows import WorkflowRepository
from app.schemas.workflows import (
    CaptureRequest,
    Workflow,
    WorkflowCreate,
    WorkflowDraft,
    WorkflowFields,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowUpdate,
)
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import declared_tool_names
from app.workflows import NOT_REPLAYABLE, WorkflowError, capture, run_workflow

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]
EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RepoDep = Annotated[WorkflowRepository, Depends(get_workflow_repository)]


def _not_found(workflow_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow « {workflow_id} » introuvable.")


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


async def _agent(
    name: str, llm: LLMRouter, catalog: AgentCatalog, env: ToolEnvironment
) -> BaseAgent:
    await prepare_environment(env, llm, catalog)
    return await catalog.build(name, llm, env)  # AgentNotFoundError → 404


async def _check_tools(agent: BaseAgent, body: WorkflowFields) -> None:
    """Chaque étape cite un outil de l'agent (même si son application n'est pas configurée
    sur cette machine : la disponibilité est vérifiée au lancement), jamais un outil qui
    ferait appel à un modèle."""
    banned = sorted({s.tool for s in body.steps} & set(NOT_REPLAYABLE))
    if banned:
        raise _unprocessable(
            f"Outil(s) impossible(s) dans un workflow, qui s'exécute sans modèle : "
            f"{', '.join(banned)}."
        )
    known = set(agent.tools) | await declared_tool_names(list(agent.toolsets))
    unknown = sorted({s.tool for s in body.steps} - known)
    if unknown:
        raise _unprocessable(
            f"Outil(s) inconnu(s) de l'agent « {agent.display_name} » : {', '.join(unknown)}."
        )


@router.get("", response_model=list[Workflow])
async def list_workflows(
    repo: RepoDep, agent: Annotated[str | None, Query(max_length=41)] = None
) -> list[Workflow]:
    """Les plus récemment modifiés ou lancés d'abord ; filtre facultatif par agent."""
    return await repo.list(agent)


@router.post("/capture", response_model=WorkflowDraft)
async def capture_workflow(
    body: CaptureRequest, llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep
) -> WorkflowDraft:
    """Propose un workflow à partir du dernier tour d'une conversation (rien n'est enregistré)."""
    env = make_env()
    try:
        agent = await _agent(body.agent, llm, catalog, env)
        return capture(agent, body.messages)
    except WorkflowError as exc:
        raise _unprocessable(str(exc)) from exc
    finally:
        await env.aclose()


@router.post("", response_model=Workflow, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> Workflow:
    env = make_env()
    try:
        await _check_tools(await _agent(body.agent, llm, catalog, env), body)
    finally:
        await env.aclose()
    return await repo.create(body)


@router.get("/{workflow_id}", response_model=Workflow)
async def get_workflow(workflow_id: str, repo: RepoDep) -> Workflow:
    workflow = await repo.get(workflow_id)
    if workflow is None:
        raise _not_found(workflow_id)
    return workflow


@router.put("/{workflow_id}", response_model=Workflow)
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> Workflow:
    current = await repo.get(workflow_id)
    if current is None:
        raise _not_found(workflow_id)
    env = make_env()
    try:
        await _check_tools(await _agent(current.agent, llm, catalog, env), body)
    finally:
        await env.aclose()
    updated = await repo.update(workflow_id, body)
    if updated is None:
        raise _not_found(workflow_id)
    return updated


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str, repo: RepoDep) -> Response:
    if not await repo.delete(workflow_id):
        raise _not_found(workflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResult)
async def run(
    workflow_id: str,
    body: WorkflowRunRequest,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> WorkflowRunResult:
    """Exécute les étapes avec les outils de l'agent, sans modèle. Une étape d'écriture sans
    décision renvoie `awaiting_approval` (rien n'est exécuté) : relancer avec
    `approvals: {"<jeton reçu dans pending>": true | false}`. Un jeton ne vaut que pour l'action
    montrée : autres valeurs ou workflow modifié entre-temps → nouvelle demande."""
    workflow = await repo.get(workflow_id)
    if workflow is None:
        raise _not_found(workflow_id)
    env = make_env()
    try:
        try:
            agent = await _agent(workflow.agent, llm, catalog, env)
        except AgentNotFoundError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"L'agent « {workflow.agent} » de ce workflow n'existe plus : supprimez le "
                "workflow ou recréez l'agent.",
            ) from exc
        result = await run_workflow(
            agent,
            workflow.steps,
            workflow.params,
            body.params,
            body.approvals,
            ToolContext(extras={"workflow_id": workflow.id}),
            binding=f"{workflow.id}:{workflow.updated_at.isoformat()}",
        )
    except WorkflowError as exc:
        raise _unprocessable(str(exc)) from exc
    finally:
        await env.aclose()
    if result.status != "awaiting_approval":
        try:
            await repo.record_run(workflow.id, result.status)
        except StorageError as exc:  # le résultat compte plus que le compteur
            logger.warning("Lancement du workflow non comptabilisé : %s", exc)
    return result
