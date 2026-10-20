"""Traduction des erreurs métier en réponses HTTP homogènes."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agents import AgentNotFoundError
from app.core.llm import (
    LLMError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderUnavailableError,
)


class ErrorBody(BaseModel):
    code: str
    message: str
    provider: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def llm_error_body(exc: LLMError) -> tuple[int, ErrorBody]:
    if isinstance(exc, ProviderNotConfiguredError):
        status, code = 503, "provider_not_configured"
    elif isinstance(exc, ProviderUnavailableError):
        status, code = 503, "provider_unavailable"
    elif isinstance(exc, ProviderRequestError):
        status, code = 502, "provider_request_error"
    else:
        status, code = 500, "llm_error"
    return status, ErrorBody(code=code, message=str(exc), provider=exc.provider)


def _json(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=body).model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMError)
    async def _llm(_: Request, exc: LLMError) -> JSONResponse:
        return _json(*llm_error_body(exc))

    @app.exception_handler(AgentNotFoundError)
    async def _agent(_: Request, exc: AgentNotFoundError) -> JSONResponse:
        return _json(404, ErrorBody(code="agent_not_found", message=f"Agent inconnu : {exc}"))
