"""Point d'entrée FastAPI — Atelier Nexus."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api import agents, data_via, llm
from app.api.errors import register_error_handlers
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Atelier Nexus API",
    version="0.3.0",
    description="Orchestration des agents IA et connecteurs de la suite Atelier.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(llm.router)
app.include_router(agents.router)
app.include_router(data_via.router)


class HealthResponse(BaseModel):
    status: str
    env: str
    llm_default_provider: str


@app.get("/health", response_model=HealthResponse, tags=["system"])
# Convention de la suite Atelier (docs/SUITE.md) : santé sur /api/health
@app.get("/api/health", response_model=HealthResponse, tags=["system"], include_in_schema=False)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        env=settings.app_env,
        llm_default_provider=settings.llm_default_provider,
    )
