"""Exemples de la suite (docs/exemples-suite.md) : une histoire fictive suivie d'une application
à l'autre ; ici, ses workflows.

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/exemples-suite` | Histoires, parcours, workflows d'exemple déjà créés |
| POST | `/api/exemples-suite/{histoire}` | Crée (ou recrée) les workflows de l'histoire |
| DELETE | `/api/exemples-suite/{histoire}` | Retire ses workflows (et leurs déclencheurs) |

Charger copie les modèles de la bibliothèque en workflows (rien n'est lancé) avec les
paramètres de l'histoire, résolus dans les applications quand elles répondent : id du jeu Viz
(clé `exemple:<histoire>:…`), n° de la story Projets ; puis ajoute le déclencheur de l'alerte
Viz. Si le serveur MCP de Tab est configuré, le projet de l'histoire est aussi chargé dans les
fichiers de Tab (outil `load_suite_example`) : la conversion envoyée par le premier workflow y
trouve son projet. Une application arrêtée ne fait jamais échouer la route : la réponse le dit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_env_factory, get_workflow_repository
from app.api.triggers import ServiceDep, parse_fields
from app.api.workflows import CatalogDep, LLMDep, _check_v2
from app.core.config import get_settings
from app.db.repository import StorageError
from app.db.workflows import WorkflowRepository
from app.examples import (
    ALERT_TEMPLATE,
    ExampleError,
    Resolved,
    alert_trigger,
    dataset_id,
    folder,
    mark_of,
    part,
    project_id,
    stories,
    story_id,
    workflow_body,
)
from app.schemas.workflows_v2 import WorkflowV2
from app.suite.manifest import ManifestError
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError
from app.triggers.service import TriggerService
from app.workflows_v2.library import TEMPLATES

router = APIRouter(prefix="/api/exemples-suite", tags=["exemples"])
logger = logging.getLogger(__name__)

EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RepoDep = Annotated[WorkflowRepository, Depends(get_workflow_repository)]
#: Erreurs « application injoignable ou en désaccord » : dites en clair, jamais levées
APP_ERRORS = (AppError, ManifestError, OSError, ValueError, KeyError, TypeError)


class ExampleWorkflow(BaseModel):
    id: str
    title: str


class ExampleStep(BaseModel):
    app: str
    titre: str
    texte: str


class ExampleStory(BaseModel):
    id: str
    titre: str
    sous_titre: str = ""
    secteur: str = ""
    resume: str = ""
    parcours: list[ExampleStep] = []
    #: Workflows d'exemple de cette histoire déjà dans Nexus
    workflows: list[ExampleWorkflow] = []


class ExampleList(BaseModel):
    histoires: list[ExampleStory]


class ExampleLoaded(BaseModel):
    histoire: str
    workflows: list[ExampleWorkflow]
    trigger_id: str | None = None
    #: Paramètres résolus dans les applications (None : à renseigner dans le workflow)
    jeu: str | None = None
    story: int | None = None
    #: Projet de l'histoire chargé dans les fichiers de Tab (serveur MCP)
    tab: bool = False
    notes: list[str] = []


class ExampleRemoved(BaseModel):
    histoire: str
    retires: int


def _base() -> Any:
    return folder(get_settings().exemples_dir)


def _storage(exc: StorageError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


async def _examples_of(repo: WorkflowRepository) -> dict[str, list[WorkflowV2]]:
    out: dict[str, list[WorkflowV2]] = {}
    for workflow in await repo.list():
        if isinstance(workflow, WorkflowV2):
            mark = mark_of(workflow.description)
            if mark:
                out.setdefault(mark, []).append(workflow)
    return out


@router.get("", response_model=ExampleList)
async def list_examples(repo: RepoDep) -> ExampleList:
    """Histoires livrées avec Nexus et workflows d'exemple déjà créés pour chacune."""
    try:
        existing = await _examples_of(repo)
    except StorageError as exc:
        raise _storage(exc) from exc
    return ExampleList(
        histoires=[
            ExampleStory.model_validate(
                story
                | {
                    "workflows": [
                        {"id": w.id, "title": w.title} for w in existing.get(story["id"], [])
                    ]
                }
            )
            for story in stories(_base())
        ]
    )


async def _resolve(env: ToolEnvironment, refs: dict[str, Any]) -> Resolved:
    """Id du jeu Viz et n° de la story Projets, lus dans les applications ; chaque absence est
    dite dans `notes` (l'exemple de l'application n'est pas chargé, ou elle ne répond pas)."""
    resolved = Resolved()
    suite = env.suite()
    key = str(refs.get("viz_jeu_cle") or "")
    try:
        found = await suite.run_action("viz", "datasets.list", {})
        resolved.jeu = dataset_id(found.data, key)
        if resolved.jeu is None:
            resolved.notes.append(
                "Jeu Viz de l'histoire introuvable : chargez d'abord l'exemple dans Atelier Viz, "
                "puis rechargez celui-ci (ou renseignez le paramètre « jeu »)."
            )
    except APP_ERRORS as exc:
        resolved.notes.append(f"Atelier Viz : {_short(exc)} — paramètre « jeu » à renseigner.")
    name, title = str(refs.get("projets_projet") or ""), str(refs.get("projets_story") or "")
    try:
        projects = await suite.run_action("projets", "projects.list", {})
        pid = project_id(projects.data, name)
        resolved.projet = pid
        if pid is not None:
            tree = await suite.run_action("projets", "projects.tree", {"project_id": pid})
            resolved.story = story_id(tree.data, title)
        if resolved.story is None:
            resolved.notes.append(
                f"Story « {title} » introuvable dans Atelier Projets : chargez d'abord l'exemple "
                "dans Projets, puis rechargez celui-ci. Le déclencheur reste coupé d'ici là."
            )
    except APP_ERRORS as exc:
        resolved.notes.append(
            f"Atelier Projets : {_short(exc)} — paramètre « story » à renseigner, déclencheur "
            "coupé."
        )
    return resolved


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) <= 160 else text[:159] + "…"


async def _tab(env: ToolEnvironment, tool: str, story: str, notes: list[str]) -> bool:
    """Charge ou retire le projet de l'histoire dans les fichiers de Tab (serveur MCP)."""
    if not env.settings.tab_mcp_command:
        return False
    try:
        refused, value = await env.tab_mcp().call_raw(tool, {"example": story})
    except APP_ERRORS as exc:
        notes.append(f"Atelier Tab (serveur MCP) : {_short(exc)}")
        return False
    if refused:
        detail = value.get("detail") if isinstance(value, dict) else value
        notes.append(f"Atelier Tab (serveur MCP) : {_short(Exception(detail or 'refusé'))}")
        return False
    return True


@router.post("/{histoire}", response_model=ExampleLoaded)
async def load_example(
    histoire: str,
    repo: RepoDep,
    service: ServiceDep,
    llm: LLMDep,
    catalog: CatalogDep,
    make_env: EnvFactoryDep,
) -> ExampleLoaded:
    """Crée les workflows de l'histoire (en remplaçant ceux d'un chargement précédent), sans
    rien lancer : chaque étape d'écriture attendra « Autoriser » comme toujours."""
    try:
        data = part(_base(), histoire)
    except ExampleError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    env = make_env()
    try:
        notes: list[str] = []
        tab = await _tab(env, "load_suite_example", histoire, notes)
        resolved = await _resolve(env, data["references"])
    finally:
        await env.aclose()
    by_slug = {t.slug: t for t in TEMPLATES}
    try:
        for old in (await _examples_of(repo)).get(histoire, []):
            await repo.delete(old.id)
        created: list[WorkflowV2] = []
        trigger_id: str | None = None
        for item in data["workflows"]:
            template = by_slug.get(str(item.get("modele")))
            if template is None:
                notes.append(f"Modèle « {item.get('modele')} » absent de cette version de Nexus.")
                continue
            body = workflow_body(template, data, resolved)
            try:
                await _check_v2(body, llm, catalog, make_env)
            except HTTPException as exc:
                # Manifeste d'une application plus ancien ou plus récent que la bibliothèque
                notes.append(f"Modèle « {template.title} » non créé : {exc.detail}")
                continue
            workflow = await repo.create(body)
            assert isinstance(workflow, WorkflowV2)
            created.append(workflow)
            if template.slug == ALERT_TEMPLATE:
                trigger_id = await _alert_trigger(service, workflow, data, resolved, notes)
    except StorageError as exc:
        raise _storage(exc) from exc
    return ExampleLoaded(
        histoire=histoire,
        workflows=[ExampleWorkflow(id=w.id, title=w.title) for w in created],
        trigger_id=trigger_id,
        jeu=resolved.jeu,
        story=resolved.story,
        tab=tab,
        notes=resolved.notes + notes,
    )


async def _alert_trigger(
    service: TriggerService,
    workflow: WorkflowV2,
    data: dict[str, Any],
    resolved: Resolved,
    notes: list[str],
) -> str | None:
    fields = parse_fields(alert_trigger(data, resolved))
    problems, note = await service.check(workflow, fields)
    if problems:
        notes.append("Déclencheur non créé : " + " ".join(problems))
        return None
    state, internal = await service.initial_state(fields, note)
    stored = await service.triggers.create(workflow.id, fields, state, internal)
    return str(stored.trigger.id)


@router.delete("/{histoire}", response_model=ExampleRemoved)
async def remove_example(histoire: str, repo: RepoDep, make_env: EnvFactoryDep) -> ExampleRemoved:
    """Retire les workflows de l'histoire (déclencheurs compris ; l'historique des exécutions
    reste) et son projet des fichiers de Tab. Un workflow dont la marque a été retirée est
    gardé."""
    if not any(s["id"] == histoire for s in stories(_base())):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Exemple « {histoire} » introuvable.")
    try:
        mine = (await _examples_of(repo)).get(histoire, [])
        for workflow in mine:
            await repo.delete(workflow.id)
    except StorageError as exc:
        raise _storage(exc) from exc
    env = make_env()
    try:
        await _tab(env, "remove_suite_example", histoire, [])
    finally:
        await env.aclose()
    return ExampleRemoved(histoire=histoire, retires=len(mine))
