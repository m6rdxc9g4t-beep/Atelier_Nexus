"""Endpoints des agents : catalogue, exécution (complète ou SSE), validations, agents personnalisés."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sse_starlette import EventSourceResponse

from app.agents import (
    AgentCatalog,
    AgentInfo,
    AgentResult,
    BaseAgent,
    DoneEvent,
    builtin_names,
    describe,
)
from app.agents.base import ReviewAction, is_review_point
from app.api.deps import (
    get_attachment_repository,
    get_catalog,
    get_conversation_repository,
    get_custom_repository,
    get_env_factory,
    prepare_environment,
)
from app.api.errors import ErrorResponse, app_error_body, llm_error_body
from app.core.llm import LLMError, LLMRouter, Message, ProviderName, ToolUseBlock, get_llm_router
from app.core.llm.attachments import AttachmentContent, referenced_ids
from app.core.llm.types import ImageBlock
from app.db.attachments import AttachmentRepository
from app.db.conversations import ConversationRepository
from app.db.repository import CustomAgentRepository, StorageError
from app.schemas.agents import (
    ICONS,
    CustomAgentCreate,
    CustomAgentDefinition,
    CustomAgentUpdate,
)
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError
from app.tools.toolsets import ToolsetInfo, describe_toolsets

router = APIRouter(prefix="/api", tags=["agents"])
logger = logging.getLogger(__name__)

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]
EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RepoDep = Annotated[CustomAgentRepository, Depends(get_custom_repository)]
ConvDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
FilesDep = Annotated[AttachmentRepository, Depends(get_attachment_repository)]


async def _attachments(
    body: AgentRunRequest, files: AttachmentRepository
) -> dict[str, AttachmentContent]:
    """Contenu des pièces jointes citées par la conversation (503 si la base ne répond pas)."""
    ids = referenced_ids(body.messages)
    if not ids:
        return {}
    try:
        return await files.contents(ids)
    except StorageError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Pièces jointes indisponibles : {exc}"
        ) from exc


async def _check_conversation(
    body: AgentRunRequest, agent_name: str, conversations: ConversationRepository
) -> bool:
    """Vrai si le tour doit être enregistré. 404 / 409 si la conversation ne colle pas."""
    if not body.conversation_id:
        return False
    try:
        owner = await conversations.agent_of(body.conversation_id)
    except StorageError as exc:
        logger.warning("Historique indisponible, tour non enregistré : %s", exc)
        return False
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation introuvable.")
    if owner != agent_name:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cette conversation appartient à l'agent « {owner} »."
        )
    return True


async def _save(
    conversations: ConversationRepository, body: AgentRunRequest, result: AgentResult
) -> str | None:
    """Enregistre le tour ; renvoie un message d'erreur lisible en cas d'échec."""
    assert body.conversation_id
    try:
        await conversations.save_turn(body.conversation_id, list(body.messages), result)
        return None
    except StorageError as exc:
        logger.warning("Tour non enregistré : %s", exc)
        return str(exc)


_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorResponse,
        "description": "Moteur interdit pour cet agent (données locales)",
    },
    404: {"model": ErrorResponse, "description": "Agent inconnu"},
    502: {"model": ErrorResponse, "description": "Requête refusée par le provider"},
    503: {"model": ErrorResponse, "description": "Provider non configuré ou indisponible"},
}


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1)
    provider: ProviderName | None = Field(
        default=None, description="anthropic | ollama ; vide = moteur de l'agent ou par défaut"
    )
    model: str | None = Field(default=None, description="Modèle du provider ; vide = défaut")
    conversation_id: str | None = None
    approvals: dict[str, bool] | None = Field(
        default=None,
        description="Décisions sur les appels en attente (id → autorisé), pour reprendre un tour.",
    )
    review_results: bool = Field(
        default=False,
        description="Mode pas à pas : pause après chaque résultat d'outil, avant que le modèle "
        "ne l'interprète (stop_reason « awaiting_review »).",
    )
    review: ReviewAction | None = Field(
        default=None,
        description="Réponse à une pause de revue : « continue », ou « stop » pour finir le tour "
        "sans appeler le modèle. Pour corriger, joindre un texte aux résultats et continuer.",
    )

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if any(isinstance(b, ImageBlock) for m in self.messages for b in m.content):
            raise ValueError(
                "Les images se joignent par POST /api/attachments, puis un bloc "
                "« attachment » qui les cite."
            )
        last = self.messages[-1]
        if self.review is not None and not is_review_point(last):
            raise ValueError(
                "« review » répond à une pause : le dernier message doit contenir les résultats revus."
            )
        if last.role == "user":
            return self
        calls = [b for b in last.content if isinstance(b, ToolUseBlock)]
        if not calls or self.approvals is None:
            raise ValueError(
                "Le dernier message doit être « user », ou contenir des appels d'outils "
                "accompagnés de « approvals »."
            )
        return self


async def _build(
    name: str, body: AgentRunRequest, llm: LLMRouter, catalog: AgentCatalog, env: ToolEnvironment
) -> BaseAgent:
    await prepare_environment(env, llm, catalog)
    agent = await catalog.build(name, llm, env)
    provider = agent.resolve_provider(body.provider)  # 403 si Claude demandé pour un agent local
    llm.get_provider(provider)  # 503 si le moteur n'est pas configuré
    return agent


# ─── Catalogue ────────────────────────────────────────────────────


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents(llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep) -> list[AgentInfo]:
    env = make_env()
    try:
        await prepare_environment(env, llm, catalog)
        return await catalog.infos(llm, env)
    finally:
        await env.aclose()


class EditorOptions(BaseModel):
    icons: list[str]
    toolsets: list[ToolsetInfo]
    reserved_names: list[str]


@router.get("/toolsets", response_model=EditorOptions, tags=["agents"])
async def editor_options(make_env: EnvFactoryDep) -> EditorOptions:
    """Ce que l'éditeur d'agents propose : icônes, boîtes à outils (avec état), noms réservés."""
    env = make_env()
    try:
        return EditorOptions(
            icons=list(ICONS),
            toolsets=describe_toolsets(env),
            reserved_names=sorted(builtin_names()),
        )
    finally:
        await env.aclose()


# ─── Exécution ────────────────────────────────────────────────────


@router.post("/agents/{agent_name}/run", response_model=AgentResult, responses=_ERRORS)
async def run_agent(
    agent_name: str,
    body: AgentRunRequest,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
    conversations: ConvDep,
    files: FilesDep,
) -> AgentResult:
    save = await _check_conversation(body, agent_name, conversations)
    attachments = await _attachments(body, files)
    env = make_env()
    try:
        agent = await _build(agent_name, body, llm, catalog, env)
        result = await agent.run(
            body.messages,
            provider=body.provider,
            model=body.model,
            context=ToolContext(conversation_id=body.conversation_id),
            approvals=body.approvals,
            attachments=attachments,
            review_results=body.review_results,
            review=body.review,
        )
    finally:
        await env.aclose()
    if save:
        await _save(conversations, body, result)
    return result


@router.post("/agents/{agent_name}/stream", responses=_ERRORS)
async def stream_agent(
    agent_name: str,
    body: AgentRunRequest,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
    conversations: ConvDep,
    files: FilesDep,
) -> EventSourceResponse:
    """Flux SSE. Événements : `text_delta`, `tool_call`, `tool_result`, `artifact`,
    `approval_required`, `review_required` (mode pas à pas), `done` (résultat final), `saved` / `save_error` (historique) ou
    `error`. Le champ `data` est du JSON."""
    save = await _check_conversation(body, agent_name, conversations)
    attachments = await _attachments(body, files)
    env = make_env()
    try:
        agent = await _build(agent_name, body, llm, catalog, env)
    except BaseException:
        await env.aclose()
        raise

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in agent.run_stream(
                body.messages,
                provider=body.provider,
                model=body.model,
                context=ToolContext(conversation_id=body.conversation_id),
                approvals=body.approvals,
                attachments=attachments,
                review_results=body.review_results,
                review=body.review,
            ):
                yield {"event": event.type, "data": event.model_dump_json()}
                if save and isinstance(event, DoneEvent):
                    problem = await _save(conversations, body, event.result)
                    if problem:
                        yield {"event": "save_error", "data": json.dumps({"message": problem})}
                    else:
                        yield {
                            "event": "saved",
                            "data": json.dumps({"conversation_id": body.conversation_id}),
                        }
        except LLMError as exc:
            _, error = llm_error_body(exc)
            yield {"event": "error", "data": error.model_dump_json()}
        except AppError as exc:
            _, error = app_error_body(exc)
            yield {"event": "error", "data": error.model_dump_json()}
        finally:
            await env.aclose()

    return EventSourceResponse(events())


# ─── Agents personnalisés ─────────────────────────────────────────


def _reserved(name: str) -> None:
    if name in builtin_names():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"« {name} » est le nom d'un agent fourni : choisissez-en un autre.",
        )


@router.get("/custom-agents", response_model=list[CustomAgentDefinition])
async def list_custom_agents(repo: RepoDep) -> list[CustomAgentDefinition]:
    return await repo.list()


@router.post("/custom-agents", response_model=AgentInfo, status_code=status.HTTP_201_CREATED)
async def create_custom_agent(
    body: CustomAgentCreate,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> AgentInfo:
    _reserved(body.name)
    await repo.create(body)
    return await _info(body.name, llm, catalog, make_env)


@router.get("/custom-agents/{name}", response_model=CustomAgentDefinition)
async def get_custom_agent(name: str, repo: RepoDep) -> CustomAgentDefinition:
    definition = await repo.get(name)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Agent personnalisé « {name} » introuvable."
        )
    return definition


@router.put("/custom-agents/{name}", response_model=AgentInfo)
async def update_custom_agent(
    name: str,
    body: CustomAgentUpdate,
    repo: RepoDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> AgentInfo:
    if await repo.update(name, body) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Agent personnalisé « {name} » introuvable."
        )
    return await _info(name, llm, catalog, make_env)


@router.delete("/custom-agents/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_agent(name: str, repo: RepoDep) -> Response:
    if not await repo.delete(name):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Agent personnalisé « {name} » introuvable."
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _info(
    name: str, llm: LLMRouter, catalog: AgentCatalog, make_env: Callable[[], ToolEnvironment]
) -> AgentInfo:
    env = make_env()
    try:
        await prepare_environment(env, llm, catalog)
        return describe(await catalog.build(name, llm, env))
    finally:
        await env.aclose()
