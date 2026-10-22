"""Chaînes d'agents : catalogue, démarrage, validation d'une étape, arrêt.

Le serveur tient l'état de la chaîne (étape courante, livrables figés) ; chaque étape se joue
dans une conversation ordinaire avec son agent (validations, pas à pas). L'interface ouvre la
conversation renvoyée et y envoie le message de passage de relais.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agents import AgentCatalog, BaseAgent
from app.api.deps import (
    get_catalog,
    get_chain_repository,
    get_conversation_repository,
    get_env_factory,
    prepare_environment,
)
from app.chains import (
    CHAINS,
    StageNotFinishedError,
    chain_info,
    deliverable_from,
    get_chain,
    handoff_message,
    recap_artifact,
)
from app.chains.definitions import ChainNotFoundError, leaks_local_data
from app.core.llm import LLMRouter, get_llm_router
from app.db.chains import ChainRunRepository
from app.db.conversations import ConversationRepository
from app.schemas.chains import (
    ChainDefinition,
    ChainInfo,
    ChainRun,
    ChainStart,
    ChainStep,
    StageState,
)
from app.tools.base import Artifact
from app.tools.environment import ToolEnvironment

router = APIRouter(prefix="/api", tags=["chaînes"])

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]
EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RunsDep = Annotated[ChainRunRepository, Depends(get_chain_repository)]
ConvDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]


async def _agents(
    names: list[str], llm: LLMRouter, catalog: AgentCatalog, make_env: Callable[[], ToolEnvironment]
) -> dict[str, BaseAgent]:
    """Agents des étapes, construits pour lire leur nom affiché et leur verrou local."""
    env = make_env()
    try:
        await prepare_environment(env, llm, catalog)
        return {name: await catalog.build(name, llm, env) for name in dict.fromkeys(names)}
    finally:
        await env.aclose()


def _chain(chain_id: str) -> ChainDefinition:
    try:
        return get_chain(chain_id)
    except ChainNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Chaîne « {chain_id} » inconnue.") from exc


async def _run_or_404(runs: ChainRunRepository, run_id: str) -> ChainRun:
    run = await runs.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Exécution « {run_id} » introuvable.")
    return run


def _title(chain: ChainDefinition, index: int) -> str:
    stage = chain.stages[index]
    return f"{chain.title} · {index + 1}/{len(chain.stages)} — {stage.role}"[:120]


@router.get("/chains", response_model=list[ChainInfo])
async def list_chains(llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep) -> list[ChainInfo]:
    names = [s.agent for c in CHAINS.values() for s in c.stages]
    agents = await _agents(names, llm, catalog, make_env)
    return [chain_info(c, agents) for c in CHAINS.values()]


@router.get("/chain-runs", response_model=list[ChainRun])
async def list_runs(
    runs: RunsDep, chain: Annotated[str | None, Query(max_length=41)] = None
) -> list[ChainRun]:
    """Les plus récentes d'abord ; filtre facultatif par chaîne."""
    return await runs.list(chain)


@router.get("/chain-runs/{run_id}", response_model=ChainRun)
async def get_run(run_id: str, runs: RunsDep) -> ChainRun:
    return await _run_or_404(runs, run_id)


@router.post(
    "/chains/{chain_id}/runs", response_model=ChainStep, status_code=status.HTTP_201_CREATED
)
async def start_chain(
    chain_id: str,
    body: ChainStart,
    runs: RunsDep,
    conversations: ConvDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> ChainStep:
    """Crée l'exécution et la conversation de l'étape 1 ; renvoie le message à y envoyer."""
    chain = _chain(chain_id)
    agents = await _agents([s.agent for s in chain.stages], llm, catalog, make_env)
    names = {n: a.display_name for n, a in agents.items()}
    first = await conversations.create(chain.stages[0].agent, _title(chain, 0))
    stages = [
        StageState(
            agent=s.agent,
            role=s.role,
            status="active" if i == 0 else "pending",
            conversation_id=first.id if i == 0 else None,
        )
        for i, s in enumerate(chain.stages)
    ]
    run = await runs.create(chain.id, body.request.strip(), stages)
    return ChainStep(
        run=run,
        agent=chain.stages[0].agent,
        conversation_id=first.id,
        handoff=handoff_message(chain, run.request, run.stages, 0, names),
    )


@router.post("/chain-runs/{run_id}/advance", response_model=ChainStep)
async def advance(
    run_id: str,
    runs: RunsDep,
    conversations: ConvDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> ChainStep:
    """Valide le livrable de l'étape courante (figé tel qu'il est maintenant) et prépare la
    suivante, ou termine la chaîne avec un récapitulatif. 409 si l'étape n'est pas terminée."""
    run = await _run_or_404(runs, run_id)
    if run.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette chaîne n'est plus en cours.")
    chain = _chain(run.chain)
    index = run.stage_index
    stages = [s.model_copy(deep=True) for s in run.stages]
    current = stages[index]
    detail = await conversations.get(current.conversation_id or "")
    if detail is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La conversation de cette étape a été supprimée : arrêtez la chaîne et relancez-la.",
        )
    try:
        current.deliverable = deliverable_from(detail)
    except StageNotFinishedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    current.status = "validated"
    current.validated_at = datetime.now(UTC)

    agents = await _agents([s.agent for s in chain.stages], llm, catalog, make_env)
    names = {n: a.display_name for n, a in agents.items()}
    nxt = index + 1
    if nxt >= len(chain.stages):
        saved = await runs.save(run.id, status="completed", stage_index=index, stages=stages)
        assert saved is not None
        return ChainStep(run=saved, recap=recap_artifact(chain, run.request, stages, names))

    following = agents[chain.stages[nxt].agent]
    previous = [agents[s.agent] for s in chain.stages[:nxt]]
    if leaks_local_data(previous, following):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"« {following.display_name} » peut utiliser Claude : il ne peut pas recevoir le "
            "livrable d'un agent 100 % local.",
        )
    conversation = await conversations.create(chain.stages[nxt].agent, _title(chain, nxt))
    stages[nxt].status = "active"
    stages[nxt].conversation_id = conversation.id
    saved = await runs.save(run.id, status="running", stage_index=nxt, stages=stages)
    assert saved is not None
    return ChainStep(
        run=saved,
        agent=chain.stages[nxt].agent,
        conversation_id=conversation.id,
        handoff=handoff_message(chain, run.request, stages, nxt, names),
    )


@router.get("/chain-runs/{run_id}/recap", response_model=Artifact)
async def recap(
    run_id: str, runs: RunsDep, llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep
) -> Artifact:
    """Récapitulatif Markdown (demande + livrable validé de chaque étape), à tout moment."""
    run = await _run_or_404(runs, run_id)
    chain = _chain(run.chain)
    agents = await _agents([s.agent for s in chain.stages], llm, catalog, make_env)
    names = {n: a.display_name for n, a in agents.items()}
    return recap_artifact(chain, run.request, run.stages, names)


@router.post("/chain-runs/{run_id}/stop", response_model=ChainRun)
async def stop_run(run_id: str, runs: RunsDep) -> ChainRun:
    """Arrête la chaîne : l'étape courante et les suivantes ne seront pas jouées."""
    run = await _run_or_404(runs, run_id)
    if run.status != "running":
        return run
    stages = [s.model_copy(deep=True) for s in run.stages]
    for stage in stages[run.stage_index :]:
        if stage.status in ("pending", "active"):
            stage.status = "skipped"
    saved = await runs.save(run.id, status="stopped", stage_index=run.stage_index, stages=stages)
    assert saved is not None
    return saved
