"""Workflows rejouables : capture depuis une conversation, enregistrement, exécution sans modèle.

v1 (étape 18) : étapes `{tool, input, label}` d'un agent, réponse `WorkflowRunResult`.
v2 (étape 19, docs/workflows-v2-api.md) : graphe d'étapes outils et actions d'applications,
catalogue, validation, conversion, exécutions persistées (`/api/workflow-runs`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import TypeAdapter, ValidationError

from app.agents import AgentCatalog, AgentNotFoundError, BaseAgent
from app.api.deps import (
    get_catalog,
    get_env_factory,
    get_workflow_repository,
)
from app.core.llm import LLMRouter, get_llm_router
from app.db.repository import StorageError
from app.db.workflows import WorkflowRepository
from app.schemas.triggers import InboxCount
from app.schemas.workflows import (
    PLACEHOLDER,
    CaptureRequest,
    Workflow,
    WorkflowCreate,
    WorkflowDraft,
    WorkflowFields,
    WorkflowParam,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowUpdate,
)
from app.schemas.workflows_v2 import (
    Catalog,
    ResumeRequest,
    RunStatus,
    ValidationResult,
    WorkflowRun,
    WorkflowStepV2,
    WorkflowV2,
    WorkflowV2Create,
    WorkflowV2Fields,
    WorkflowV2Update,
)
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import declared_tool_names
from app.workflows import NOT_REPLAYABLE, WorkflowError, capture, run_workflow
from app.workflows_v2.engine import resume_run
from app.workflows_v2.launch import build_agent, launch_run, step_registry
from app.workflows_v2.validation import blocking, validate_workflow

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
runs_router = APIRouter(prefix="/api/workflow-runs", tags=["workflows"])
logger = logging.getLogger(__name__)

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]
EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RepoDep = Annotated[WorkflowRepository, Depends(get_workflow_repository)]

AnyWorkflow = Workflow | WorkflowV2
_CREATE_V1 = TypeAdapter(WorkflowCreate)
_CREATE_V2 = TypeAdapter(WorkflowV2Create)
_UPDATE_V1 = TypeAdapter(WorkflowUpdate)
_UPDATE_V2 = TypeAdapter(WorkflowV2Update)


def _not_found(workflow_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow « {workflow_id} » introuvable.")


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _parse[T](adapter: TypeAdapter[T], body: dict[str, Any]) -> T:
    """Corps v1 ou v2 lu à la main (le champ `version` choisit le schéma) : même forme d'erreur
    422 que FastAPI."""
    try:
        return adapter.validate_python(body)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [
                {"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]}
                for e in exc.errors(include_url=False, include_context=False)
            ],
        ) from exc


def _is_v2(body: dict[str, Any]) -> bool:
    return body.get("version") == 2


# AgentNotFoundError → 404 (gestionnaire commun)
_agent = build_agent
_registry = step_registry


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


async def _check_v2(
    body: WorkflowV2Fields, llm: LLMRouter, catalog: AgentCatalog, make_env: EnvFactoryDep
) -> None:
    """Enregistrement d'un v2 : refusé (422) si le graphe est invalide. Une application
    indisponible, une entrée incomplète ou une condition inachevée n'empêchent pas d'enregistrer
    un brouillon : la porte de contrôle les vérifie au lancement."""
    async with _registry(body.agent, llm, catalog, make_env) as (registry, _):
        result = validate_workflow(body, registry)
    errors = blocking(result)
    if errors:
        details = " ; ".join(
            f"{e.step_id} : {e.message}" if e.step_id else e.message for e in errors[:5]
        )
        raise _unprocessable(f"Workflow invalide ({len(errors)} problème(s)) — {details}")


# ─── Liste, capture, CRUD ─────────────────────────────────────────


@router.get("", response_model=list[Workflow | WorkflowV2])
async def list_workflows(
    repo: RepoDep, agent: Annotated[str | None, Query(max_length=41)] = None
) -> list[AnyWorkflow]:
    """v1 et v2 (champ `version`), les plus récemment modifiés ou lancés d'abord."""
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


@router.get("/catalog", response_model=Catalog)
async def workflow_catalog(
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
    agent: Annotated[str | None, Query(max_length=41)] = None,
) -> Catalog:
    """Étapes disponibles : outils de l'agent (sans `agent` : de toute la suite) et actions des
    manifestes de Viz, Projets et Tab."""
    async with _registry(agent, llm, catalog, make_env) as (registry, _):
        return registry.catalog()


@router.post("/validate", response_model=ValidationResult)
async def validate(
    body: WorkflowV2Fields, llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep
) -> ValidationResult:
    """Erreurs par étape et par champ (codes stables) et ordre d'exécution si tout est valide."""
    async with _registry(body.agent, llm, catalog, make_env) as (registry, _):
        return validate_workflow(body, registry)


@router.post("", response_model=Workflow | WorkflowV2, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
    body: Annotated[dict[str, Any], Body()],
) -> AnyWorkflow:
    """Corps v1 (`{agent, title, steps: [{tool, input}], …}`) ou v2 (`version: 2`)."""
    if _is_v2(body):
        data_v2 = _parse(_CREATE_V2, body)
        await _check_v2(data_v2, llm, catalog, make_env)
        return await repo.create(data_v2)
    data = _parse(_CREATE_V1, body)
    env = make_env()
    try:
        await _check_tools(await _agent(data.agent, llm, catalog, env), data)
    finally:
        await env.aclose()
    return await repo.create(data)


@router.get("/{workflow_id}", response_model=Workflow | WorkflowV2)
async def get_workflow(workflow_id: str, repo: RepoDep) -> AnyWorkflow:
    workflow = await repo.get(workflow_id)
    if workflow is None:
        raise _not_found(workflow_id)
    return workflow


@router.put("/{workflow_id}", response_model=Workflow | WorkflowV2)
async def update_workflow(
    workflow_id: str,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
    body: Annotated[dict[str, Any], Body()],
) -> AnyWorkflow:
    current = await repo.get(workflow_id)
    if current is None:
        raise _not_found(workflow_id)
    if isinstance(current, WorkflowV2):
        if not _is_v2(body):
            raise _unprocessable("Ce workflow est en version 2 : envoyez un corps `version: 2`.")
        data_v2 = _parse(_UPDATE_V2, body)
        await _check_v2(data_v2, llm, catalog, make_env)
        updated = await repo.update(workflow_id, data_v2)
    else:
        if _is_v2(body):
            raise _unprocessable(
                "Ce workflow est en version 1 : convertissez-le d'abord (POST …/convert)."
            )
        data = _parse(_UPDATE_V1, body)
        env = make_env()
        try:
            await _check_tools(await _agent(current.agent, llm, catalog, env), data)
        finally:
            await env.aclose()
        updated = await repo.update(workflow_id, data)
    if updated is None:
        raise _not_found(workflow_id)
    return updated


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str, repo: RepoDep) -> Response:
    if not await repo.delete(workflow_id):
        raise _not_found(workflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def convert_v1(workflow: Workflow) -> WorkflowV2Fields:
    """v1 → v2 : ids `s1..sn`, chaîne linéaire de `needs`, `{{nom}}` → `{{params.nom}}`."""

    def upgrade(value: Any) -> Any:
        if isinstance(value, str):
            return PLACEHOLDER.sub(lambda m: "{{params." + m.group(1) + "}}", value)
        if isinstance(value, dict):
            return {k: upgrade(v) for k, v in value.items()}
        if isinstance(value, list):
            return [upgrade(v) for v in value]
        return value

    steps = [
        WorkflowStepV2(
            id=f"s{index}",
            label=step.label,
            uses=f"tool:{step.tool}",
            input=upgrade(step.input),
            needs=[f"s{index - 1}"] if index > 1 else [],
        )
        for index, step in enumerate(workflow.steps, start=1)
    ]
    return WorkflowV2Fields(
        version=2,
        agent=workflow.agent,
        title=workflow.title,
        description=workflow.description,
        steps=steps,
        params=[WorkflowParam.model_validate(p.model_dump()) for p in workflow.params],
    )


@router.post("/{workflow_id}/convert", response_model=WorkflowV2)
async def convert_workflow(workflow_id: str, repo: RepoDep) -> WorkflowV2:
    """Convertit un workflow v1 en v2 (enregistré sous le même identifiant)."""
    current = await repo.get(workflow_id)
    if current is None:
        raise _not_found(workflow_id)
    if isinstance(current, WorkflowV2):
        return current
    converted = await repo.replace_with_v2(workflow_id, convert_v1(current))
    if not isinstance(converted, WorkflowV2):
        raise _not_found(workflow_id)
    return converted


# ─── Exécution ────────────────────────────────────────────────────


@router.post("/{workflow_id}/run", response_model=WorkflowRunResult | WorkflowRun)
async def run(
    workflow_id: str,
    body: WorkflowRunRequest,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> WorkflowRunResult | WorkflowRun:
    """v1 : exécute les étapes avec les outils de l'agent ; une écriture sans décision renvoie
    `awaiting_approval` (rien n'est exécuté), relancer avec `approvals: {"<jeton>": true}`.
    v2 : crée une exécution persistée qui avance jusqu'à la fin ou jusqu'à la première écriture
    (`awaiting_approval`, reprise par `POST /api/workflow-runs/{id}/resume`)."""
    workflow = await repo.get(workflow_id)
    if workflow is None:
        raise _not_found(workflow_id)
    if isinstance(workflow, WorkflowV2):
        return await _run_v2(workflow, body.params, repo, llm, catalog, make_env)
    env = make_env()
    try:
        try:
            agent = await _agent(workflow.agent, llm, catalog, env)
        except AgentNotFoundError as exc:
            raise _agent_gone(workflow.agent) from exc
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


def _agent_gone(agent: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        f"L'agent « {agent} » de ce workflow n'existe plus : supprimez le workflow ou recréez "
        "l'agent.",
    )


async def _run_v2(
    workflow: WorkflowV2,
    given: dict[str, str],
    repo: WorkflowRepository,
    llm: LLMRouter,
    catalog: AgentCatalog,
    make_env: Callable[[], ToolEnvironment],
) -> WorkflowRun:
    try:
        return await launch_run(
            workflow, given, llm=llm, catalog=catalog, make_env=make_env, repo=repo
        )
    except AgentNotFoundError as exc:
        raise _agent_gone(workflow.agent or "") from exc
    except WorkflowError as exc:
        raise _unprocessable(str(exc)) from exc


@runs_router.get("", response_model=list[WorkflowRun])
async def list_runs(
    repo: RepoDep,
    workflow_id: Annotated[str | None, Query(max_length=36)] = None,
    status_: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[WorkflowRun]:
    """Exécutions récentes d'abord ; filtres facultatifs par workflow et par statut
    (`status=awaiting_approval` : boîte « À valider », tous workflows)."""
    return await repo.list_runs(workflow_id, limit, status_)


@runs_router.get("/inbox-count", response_model=InboxCount)
async def inbox_count(repo: RepoDep) -> InboxCount:
    """Nombre d'exécutions en attente de validation (badge de l'en-tête)."""
    return InboxCount(awaiting_approval=await repo.count_runs("awaiting_approval"))


@runs_router.get("/{run_id}", response_model=WorkflowRun)
async def get_run(run_id: str, repo: RepoDep) -> WorkflowRun:
    found = await repo.get_run(run_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Exécution « {run_id} » introuvable.")
    return found[0]


@runs_router.post("/{run_id}/resume", response_model=WorkflowRun)
async def resume(
    run_id: str,
    body: ResumeRequest,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> WorkflowRun:
    """Décision sur l'étape en attente (`approvals: {jeton: vrai | faux}`) puis reprise.
    Un jeton périmé ou absent laisse l'exécution en attente (rien n'est exécuté)."""
    found = await repo.get_run(run_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Exécution « {run_id} » introuvable.")
    current, state = found
    if current.status != "awaiting_approval":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Exécution « {run_id} » non en attente de validation (statut {current.status}).",
        )
    agent = state.get("definition", {}).get("agent")
    try:
        async with _registry(agent, llm, catalog, make_env) as (registry, env):
            return await resume_run(current, state, body.approvals, registry, env, repo)
    except AgentNotFoundError as exc:
        raise _agent_gone(agent or "") from exc
