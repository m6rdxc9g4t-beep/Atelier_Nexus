"""Réglages de Nexus depuis l'interface (clé Claude, modèles, adresses des apps, GitHub).

Écrit le `.env` lu par `Settings` puis recharge la configuration à chaud : routeur LLM et
connecteurs utilisent les nouvelles valeurs dès la requête suivante. Réservé à l'interface
de Nexus : un appel venant d'une autre origine est refusé.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.llm.router import get_llm_router
from app.core.settings_editor import (
    SettingsError,
    SettingsUpdate,
    SettingsView,
    env_file_path,
    validate_changes,
    view,
    write_env_file,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def same_origin_only(
    origin: Annotated[str | None, Header()] = None, host: Annotated[str | None, Header()] = None
) -> None:
    """Interface de Nexus (origines CORS déclarées ou même origine) ; sans Origin : client local."""
    if origin is None:
        return
    allowed = set(get_settings().cors_origin_list)
    if host:
        allowed |= {f"http://{host}", f"https://{host}"}
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Réglages réservés à l'interface de Nexus.")


Guard = Annotated[None, Depends(same_origin_only)]


def reload_settings() -> None:
    """Configuration relue à la requête suivante (réglages, routeur LLM et ses clients)."""
    get_settings.cache_clear()
    get_llm_router.cache_clear()


@router.get("", response_model=SettingsView)
async def read_settings(_: Guard) -> SettingsView:
    return view(get_settings(), env_file_path())


@router.put("", response_model=SettingsView, responses={422: {"description": "Réglage refusé"}})
async def update_settings(update: SettingsUpdate, _: Guard) -> SettingsView | JSONResponse:
    try:
        changes = validate_changes(update, get_settings())
    except SettingsError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "invalid_settings", "message": str(exc), "fields": exc.fields}
            },
        )
    path = env_file_path()
    try:
        await asyncio.to_thread(write_env_file, path, changes)
    except OSError as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "settings_not_saved",
                    "message": f"Écriture impossible ({path}) : {exc}",
                }
            },
        )
    reload_settings()
    return view(get_settings(), path)
