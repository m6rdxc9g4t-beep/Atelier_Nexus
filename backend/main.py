"""Point d'entrée FastAPI — Atelier Nexus."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.api import agents, apps, attachments, conversations, data_via, llm
from app.api import settings as settings_api
from app.api.deps import get_attachment_repository
from app.api.errors import register_error_handlers
from app.core.config import get_settings
from app.db.repository import StorageError

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
    try:  # envois abandonnés : pièces jointes jamais rattachées à une conversation
        purged = await get_attachment_repository().purge_orphans()
        if purged:
            logger.info("%d pièce(s) jointe(s) abandonnée(s) supprimée(s)", purged)
    except StorageError as exc:
        logger.debug("Nettoyage des pièces jointes ignoré : %s", exc)
    yield


app = FastAPI(
    title="Atelier Nexus API",
    version=__version__,
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
app.include_router(conversations.router)
app.include_router(attachments.router)
app.include_router(data_via.router)
app.include_router(settings_api.router)


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


# Application de bureau : le backend sert aussi l'interface compilée (NEXUS_EXPORT=1), en dernier
# pour que les routes /api gardent la priorité. Voir app/desktop.py et scripts/macos/build_app.sh.
if settings.frontend_dist and (Path(settings.frontend_dist) / "index.html").is_file():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="interface")
