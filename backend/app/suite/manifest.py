"""Manifeste `atelier-node/1` et événements (docs/apps/noeud-atelier.md §7.1 et §7.3).

Lecture tolérante : un champ inconnu est ignoré (compatibilité ascendante) et une action mal
formée est écartée (et signalée) sans rendre tout le manifeste inutilisable. Les règles de
sécurité, elles, ne sont pas négociables : chemin HTTP relatif à l'application, sans `..`,
nom d'outil MCP simple, schéma d'entrée valide (JSON Schema 2020-12).
"""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONTRACT = "atelier-node/1"
ACTION_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
#: Chemin d'une action : absolu, segments simples et paramètres `{nom}`
HTTP_PATH = re.compile(r"^(/([A-Za-z0-9_\-.]+|\{[a-z][a-z0-9_]*\}))+/?$")
PATH_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")
MCP_TOOL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

ActionKind = Literal["read", "write", "destructive"]
Idempotency = Literal["header", "field", "natural", "none"]


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class HttpBinding(_Lenient):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(max_length=300)

    @model_validator(mode="after")
    def _safe_path(self) -> Self:
        segments = self.path.split("/")
        if not HTTP_PATH.match(self.path) or ".." in segments or "." in segments:
            raise ValueError(f"Chemin d'action refusé : {self.path!r}")
        return self

    @property
    def path_params(self) -> list[str]:
        return PATH_PARAM.findall(self.path)


class ActionOutput(_Lenient):
    format: Literal["atelier-table/1", "json"] = "json"
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class NodeAction(_Lenient):
    id: str = Field(max_length=120)
    label: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    kind: ActionKind
    http: HttpBinding | None = None
    mcp_tool: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output: ActionOutput = Field(default_factory=ActionOutput)
    idempotency: Idempotency = "none"

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not ACTION_ID.match(self.id):
            raise ValueError(f"Identifiant d'action invalide : {self.id!r}")
        if (self.http is None) == (self.mcp_tool is None):
            raise ValueError(f"{self.id} : exactement un transport (http ou mcp_tool).")
        if self.mcp_tool is not None and not MCP_TOOL.match(self.mcp_tool):
            raise ValueError(f"{self.id} : nom d'outil MCP invalide.")
        try:
            Draft202012Validator.check_schema(self.input_schema)
        except SchemaError as exc:
            raise ValueError(f"{self.id} : schéma d'entrée invalide ({exc.message}).") from exc
        if self.input_schema.get("type", "object") != "object":
            raise ValueError(f"{self.id} : l'entrée doit être un objet.")
        return self

    @property
    def transport(self) -> Literal["http", "mcp"]:
        return "http" if self.http is not None else "mcp"


class EventSpec(_Lenient):
    type: str = Field(max_length=120)
    label: str = Field(default="", max_length=200)


class NodeManifest(_Lenient):
    contract: str
    app: str
    name: str = ""
    version: str = ""
    transport: Literal["http", "mcp"]
    actions: list[NodeAction] = Field(default_factory=list)
    events: list[EventSpec] = Field(default_factory=list)

    def action(self, action_id: str) -> NodeAction | None:
        return next((a for a in self.actions if a.id == action_id), None)


class ManifestError(ValueError):
    """Manifeste absent, d'un autre contrat ou illisible (message lisible)."""


def parse_manifest(raw: Any, expected_app: str) -> tuple[NodeManifest, list[str]]:
    """Manifeste validé + actions écartées (`id : raison`). Lève `ManifestError`."""
    if not isinstance(raw, dict):
        raise ManifestError("Manifeste illisible (objet JSON attendu).")
    if raw.get("contract") != CONTRACT:
        raise ManifestError(f"Contrat inconnu : {raw.get('contract')!r} (attendu {CONTRACT}).")
    if raw.get("app") != expected_app:
        raise ManifestError(f"Manifeste d'une autre application : {raw.get('app')!r}.")
    actions: list[NodeAction] = []
    ignored: list[str] = []
    seen: set[str] = set()
    for item in raw.get("actions") or []:
        ident = item.get("id", "?") if isinstance(item, dict) else "?"
        try:
            action = NodeAction.model_validate(item)
        except ValidationError as exc:
            reason = exc.errors()[0]["msg"].removeprefix("Value error, ")
            ignored.append(f"{ident} : {reason}")
            continue
        if action.id in seen:
            ignored.append(f"{action.id} : identifiant en double")
            continue
        seen.add(action.id)
        actions.append(action)
    events = []
    for item in raw.get("events") or []:
        try:
            events.append(EventSpec.model_validate(item))
        except ValidationError:
            continue
    try:
        manifest = NodeManifest.model_validate(
            {k: v for k, v in raw.items() if k not in ("actions", "events")}
            | {"actions": [], "events": []}
        )
    except ValidationError as exc:
        raise ManifestError(f"Manifeste non conforme : {exc.error_count()} erreur(s).") from exc
    manifest.actions = actions
    manifest.events = events
    return manifest, ignored


# ─── Événements (§7.3) ────────────────────────────────────────────


class EventSubject(_Lenient):
    kind: str
    id: str
    label: str = ""


class AtelierEvent(_Lenient):
    seq: int
    type: str
    at: str
    subject: EventSubject
    data: dict[str, Any] = Field(default_factory=dict)


class EventPage(BaseModel):
    events: list[AtelierEvent] = Field(default_factory=list)
    next: int = 0
    oldest: int | None = None
    gap: bool = False


def parse_events(raw: Any, since: int | None) -> EventPage:
    """Réponse `{events, next, oldest, gap?}` d'une application ; événements illisibles écartés."""
    if not isinstance(raw, dict):
        raise ManifestError("Réponse d'événements illisible.")
    events = []
    for item in raw.get("events") or []:
        try:
            events.append(AtelierEvent.model_validate(item))
        except ValidationError:
            continue
    nxt = raw.get("next")
    oldest = raw.get("oldest")
    return EventPage(
        events=events,
        next=nxt if isinstance(nxt, int) else (events[-1].seq if events else (since or 0)),
        oldest=oldest if isinstance(oldest, int) else None,
        gap=bool(raw.get("gap", False)),
    )
