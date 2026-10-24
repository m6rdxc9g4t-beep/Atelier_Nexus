"""Rituels de l'équipe : liste et installation (workflow v2 + déclencheur horaire).

L'installation passe par les mêmes contrôles que l'éditeur : graphe validé (`_check_v2`),
déclencheur vérifié (`TriggerService.check`). docs/equipe.md.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.triggers import ServiceDep, _checked, parse_fields
from app.api.workflows import _CREATE_V2, CatalogDep, EnvFactoryDep, LLMDep, _check_v2, _parse
from app.schemas.workflows_v2 import WorkflowV2
from app.team_rituals import RITUALS, Ritual, installed, ritual

router = APIRouter(prefix="/api/equipe", tags=["equipe"])


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
    titles = {w.title: w.id for w in await service.workflows.list() if isinstance(w, WorkflowV2)}
    done = installed(titles)
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
    current = {i.id: i for i in await _infos(service, make_env)}[ritual_id]
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
        await service.workflows.delete(workflow.id)  # jamais un rituel à moitié installé
        raise
    return _info(found, [], workflow.id)
