"""État des applications connectées (Viz / Data Via, Projets, Convert, Trésorerie, Tab, Ciné,
Savoir, Cuisine, GitHub)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_env_factory
from app.tools.data_via import DataViaError
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError, AppUnavailableError

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

    async def convert() -> str:
        # Nœud atelier-node/1 : même garde de bouclage et même cache que les workflows
        st = await env.suite().state("convert", fresh=True)
        if st.status == "ok" and st.manifest is not None:
            return (
                f"{len(st.manifest.actions)} action(s), {len(st.manifest.events)} événement(s) "
                "(nœud atelier-node/1)"
            )
        if st.status == "no_contract":
            return "en marche, sans manifeste atelier-node/1 (version antérieure au contrat)"
        raise AppUnavailableError(st.reason or "injoignable", app="convert")

    async def tresorerie() -> str:
        await env.tresorerie().ping()
        return "en marche (données locales)"

    async def tab() -> str:
        tables, _ = await env.tab().tables()
        return f"{len(tables)} table(s) publiée(s)"

    async def cine() -> str:
        health = await env.cine().health()
        lib = await env.cine().library()
        return f"v{health.version} : {len(lib.movies)} film(s), {len(lib.shows)} série(s)"

    async def savoir() -> str:
        st = await env.savoir().stats()
        return f"{st.courses} cours, {st.cards} carte(s), {st.due} à réviser (données locales)"

    async def cuisine() -> str:
        # App en ligne : on interroge Supabase (jamais l'adresse Vercel de l'interface)
        items = await env.cuisine().pantry()
        today = env.cuisine().today()
        soon = sum(1 for i in items if i.expires_on and (i.expires_on - today).days <= 3)
        return f"{len(items)} produit(s) en stock, {soon} à finir en premier (en ligne)"

    async def github() -> str:
        repo = await env.github().get_repo(None)
        return f"{repo.full_name} ({'jeton présent' if s.github_token else 'sans jeton : lecture publique'})"

    try:
        return list(
            await asyncio.gather(
                _probe("viz", "Atelier Viz (Data Via)", s.data_via_base_url, viz),
                _probe("projets", "Atelier Projets", s.projets_base_url, projets),
                _probe("convert", "Atelier Convert", s.convert_base_url, convert),
                _probe("tresorerie", "Atelier Trésorerie", s.tresorerie_base_url, tresorerie),
                _probe("tab", "Atelier Tab", s.tab_exports_dir, tab),
                _probe("cine", "Atelier Ciné", s.cine_base_url, cine),
                _probe("savoir", "Atelier Savoir", s.savoir_base_url, savoir),
                _probe(
                    "cuisine",
                    "Atelier Cuisine",
                    s.cuisine_supabase_url if s.cuisine_configured else None,
                    cuisine,
                ),
                _probe("github", "GitHub", ", ".join(s.github_repo_list) or None, github),
            )
        )
    finally:
        await env.aclose()
