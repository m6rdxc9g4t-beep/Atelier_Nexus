"""Endpoints d'exécution des agents (réponse complète ou flux SSE)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sse_starlette import EventSourceResponse

from app.agents import (
    AgentInfo,
    AgentResult,
    BaseAgent,
    describe,
    get_agent_class,
    list_agent_classes,
)
from app.api.errors import ErrorResponse, llm_error_body
from app.core.llm import LLMError, LLMRouter, Message, ProviderName, get_llm_router
from app.tools import ToolContext

router = APIRouter(prefix="/api/agents", tags=["agents"])

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Agent inconnu"},
    502: {"model": ErrorResponse, "description": "Requête refusée par le provider"},
    503: {"model": ErrorResponse, "description": "Provider non configuré ou indisponible"},
}


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1)
    provider: ProviderName | None = Field(
        default=None, description="anthropic | ollama ; vide = provider par défaut"
    )
    model: str | None = Field(default=None, description="Modèle du provider ; vide = défaut")
    conversation_id: str | None = None

    @model_validator(mode="after")
    def _ends_with_user(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("Le dernier message doit avoir le rôle « user ».")
        return self


def _build(agent_name: str, llm: LLMRouter, body: AgentRunRequest) -> BaseAgent:
    agent = get_agent_class(agent_name)(llm)
    llm.get_provider(body.provider)  # échoue tôt (HTTP 503) si non configuré
    return agent


@router.get("", response_model=list[AgentInfo])
async def list_agents(llm: LLMDep) -> list[AgentInfo]:
    return [describe(cls(llm)) for cls in list_agent_classes()]


@router.post("/{agent_name}/run", response_model=AgentResult, responses=_ERRORS)
async def run_agent(agent_name: str, body: AgentRunRequest, llm: LLMDep) -> AgentResult:
    agent = _build(agent_name, llm, body)
    return await agent.run(
        body.messages,
        provider=body.provider,
        model=body.model,
        context=ToolContext(conversation_id=body.conversation_id),
    )


@router.post("/{agent_name}/stream", responses=_ERRORS)
async def stream_agent(agent_name: str, body: AgentRunRequest, llm: LLMDep) -> EventSourceResponse:
    """Flux SSE. Événements : `text_delta`, `tool_call`, `tool_result`, `artifact`,
    `done` (résultat final) ou `error`. Le champ `data` est du JSON."""
    agent = _build(agent_name, llm, body)

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in agent.run_stream(
                body.messages,
                provider=body.provider,
                model=body.model,
                context=ToolContext(conversation_id=body.conversation_id),
            ):
                yield {"event": event.type, "data": event.model_dump_json()}
        except LLMError as exc:
            _, error = llm_error_body(exc)
            yield {"event": "error", "data": error.model_dump_json()}

    return EventSourceResponse(events())
