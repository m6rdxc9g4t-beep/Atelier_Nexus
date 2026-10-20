"""Traduction des erreurs métier en réponses HTTP homogènes :
`{"error": {"code", "message", "provider"}}`."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agents import AgentNotFoundError
from app.core.llm import (
    LLMError,
    ProviderNotAllowedError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.db.repository import DuplicateAgentError, StorageError
from app.tools.data_via import (
    DataViaError,
    DataViaNotConfiguredError,
    DataViaNotFoundError,
    DataViaUnavailableError,
)
from app.tools.http import (
    AppError,
    AppNotConfiguredError,
    AppNotFoundError,
    AppUnavailableError,
)


class ErrorBody(BaseModel):
    code: str
    message: str
    provider: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def llm_error_body(exc: LLMError) -> tuple[int, ErrorBody]:
    if isinstance(exc, ProviderNotAllowedError):
        status, code = 403, "provider_not_allowed"
    elif isinstance(exc, ProviderNotConfiguredError):
        status, code = 503, "provider_not_configured"
    elif isinstance(exc, ProviderUnavailableError):
        status, code = 503, "provider_unavailable"
    elif isinstance(exc, ProviderRequestError):
        status, code = 502, "provider_request_error"
    else:
        status, code = 500, "llm_error"
    return status, ErrorBody(code=code, message=str(exc), provider=exc.provider)


def data_via_error_body(exc: DataViaError) -> tuple[int, ErrorBody]:
    if isinstance(exc, DataViaNotConfiguredError):
        status, code = 503, "data_via_not_configured"
    elif isinstance(exc, DataViaUnavailableError):
        status, code = 503, "data_via_unavailable"
    elif isinstance(exc, DataViaNotFoundError):
        status, code = 404, "data_via_not_found"
    else:
        status, code = 422, "data_via_request_error"
    return status, ErrorBody(code=code, message=str(exc), provider="data_via")


def app_error_body(exc: AppError) -> tuple[int, ErrorBody]:
    if isinstance(exc, AppNotConfiguredError):
        status, suffix = 503, "not_configured"
    elif isinstance(exc, AppUnavailableError):
        status, suffix = 503, "unavailable"
    elif isinstance(exc, AppNotFoundError):
        status, suffix = 404, "not_found"
    else:
        status, suffix = 422, "request_error"
    return status, ErrorBody(code=f"{exc.app}_{suffix}", message=str(exc), provider=exc.app)


def _json(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=body).model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMError)
    async def _llm(_: Request, exc: LLMError) -> JSONResponse:
        return _json(*llm_error_body(exc))

    @app.exception_handler(AgentNotFoundError)
    async def _agent(_: Request, exc: AgentNotFoundError) -> JSONResponse:
        return _json(404, ErrorBody(code="agent_not_found", message=f"Agent inconnu : {exc}"))

    @app.exception_handler(DataViaError)
    async def _data_via(_: Request, exc: DataViaError) -> JSONResponse:
        return _json(*data_via_error_body(exc))

    @app.exception_handler(AppError)
    async def _app(_: Request, exc: AppError) -> JSONResponse:
        return _json(*app_error_body(exc))

    @app.exception_handler(StorageError)
    async def _storage(_: Request, exc: StorageError) -> JSONResponse:
        return _json(503, ErrorBody(code="storage_unavailable", message=str(exc)))

    @app.exception_handler(DuplicateAgentError)
    async def _duplicate(_: Request, exc: DuplicateAgentError) -> JSONResponse:
        return _json(
            409, ErrorBody(code="agent_exists", message=f"Un agent « {exc} » existe déjà.")
        )
