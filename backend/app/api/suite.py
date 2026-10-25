"""Carte de la suite Atelier et événements des applications (docs/workflows-v2-api.md §7).

- `GET /api/suite/map` : pour chaque application, actions et événements de son manifeste,
  outils Nexus qui la touchent, agents qui l'utilisent ; échanges entre applications ;
  workflows qui la touchent.
- `GET /api/suite/events` : derniers événements de Viz, Projets, Tab et Convert (contrat §7.3).
Ne lève jamais pour une application en panne : son statut le dit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.agents import AgentCatalog
from app.api.deps import get_catalog, get_env_factory, get_workflow_repository
from app.core.llm import LLMRouter, get_llm_router
from app.db.repository import StorageError
from app.db.workflows import WorkflowRepository
from app.schemas.workflows_v2 import AppStatus, WorkflowV2
from app.suite.apps import NODE_APPS, app_color, app_name
from app.suite.manifest import AtelierEvent, ManifestError
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError
from app.tools.toolsets import blank_tools, get_toolset, toolset_ids
from app.workflows_v2.steps import parse_uses

router = APIRouter(prefix="/api/suite", tags=["suite"])

LLMDep = Annotated[LLMRouter, Depends(get_llm_router)]
CatalogDep = Annotated[AgentCatalog, Depends(get_catalog)]
EnvFactoryDep = Annotated[Callable[[], ToolEnvironment], Depends(get_env_factory)]
RepoDep = Annotated[WorkflowRepository, Depends(get_workflow_repository)]

#: Échanges fixes de la suite (docs/SUITE.md §4)
FIXED_FLOWS = (
    ("tab", "projets", "Import DataFlow", "webhook"),
    ("tab", "viz", "Instantanés", "fichiers"),
    ("projets", "viz", "Jeux de données", "HTTP"),
    # Convert écrit la table (tables/<id>.json) directement dans le dossier de données de Tab
    ("convert", "tab", "Nouvelle table", "fichiers"),
)


class MapAction(BaseModel):
    id: str
    label: str
    kind: Literal["read", "write", "destructive"]
    output_format: str


class MapEvent(BaseModel):
    type: str
    label: str


class MapTool(BaseModel):
    name: str
    kind: Literal["read", "write"]
    toolset: str


class MapAgent(BaseModel):
    name: str
    display_name: str
    icon: str
    toolsets: list[str]
    writes: bool


class MapApp(BaseModel):
    app: str
    name: str
    color: str
    status: AppStatus
    transport: Literal["http", "mcp", "files"] | None
    actions: list[MapAction]
    events: list[MapEvent]
    nexus_tools: list[MapTool]
    agents: list[MapAgent]


class MapWorkflow(BaseModel):
    id: str
    title: str
    apps: list[str]


class SuiteMap(BaseModel):
    apps: list[MapApp]
    #: `{from, to, label, via}` (`from` : mot réservé en Python, d'où le dictionnaire)
    flows: list[dict[str, str]]
    workflows: list[MapWorkflow]


class SuiteEvents(BaseModel):
    app: str
    events: list[AtelierEvent]
    next: int
    gap: bool = False
    status: str


# ─── Carte ────────────────────────────────────────────────────────


@router.get("/map", response_model=SuiteMap)
async def suite_map(
    llm: LLMDep, catalog: CatalogDep, make_env: EnvFactoryDep, repo: RepoDep
) -> SuiteMap:
    env = make_env()
    try:
        states = {s.app: s for s in await env.suite().states()}
        agents = await catalog.agents(llm, env)
    finally:
        await env.aclose()

    # Outils Nexus par application (toutes les boîtes, configurées ou non)
    tools_by_app: dict[str, list[MapTool]] = {}
    toolset_tools: dict[str, set[str]] = {}
    for toolset_id, tool in await blank_tools(toolset_ids(include_internal=True)):
        toolset_tools.setdefault(toolset_id, set()).add(tool.name)
        app = get_toolset(toolset_id).app
        if app is None:
            continue
        entries = tools_by_app.setdefault(app, [])
        if all(t.name != tool.name for t in entries):
            entries.append(
                MapTool(
                    name=tool.name,
                    kind="write" if tool.requires_approval else "read",
                    toolset=toolset_id,
                )
            )

    # Agents par application, d'après leurs boîtes
    agents_by_app: dict[str, list[MapAgent]] = {}
    for agent in agents:
        apps: dict[str, bool] = {}
        for toolset_id in agent.toolsets:
            try:
                toolset = get_toolset(toolset_id)
            except KeyError:
                continue
            if toolset.app:
                apps[toolset.app] = apps.get(toolset.app, False) or toolset.writes
        for app, writes in apps.items():
            agents_by_app.setdefault(app, []).append(
                MapAgent(
                    name=agent.name,
                    display_name=agent.display_name,
                    icon=agent.icon,
                    toolsets=[t for t in agent.toolsets if _toolset_app(t) == app],
                    writes=writes,
                )
            )

    order = list(NODE_APPS) + sorted((set(tools_by_app) | set(agents_by_app)) - set(NODE_APPS))
    apps_out: list[MapApp] = []
    for app in order:
        state = states.get(app)
        if state is not None:
            manifest = state.manifest
            status: AppStatus = state.status
            transport = state.transport
        else:
            manifest = None
            configured = any(
                get_toolset(t.toolset).is_configured(env.settings)
                for t in tools_by_app.get(app, [])
            )
            status = "no_contract" if configured else "not_configured"
            transport = None
        apps_out.append(
            MapApp(
                app=app,
                name=state.name if state else app_name(app),
                color=app_color(app),
                status=status,
                transport=transport,
                actions=[
                    MapAction(
                        id=a.id, label=a.label or a.id, kind=a.kind, output_format=a.output.format
                    )
                    for a in (manifest.actions if manifest else [])
                ],
                events=[
                    MapEvent(type=e.type, label=e.label or e.type)
                    for e in (manifest.events if manifest else [])
                ],
                nexus_tools=tools_by_app.get(app, []),
                agents=agents_by_app.get(app, []),
            )
        )

    flows = [{"from": f, "to": t, "label": lbl, "via": via} for f, t, lbl, via in FIXED_FLOWS]
    for app in order:
        tools = tools_by_app.get(app, [])
        via = "MCP" if app == "tab" else "HTTP"
        if any(t.kind == "write" for t in tools):
            flows.append({"from": "nexus", "to": app, "label": "Écritures validées", "via": via})
        if any(t.kind == "read" for t in tools):
            read_via = "fichiers" if app == "tab" else ("Supabase" if app == "cuisine" else "HTTP")
            flows.append({"from": app, "to": "nexus", "label": "Lecture", "via": read_via})

    workflows: list[MapWorkflow] = []
    try:
        listed = await repo.list(None)
    except StorageError:
        listed = []
    tool_app = {
        name: get_toolset(toolset).app for toolset, names in toolset_tools.items() for name in names
    }
    for workflow in listed:
        touched: list[str] = []
        uses = (
            [s.uses for s in workflow.steps]
            if isinstance(workflow, WorkflowV2)
            else [f"tool:{s.tool}" for s in workflow.steps]
        )
        for item in uses:
            parsed = parse_uses(item)
            if parsed is None:
                continue
            source, name, _ = parsed
            app_id = name if source == "node" else tool_app.get(name)
            if app_id and app_id not in touched:
                touched.append(app_id)
        if touched:
            workflows.append(MapWorkflow(id=workflow.id, title=workflow.title, apps=touched))

    return SuiteMap(apps=apps_out, flows=flows, workflows=workflows)


def _toolset_app(toolset_id: str) -> str | None:
    try:
        return get_toolset(toolset_id).app
    except KeyError:
        return None


# ─── Événements ───────────────────────────────────────────────────


@router.get("/events", response_model=list[SuiteEvents])
async def suite_events(
    make_env: EnvFactoryDep,
    app: Annotated[str | None, Query(max_length=20)] = None,
    since: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[SuiteEvents]:
    """Une entrée par application de la suite (ou seulement `app`) ; `since` ne vaut qu'avec
    `app`. Une application sans contrat ou injoignable rend une liste vide et son statut."""
    apps = [app] if app else list(NODE_APPS)
    env = make_env()
    try:
        suite = env.suite()

        async def one(name: str) -> SuiteEvents:
            if name not in NODE_APPS:
                return SuiteEvents(app=name, events=[], next=0, status="not_configured")
            state = await suite.state(name)
            if state.status in ("not_configured", "no_contract"):
                return SuiteEvents(app=name, events=[], next=since or 0, status=state.status)
            try:
                page = await suite.events(name, since=since if app else None, limit=limit)
            except (AppError, ManifestError, OSError, ValueError):
                return SuiteEvents(app=name, events=[], next=since or 0, status="unreachable")
            return SuiteEvents(
                app=name,
                events=page.events,
                next=page.next,
                gap=page.gap,
                status="ok",
            )

        return list(await asyncio.gather(*(one(a) for a in apps)))
    finally:
        await env.aclose()
