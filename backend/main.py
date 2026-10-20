"""Point d'entrée FastAPI — Atelier Nexus."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api import agents, apps, data_via, llm
from app.api.errors import register_error_handlers
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("atelier_nexus")


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).with_name("alembic.ini")))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.db_auto_migrate:
        try:
            await asyncio.to_thread(_migrate)
        except Exception as exc:  # la base est facultative : les agents experts restent utilisables
            logger.warning(
                "Migrations non appliquées (agents personnalisés indisponibles) : %s", exc
            )
    yield


app = FastAPI(
    title="Atelier Nexus API",
    version="0.5.0",
    description="Orchestration des agents IA et connecteurs de la suite Atelier.",
    lifespan=lifespan,
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
app.include_router(apps.router)
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
