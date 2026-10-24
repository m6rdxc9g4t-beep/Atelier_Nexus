"""Rituels de l'équipe : liste et installation (workflow v2 + déclencheur horaire).

L'installation passe par les mêmes contrôles que l'éditeur : graphe validé (`_check_v2`),
déclencheur vérifié (`TriggerService.check`). docs/equipe.md.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.triggers import ServiceDep, _checked, parse_fields
from app.api.workflows import _CREATE_V2, CatalogDep, EnvFactoryDep, LLMDep, _check_v2, _parse
from app.schemas.workflows_v2 import WorkflowV2
from app.team_rituals import RITUALS, Ritual, installed, ritual

router = APIRouter(prefix="/api/equipe", tags=["equipe"])

#: Contrôle « déjà installé » et création sous le même verrou : deux clics simultanés
#: n'installent pas deux fois le même rituel (un seul processus backend).
_INSTALL_LOCK = asyncio.Lock()


class RitualInfo(BaseModel):
    id: str
    title: str
    description: str
    when: str
    #: Applications nécessaires absentes de cette installation (vide = installable)
    missing: list[str]
    workflow_id: str | None


async def _infos(service: Any, make_env: Any) -> list[RitualInfo]:
    env = make_env()
    try:
        settings = env.settings
    finally:
        await env.aclose()
    done = installed(
        [
            (w.id, w.description or "")
            for w in await service.workflows.list()
            if isinstance(w, WorkflowV2)
        ]
    )
    return [_info(r, r.missing(settings), done.get(r.id)) for r in RITUALS]


def _info(r: Ritual, missing: list[str], workflow_id: str | None) -> RitualInfo:
    return RitualInfo(
        id=r.id,
        title=r.title,
        description=r.description,
        when=r.when,
        missing=missing,
        workflow_id=workflow_id,
    )


@router.get("/rituels", response_model=list[RitualInfo])
async def list_rituals(service: ServiceDep, make_env: EnvFactoryDep) -> list[RitualInfo]:
    """Rituels proposés, installés ou non, et ce qui manque pour les installer."""
    return await _infos(service, make_env)


@router.post("/rituels/{ritual_id}", response_model=RitualInfo, status_code=status.HTTP_201_CREATED)
async def install_ritual(
    ritual_id: str,
    service: ServiceDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> RitualInfo:
    """Crée le workflow du rituel et son déclencheur horaire. 409 s'il est déjà installé ;
    422 si une application nécessaire n'est pas configurée."""
    found = ritual(ritual_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rituel « {ritual_id} » inconnu.")
    async with _INSTALL_LOCK:
        return await _install(found, service, llm, catalog, make_env)


async def _install(
    found: Ritual, service: Any, llm: Any, catalog: Any, make_env: Any
) -> RitualInfo:
    current = {i.id: i for i in await _infos(service, make_env)}[found.id]
    if current.workflow_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Le rituel « {found.title} » est déjà installé."
        )
    if current.missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"À configurer d'abord (roue dentée → Applications Atelier) : {', '.join(current.missing)}.",
        )
    body = _parse(_CREATE_V2, found.workflow)
    await _check_v2(body, llm, catalog, make_env)
    workflow = await service.workflows.create(body)
    assert isinstance(workflow, WorkflowV2)
    try:
        fields = parse_fields(found.trigger)
        note = await _checked(service, workflow, fields)
        state, internal = await service.initial_state(fields, note)
        await service.triggers.create(workflow.id, fields, state, internal)
    except Exception:
        # Jamais un rituel à moitié installé ; l'erreur d'origine reste celle rendue
        with contextlib.suppress(Exception):
            await service.workflows.delete(workflow.id)
        raise
    return _info(found, [], workflow.id)
