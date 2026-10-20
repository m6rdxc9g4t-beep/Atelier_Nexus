"""Historique : conversations par agent, avec leurs artefacts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.agents import AgentCatalog, AgentNotFoundError
from app.agents.registry import builtin_names
from app.api.deps import get_catalog, get_conversation_repository
from app.db.conversations import ConversationRepository
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationSummary,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

RepoDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]


def _not_found(conversation_id: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, f"Conversation « {conversation_id} » introuvable."
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    repo: RepoDep,
    agent: Annotated[str | None, Query(max_length=41)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConversationSummary]:
    """Les plus récentes d'abord ; filtre facultatif par agent."""
    return await repo.recent(agent, limit)


@router.post("", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, repo: RepoDep, catalog: CatalogDep
) -> ConversationDetail:
    if body.agent not in builtin_names() and (
        catalog.custom is None or await catalog.custom.get(body.agent) is None
    ):
        raise AgentNotFoundError(body.agent)
    return await repo.create(body.agent, body.title)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, repo: RepoDep) -> ConversationDetail:
    detail = await repo.get(conversation_id)
    if detail is None:
        raise _not_found(conversation_id)
    return detail


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def rename_conversation(
    conversation_id: str, body: ConversationRename, repo: RepoDep
) -> ConversationDetail:
    detail = await repo.rename(conversation_id, body.title.strip())
    if detail is None:
        raise _not_found(conversation_id)
    return detail


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, repo: RepoDep) -> Response:
    if not await repo.delete(conversation_id):
        raise _not_found(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
