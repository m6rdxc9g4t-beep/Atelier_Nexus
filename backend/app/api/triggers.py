"""Déclencheurs de workflows v2 (contrat figé : docs/declencheurs-api.md §2).

| Méthode | Chemin | Rôle |
|---|---|---|
| GET / POST | `/api/workflows/{id}/triggers` | Liste, création (201) |
| PUT / DELETE | `/api/triggers/{trigger_id}` | Modification (compteurs conservés), suppression (204) |
| POST | `/api/triggers/{trigger_id}/test` | Lance une fois maintenant (`{event?}`) → `WorkflowRun` |
| GET | `/api/triggers/events-catalog` | Événements des manifestes et chemins proposés aux filtres |

Erreurs de validation : 422 avec un `detail` texte en français. La boîte « À valider »
(`/api/workflow-runs?status=…`, `/api/workflow-runs/inbox-count`) est dans `app/api/workflows.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import TypeAdapter, ValidationError

from app.agents import AgentCatalog, AgentNotFoundError
from app.api.deps import (
    get_catalog,
    get_env_factory,
    get_trigger_repository,
    get_workflow_repository,
)
from app.core.config import get_settings
from app.core.llm import LLMRouter, get_llm_router
from app.db.triggers import AnyFields, AnyTrigger, StoredTrigger, TriggerRepository
from app.db.workflows import WorkflowRepository
from app.schemas.triggers import EventsCatalog, Trigger, TriggerFields, TriggerTestRequest
from app.schemas.workflows_v2 import WorkflowRun, WorkflowV2
from app.tools.environment import ToolEnvironment
from app.triggers.service import Clock, TriggerDeps, TriggerService, trigger_lock, utc_now
from app.workflows import WorkflowError

router = APIRouter(tags=["triggers"])

_FIELDS: TypeAdapter[AnyFields] = TypeAdapter(TriggerFields)
#: Champs en lecture seule acceptés dans le corps et ignorés (le frontend renvoie un `Trigger`)
READ_ONLY = ("id", "workflow_id", "created_at", "updated_at", "state")
KIND_TAGS = {"schedule", "event"}
SCHEDULE_TAGS = {"interval", "daily"}


def get_trigger_clock() -> Clock:
    """Horloge des calculs d'horaire (surchargeable dans les tests)."""
    return utc_now


def get_trigger_service(
    triggers: Annotated[TriggerRepository, Depends(get_trigger_repository)],
    workflows: Annotated[WorkflowRepository, Depends(get_workflow_repository)],
    make_env: Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)],
    llm: Annotated[LLMRouter, Depends(get_llm_router)],
    catalog: Annotated[AgentCatalog, Depends(get_catalog)],
    clock: Annotated[Clock, Depends(get_trigger_clock)],
) -> TriggerService:
    return TriggerService(
        TriggerDeps(
            triggers=triggers,
            workflows=workflows,
            make_env=make_env,
            llm=lambda: llm,
            catalog=lambda: catalog,
            settings=get_settings,
        ),
        clock=clock,
    )


ServiceDep = Annotated[TriggerService, Depends(get_trigger_service)]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _trigger_not_found(trigger_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Déclencheur « {trigger_id} » introuvable.")


# ─── Erreurs de validation en français ────────────────────────────


def _where(loc: tuple[int | str, ...]) -> str:
    parts = list(loc)
    if parts and parts[0] in KIND_TAGS:
        parts = parts[1:]  # étiquette de l'union (kind)
    if len(parts) >= 2 and parts[0] == "schedule" and parts[1] in SCHEDULE_TAGS:
        parts = [parts[0], *parts[2:]]
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "corps"


def _french(error: Any) -> str:
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    msg = str(error.get("msg", ""))
    messages = {
        "missing": "champ obligatoire",
        "extra_forbidden": "champ inconnu",
        "greater_than_equal": f"doit être supérieur ou égal à {ctx.get('ge')}",
        "less_than_equal": f"doit être inférieur ou égal à {ctx.get('le')}",
        "too_short": f"au moins {ctx.get('min_length')} élément(s)",
        "too_long": f"au plus {ctx.get('max_length')} élément(s)",
        "string_too_long": f"au plus {ctx.get('max_length')} caractères",
        "string_type": "texte attendu",
        "int_type": "nombre entier attendu",
        "int_parsing": "nombre entier attendu",
        "int_from_float": "nombre entier attendu",
        "bool_type": "booléen attendu",
        "bool_parsing": "booléen attendu",
        "list_type": "liste attendue",
        "dict_type": "objet attendu",
        "model_type": "objet attendu",
        "model_attributes_type": "objet attendu",
        "literal_error": f"valeur attendue : {ctx.get('expected')}",
        "union_tag_not_found": "champ « kind » obligatoire (schedule ou event)",
        "union_tag_invalid": (
            f"« {ctx.get('tag')} » inconnu (attendu : {ctx.get('expected_tags')})"
        ),
    }
    if kind == "value_error":
        return msg.removeprefix("Value error, ")
    return messages.get(kind, "valeur invalide")


def parse_fields(body: dict[str, Any]) -> AnyFields:
    """Corps d'un déclencheur ; 422 avec un message en français."""
    data = {k: v for k, v in body.items() if k not in READ_ONLY}
    try:
        return _FIELDS.validate_python(data)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        details = " ; ".join(f"{_where(tuple(e['loc']))} : {_french(e)}" for e in errors[:5])
        more = f" (+{len(errors) - 5})" if len(errors) > 5 else ""
        raise _unprocessable(f"Déclencheur invalide — {details}{more}.") from exc


async def _workflow_v2(workflows: WorkflowRepository, workflow_id: str) -> WorkflowV2:
    workflow = await workflows.get(workflow_id)
    if workflow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow « {workflow_id} » introuvable.")
    if not isinstance(workflow, WorkflowV2):
        raise _unprocessable(
            "Les déclencheurs ne s'appliquent qu'aux workflows v2 : convertissez d'abord ce "
            "workflow (POST /api/workflows/{id}/convert)."
        )
    return workflow


async def _checked(service: TriggerService, workflow: WorkflowV2, fields: AnyFields) -> str | None:
    problems, note = await service.check(workflow, fields)
    if problems:
        raise _unprocessable(" ".join(problems))
    return note


async def _fresh(service: TriggerService, items: list[StoredTrigger]) -> list[AnyTrigger]:
    """Déclencheurs avec le statut actuel de leur dernière exécution (reprise entre-temps)."""
    ids = [s.trigger.state.last_run_id for s in items if s.trigger.state.last_run_id]
    statuses = await service.workflows.run_statuses(ids)
    out = []
    for stored in items:
        trigger = stored.trigger
        run_id = trigger.state.last_run_id
        if run_id and run_id in statuses:
            trigger.state.last_run_status = statuses[run_id]
        out.append(trigger)
    return out


# ─── Routes ───────────────────────────────────────────────────────


@router.get("/api/workflows/{workflow_id}/triggers", response_model=list[Trigger])
async def list_triggers(workflow_id: str, service: ServiceDep) -> list[AnyTrigger]:
    """Déclencheurs du workflow, du plus ancien au plus récent."""
    if await service.workflows.get(workflow_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow « {workflow_id} » introuvable.")
    return await _fresh(service, await service.triggers.list(workflow_id))


@router.post(
    "/api/workflows/{workflow_id}/triggers",
    response_model=Trigger,
    status_code=status.HTTP_201_CREATED,
)
async def create_trigger(
    workflow_id: str, service: ServiceDep, body: Annotated[dict[str, Any], Body()]
) -> AnyTrigger:
    """Crée un déclencheur : `next_fire_at` calculé (horaire), curseur = dernier événement
    connu de l'application (événement : rien d'antérieur n'est vu)."""
    workflow = await _workflow_v2(service.workflows, workflow_id)
    fields = parse_fields(body)
    note = await _checked(service, workflow, fields)
    state, internal = await service.initial_state(fields, note)
    stored = await service.triggers.create(workflow.id, fields, state, internal)
    return stored.trigger


@router.get("/api/triggers/events-catalog", response_model=EventsCatalog)
async def events_catalog(service: ServiceDep) -> EventsCatalog:
    """Événements déclarés par les manifestes de Viz, Projets et Tab ; `fields` = chemins
    proposés pour les filtres (`data.x` du `data_schema`, puis `subject.id`, `subject.label`)."""
    return await service.events_catalog()


@router.put("/api/triggers/{trigger_id}", response_model=Trigger)
async def update_trigger(
    trigger_id: str, service: ServiceDep, body: Annotated[dict[str, Any], Body()]
) -> AnyTrigger:
    """Modifie (même corps qu'à la création) : compteurs conservés, `next_fire_at` recalculé."""
    current = await service.triggers.get(trigger_id)
    if current is None:
        raise _trigger_not_found(trigger_id)
    workflow = await _workflow_v2(service.workflows, current.trigger.workflow_id)
    fields = parse_fields(body)
    note = await _checked(service, workflow, fields)
    async with trigger_lock(trigger_id):  # jamais au milieu d'un lancement de ce déclencheur
        current = await service.triggers.get(trigger_id)
        if current is None:
            raise _trigger_not_found(trigger_id)
        state, internal = await service.initial_state(fields, note, current)
        stored = await service.triggers.update(trigger_id, fields, state, internal)
    if stored is None:
        raise _trigger_not_found(trigger_id)
    return (await _fresh(service, [stored]))[0]


@router.delete("/api/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(trigger_id: str, service: ServiceDep) -> Response:
    """Supprime le déclencheur ; ses exécutions passées restent dans l'historique."""
    async with trigger_lock(trigger_id):
        deleted = await service.triggers.delete(trigger_id)
    if not deleted:
        raise _trigger_not_found(trigger_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/triggers/{trigger_id}/test", response_model=WorkflowRun)
async def test_trigger(
    trigger_id: str,
    service: ServiceDep,
    body: Annotated[TriggerTestRequest | None, Body()] = None,
) -> WorkflowRun:
    """Lance une fois maintenant comme le ferait le déclencheur (origine `test`), avec un
    événement d'exemple facultatif pour les gabarits `{{event.…}}`. Une écriture s'arrête sur
    `awaiting_approval`, comme toujours."""
    try:
        run = await service.test(trigger_id, body.event if body else None)
    except WorkflowError as exc:
        raise _unprocessable(str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"L'agent de ce workflow n'existe plus ({exc})."
        ) from exc
    if run is None:
        raise _trigger_not_found(trigger_id)
    return run
