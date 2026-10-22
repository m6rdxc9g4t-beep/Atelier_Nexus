"""Étapes utilisables par un workflow v2 : outils Nexus et actions des manifestes.

- Workflow d'un agent : les outils de ses boîtes (`agent.toolsets`).
- Workflow de suite (`agent: null`) : l'union des boîtes non internes ; seules les boîtes
  configurées sont disponibles. Aucun modèle n'est appelé : les outils `sensitive` sont permis.
- Actions `node:<app>/<action_id>` des manifestes de Viz, Projets et Tab, quel que soit l'agent.

`delegate_to_agent` et `current_datetime` ne sont jamais proposés (`NOT_REPLAYABLE`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from app.schemas.workflows_v2 import (
    Catalog,
    CatalogApp,
    CatalogEntry,
    OutputColumnHint,
    OutputHint,
)
from app.suite.apps import NODE_APPS, app_color, app_name
from app.suite.manifest import NodeAction
from app.suite.nodes import NodeState
from app.tools.base import BaseTool, portable_schema
from app.tools.toolsets import blank_tools, build_tools, get_toolset, toolset_ids
from app.workflows import NOT_REPLAYABLE

if TYPE_CHECKING:
    from app.agents.base import BaseAgent
    from app.tools.environment import ToolEnvironment

USES = re.compile(
    r"^(tool):([a-z][a-z0-9_]{1,63})$|^(node):([a-z][a-z0-9_]{0,39})/([a-z0-9_.]{1,120})$"
)


@dataclass
class ToolTarget:
    uses: str
    name: str
    tool: BaseTool[Any]
    toolset: str
    app: str | None

    @property
    def kind(self) -> Literal["read", "write"]:
        return "write" if self.tool.requires_approval else "read"


@dataclass
class NodeTarget:
    uses: str
    app: str
    action: NodeAction

    @property
    def kind(self) -> Literal["read", "write", "destructive"]:
        return self.action.kind


@dataclass
class StepProblem:
    code: str
    message: str


Target = ToolTarget | NodeTarget


def parse_uses(uses: str) -> tuple[str, str, str] | None:
    """("tool", nom, "") ou ("node", app, action) ; None si la forme est invalide."""
    m = USES.match(uses)
    if not m:
        return None
    if m.group(1):
        return "tool", m.group(2), ""
    return "node", m.group(4), m.group(5)


def short_label(description: str) -> str:
    """Libellé court d'un outil : début de sa description (« Liste les projets… »)."""
    first = re.split(r"(?<=[a-zé])\. | : |\(", description, maxsplit=1)[0].strip().rstrip(".")
    return first if len(first) <= 70 else first[:69].rstrip() + "…"


class StepRegistry:
    """Étapes connues pour UNE exécution ou UNE requête (outils construits, manifestes lus)."""

    def __init__(self) -> None:
        #: Outils exécutables (application configurée), par nom
        self.tools: dict[str, tuple[BaseTool[Any], str]] = {}
        #: Tous les outils des boîtes du périmètre, configurées ou non (métadonnées)
        self.declared: dict[str, tuple[BaseTool[Any], str]] = {}
        self.nodes: dict[str, NodeState] = {}
        self.toolsets: list[str] = []

    @classmethod
    async def build(cls, env: ToolEnvironment, agent: BaseAgent | None) -> StepRegistry:
        registry = cls()
        registry.toolsets = list(agent.toolsets) if agent is not None else toolset_ids()
        blank = await blank_tools(registry.toolsets)
        owner = {tool.name: toolset for toolset, tool in reversed(blank)}
        if agent is not None:
            live = list(agent.tools.values())
        else:
            live, _ = build_tools(registry.toolsets, env)
        registry.tools = {t.name: (t, owner.get(t.name, "core")) for t in live}
        for toolset, tool in blank:
            registry.declared.setdefault(tool.name, (tool, toolset))
        for name in NOT_REPLAYABLE:
            registry.tools.pop(name, None)
            registry.declared.pop(name, None)
        registry.nodes = {s.app: s for s in await env.suite().states()}
        return registry

    # ─── Résolution ───────────────────────────────────────────────

    def lookup(self, uses: str) -> Target | StepProblem:
        parsed = parse_uses(uses)
        if parsed is None:
            return StepProblem(
                "UNKNOWN_USES", f"« {uses} » : attendu tool:<outil> ou node:<app>/<action>."
            )
        source, name, action_id = parsed
        if source == "tool":
            if name in NOT_REPLAYABLE:
                return StepProblem(
                    "NOT_REPLAYABLE",
                    f"« {name} » ne peut pas faire partie d'un workflow ({NOT_REPLAYABLE[name]}).",
                )
            if name in self.tools:
                tool, toolset = self.tools[name]
                return ToolTarget(uses, name, tool, toolset, get_toolset(toolset).app)
            if name in self.declared:
                _, toolset = self.declared[name]
                return StepProblem(
                    "UNAVAILABLE",
                    f"L'outil « {name} » n'est pas disponible : boîte « "
                    f"{get_toolset(toolset).label} » non configurée sur cette machine.",
                )
            return StepProblem("UNKNOWN_USES", f"Outil inconnu : « {name} ».")
        state = self.nodes.get(name)
        if state is None:
            return StepProblem(
                "UNKNOWN_USES", f"Application « {name} » inconnue (nœuds : {', '.join(NODE_APPS)})."
            )
        if state.status != "ok" or state.manifest is None:
            return StepProblem(
                "UNAVAILABLE", f"{state.name} indisponible : {state.reason or state.status}."
            )
        action = state.manifest.action(action_id)
        if action is None:
            return StepProblem(
                "UNKNOWN_USES", f"Action « {action_id} » absente du manifeste de {state.name}."
            )
        if not state.executable:
            return StepProblem(
                "UNAVAILABLE", state.not_executable_reason or f"{state.name} : actions impossibles."
            )
        return NodeTarget(uses, name, action)

    # ─── Catalogue ────────────────────────────────────────────────

    def catalog(self) -> Catalog:
        entries: list[CatalogEntry] = []
        for name, (tool, toolset) in self.declared.items():
            available = name in self.tools
            app = get_toolset(toolset).app
            entries.append(
                CatalogEntry(
                    uses=f"tool:{name}",
                    source="tool",
                    app=app,
                    label=short_label(tool.description),
                    description=tool.description,
                    kind="write" if tool.requires_approval else "read",
                    input_schema=portable_schema(tool.input_model),
                    output_format=tool.output_format,
                    output_hint=OutputHint.model_validate(tool.output_hint)
                    if tool.output_hint
                    else None,
                    available=available,
                    unavailable_reason=None
                    if available
                    else f"Boîte « {get_toolset(toolset).label} » non configurée.",
                )
            )
        for state in self.nodes.values():
            if state.manifest is None:
                continue
            for action in state.manifest.actions:
                entries.append(
                    CatalogEntry(
                        uses=f"node:{state.app}/{action.id}",
                        source="node",
                        app=state.app,
                        label=action.label or action.id,
                        description=action.description,
                        kind=action.kind,
                        input_schema=action.input_schema,
                        output_format=action.output.format,
                        output_hint=node_hint(action),
                        available=state.status == "ok" and state.executable,
                        unavailable_reason=None
                        if state.executable
                        else state.not_executable_reason,
                    )
                )
        return Catalog(apps=self.apps(), entries=entries)

    def apps(self) -> list[CatalogApp]:
        """Applications des nœuds (statut du manifeste), puis celles des outils (sans contrat)."""
        out = [
            CatalogApp(app=s.app, name=s.name, status=s.status, color=app_color(s.app))
            for s in self.nodes.values()
        ]
        seen = set(self.nodes)
        for toolset in self.toolsets:
            app = get_toolset(toolset).app
            if app is None or app in seen:
                continue
            seen.add(app)
            configured = any(
                get_toolset(ts).app == app and name in self.tools
                for name, (_, ts) in self.declared.items()
            )
            out.append(
                CatalogApp(
                    app=app,
                    name=app_name(app),
                    status="no_contract" if configured else "not_configured",
                    color=app_color(app),
                )
            )
        return out


def node_hint(action: NodeAction) -> OutputHint | None:
    """Colonnes ou champs annoncés par `output.schema` (si le manifeste les décrit)."""
    schema = action.output.schema_
    if not schema:
        return None
    columns = schema.get("x-columns") or schema.get("columns")
    if isinstance(columns, list):
        try:
            return OutputHint(columns=[OutputColumnHint.model_validate(c) for c in columns])
        except ValueError:
            return None
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        return OutputHint(fields=list(props)[:30])
    return None


def tool_schema(target: Target) -> dict[str, Any]:
    if isinstance(target, ToolTarget):
        return portable_schema(target.tool.input_model)
    return target.action.input_schema
