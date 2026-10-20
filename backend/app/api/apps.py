"""État des applications connectées (Viz / Data Via, Projets, Trésorerie, GitHub)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_env_factory
from app.tools.data_via import DataViaError
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError

router = APIRouter(prefix="/api/apps", tags=["apps"])

EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]


class AppStatus(BaseModel):
    id: str
    label: str
    configured: bool
    available: bool
    base_url: str | None
    detail: str | None = None
    error: str | None = None


async def _probe(
    app_id: str, label: str, base_url: str | None, check: Callable[[], Awaitable[str]]
) -> AppStatus:
    if not base_url:
        return AppStatus(id=app_id, label=label, configured=False, available=False, base_url=None)
    try:
        detail = await asyncio.wait_for(check(), timeout=3)
        return AppStatus(
            id=app_id,
            label=label,
            configured=True,
            available=True,
            base_url=base_url,
            detail=detail,
        )
    except (AppError, DataViaError, TimeoutError) as exc:
        message = str(exc) or "délai dépassé"
        return AppStatus(
            id=app_id,
            label=label,
            configured=True,
            available=False,
            base_url=base_url,
            error=message,
        )


@router.get("/status", response_model=list[AppStatus])
async def apps_status(make_env: EnvFactoryDep) -> list[AppStatus]:
    """Vérifie chaque application en parallèle (3 s max chacune). Ne lève jamais."""
    env = make_env()
    s = env.settings

    async def viz() -> str:
        st = await env.data_via().status()
        if not st.available:
            raise DataViaError(st.error or "indisponible")
        return f"{st.datasets} jeu(x) de données"

    async def projets() -> str:
        await env.projets().health()
        return f"{len(await env.projets().projects())} projet(s)"

    async def tresorerie() -> str:
        await env.tresorerie().ping()
        return "en marche (données locales)"

    async def github() -> str:
        repo = await env.github().get_repo(None)
        return f"{repo.full_name} ({'jeton présent' if s.github_token else 'sans jeton : lecture publique'})"

    try:
        return list(
            await asyncio.gather(
                _probe("viz", "Atelier Viz (Data Via)", s.data_via_base_url, viz),
                _probe("projets", "Atelier Projets", s.projets_base_url, projets),
                _probe("tresorerie", "Atelier Trésorerie", s.tresorerie_base_url, tresorerie),
                _probe("github", "GitHub", ", ".join(s.github_repo_list) or None, github),
            )
        )
    finally:
        await env.aclose()
