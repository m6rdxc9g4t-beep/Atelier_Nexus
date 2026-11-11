"""État des applications connectées (Viz / Data Via, Projets, Convert, Wiki, Formulaire,
Trésorerie, Tab, Ciné, Savoir, Cuisine, GitHub)."""

from __future__ import annotations

import asyncio
import time
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


#: État d'une application locale gardé en mémoire : l'interface relit tout toutes les 30 s
LOCAL_TTL = 25.0
#: Services en ligne (GitHub : 60 requêtes par heure sans jeton ; Supabase d'Atelier Cuisine) :
#: relus toutes les 10 minutes, une erreur toutes les minutes
ONLINE_TTL = 600.0
ONLINE_ERROR_TTL = 60.0
ONLINE_APPS = frozenset({"github", "cuisine"})

#: (application, ce qui la désigne) → (expiration, état). Jamais de client ni de secret ici.
_CACHE: dict[tuple[str, str], tuple[float, AppStatus]] = {}
_now = time.monotonic


def clear_status_cache() -> None:
    """Réglages enregistrés (`reload_settings`) : l'état est relu à la requête suivante."""
    _CACHE.clear()


class AppStatus(BaseModel):
    id: str
    label: str
    configured: bool
    available: bool
    base_url: str | None
    detail: str | None = None
    error: str | None = None


async def _probe(
    app_id: str,
    label: str,
    base_url: str | None,
    check: Callable[[], Awaitable[str]],
    *,
    refresh: bool = False,
) -> AppStatus:
    if not base_url:
        return AppStatus(id=app_id, label=label, configured=False, available=False, base_url=None)
    key = (app_id, base_url)
    cached = _CACHE.get(key)
    if cached and cached[0] > _now() and not refresh:
        return cached[1]
    try:
        detail = await asyncio.wait_for(check(), timeout=3)
        status = AppStatus(
            id=app_id,
            label=label,
            configured=True,
            available=True,
            base_url=base_url,
            detail=detail,
        )
    except (AppError, DataViaError, TimeoutError) as exc:
        message = str(exc) or "délai dépassé"
        status = AppStatus(
            id=app_id,
            label=label,
            configured=True,
            available=False,
            base_url=base_url,
            error=message,
        )
    if app_id not in ONLINE_APPS:
        ttl = LOCAL_TTL
    else:
        ttl = ONLINE_TTL if status.available else ONLINE_ERROR_TTL
    _CACHE[key] = (_now() + ttl, status)
    return status


@router.get("/status", response_model=list[AppStatus])
async def apps_status(make_env: EnvFactoryDep, refresh: bool = False) -> list[AppStatus]:
    """Vérifie chaque application en parallèle (3 s max chacune). Ne lève jamais.

    Chaque état est gardé en mémoire (25 s pour une application locale, 10 min pour GitHub et
    Atelier Cuisine, en ligne) ; `refresh=true` relit tout (bouton « Vérifier »)."""
    env = make_env()
    s = env.settings

    def probe(
        app_id: str, label: str, base_url: str | None, check: Callable[[], Awaitable[str]]
    ) -> Awaitable[AppStatus]:
        return _probe(app_id, label, base_url, check, refresh=refresh)

    async def viz() -> str:
        st = await env.data_via().status()
        if not st.available:
            raise DataViaError(st.error or "indisponible")
        return f"{st.datasets} jeu(x) de données"

    async def projets() -> str:
        await env.projets().health()
        return f"{len(await env.projets().projects())} projet(s)"

    def node(app: str) -> Callable[[], Awaitable[str]]:
        async def check() -> str:
            # Nœud atelier-node/1 : même garde de bouclage et même cache que les workflows
            st = await env.suite().state(app, fresh=True)
            if st.status == "ok" and st.manifest is not None:
                return (
                    f"{len(st.manifest.actions)} action(s), {len(st.manifest.events)} "
                    "événement(s) (nœud atelier-node/1)"
                )
            if st.status == "no_contract":
                return "en marche, sans manifeste atelier-node/1 (version antérieure au contrat)"
            raise AppUnavailableError(st.reason or "injoignable", app=app)

        return check

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
                probe("viz", "Atelier Viz (Data Via)", s.data_via_base_url, viz),
                probe("projets", "Atelier Projets", s.projets_base_url, projets),
                probe("convert", "Atelier Convert", s.convert_base_url, node("convert")),
                probe("wiki", "Atelier Wiki", s.wiki_base_url, node("wiki")),
                probe(
                    "formulaire", "Atelier Formulaire", s.formulaire_base_url, node("formulaire")
                ),
                probe("tresorerie", "Atelier Trésorerie", s.tresorerie_base_url, tresorerie),
                probe("tab", "Atelier Tab", s.tab_exports_dir, tab),
                probe("cine", "Atelier Ciné", s.cine_base_url, cine),
                probe("savoir", "Atelier Savoir", s.savoir_base_url, savoir),
                probe(
                    "cuisine",
                    "Atelier Cuisine",
                    s.cuisine_supabase_url if s.cuisine_configured else None,
                    cuisine,
                ),
                probe("github", "GitHub", ", ".join(s.github_repo_list) or None, github),
            )
        )
    finally:
        await env.aclose()
