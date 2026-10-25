"""Nœuds de la suite : lecture des manifestes, exécution d'une action, lecture des événements.

- **Viz** : `{data_via_base_url}/atelier/manifest` (HTTP), événements `/api/atelier/events`.
- **Projets** : `{projets_base_url}/atelier/manifest` (HTTP), mêmes événements.
- **Convert** : `{convert_base_url}/atelier/manifest` (HTTP), mêmes événements ; délai des
  actions `CONVERT_TIMEOUT` (une conversion avec OCR est longue).
- **Tab** : fichier `{tab_exports_dir}/_atelier/manifest.json` (repli : outil MCP
  `atelier_manifest` si `TAB_MCP_COMMAND` est défini) ; actions par le serveur MCP ;
  événements dans `_atelier/events.jsonl` (repli : outil MCP `atelier_events`).

Manifestes gardés 60 s en mémoire (10 s pour une application qui ne répond pas). Statut :
`ok`, `unreachable`, `no_contract` (route ou fichier absent : version de l'app antérieure
au contrat) ou `not_configured`.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from jsonschema import Draft202012Validator
from referencing.exceptions import Unresolvable

from app.suite.apps import HTTP_NODES, NODE_APPS, app_name
from app.suite.http import NodeActionError, NodeHttpClient, is_loopback
from app.suite.manifest import (
    EventPage,
    ManifestError,
    NodeAction,
    NodeManifest,
    parse_events,
    parse_manifest,
)
from app.tools.formatting import is_atelier_table
from app.tools.http import AppError

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

NodeStatus = Literal["ok", "unreachable", "no_contract", "not_configured"]
Transport = Literal["http", "mcp", "files"]

CACHE_OK_SECONDS = 60.0
#: Délai de lecture d'un manifeste (catalogue, carte) : une application figée ne bloque pas l'écran
MANIFEST_TIMEOUT = 5.0
CACHE_FAIL_SECONDS = 10.0
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_EVENTS_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 500
ATELIER_DIR = "_atelier"


@dataclass
class NodeState:
    app: str
    name: str
    status: NodeStatus
    transport: Transport | None
    manifest: NodeManifest | None = None
    reason: str | None = None
    #: Actions du manifeste écartées (mal formées), `id : raison`
    ignored: list[str] = field(default_factory=list)
    #: Les actions peuvent-elles être exécutées ? (Tab : serveur MCP configuré)
    executable: bool = True
    not_executable_reason: str | None = None


@dataclass
class NodeResult:
    content: str
    data: Any
    replayed: bool = False


_CACHE: dict[tuple[str, str], tuple[float, NodeState]] = {}


def clear_manifest_cache() -> None:
    _CACHE.clear()


def _key(app: str, env: ToolEnvironment) -> tuple[str, str]:
    """Clé du cache : l'application et ce qui la désigne (un changement d'adresse dans les
    Réglages relit le manifeste dès la requête suivante)."""
    s = env.settings
    if app == "tab":
        return app, f"{s.tab_exports_dir or ''}|{s.tab_mcp_command or ''}"
    if app in HTTP_NODES:
        return app, getattr(s, HTTP_NODES[app][0]) or ""
    return app, ""


# ─── Conversion des entrées ───────────────────────────────────────


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def build_http_request(
    action: NodeAction, payload: dict[str, Any]
) -> tuple[str, list[tuple[str, str]] | None, dict[str, Any] | None]:
    """(chemin, paramètres de requête, corps JSON) : les propriétés citées dans `path` vont dans
    le chemin (encodées, jamais `.` ni `..`), celles d'une route GET dans la requête, les autres
    dans le corps."""
    assert action.http is not None
    rest = dict(payload)
    path = action.http.path
    for name in action.http.path_params:
        if name not in rest or rest[name] is None or isinstance(rest[name], dict | list):
            raise NodeActionError(
                f"Paramètre « {name} » manquant ou invalide pour le chemin {action.http.path}.",
                app="nexus",
                code="VALIDATION",
            )
        text = _scalar(rest.pop(name))
        if text in ("", ".", ".."):
            raise NodeActionError(
                f"Valeur refusée pour « {name} » dans le chemin.", app="nexus", code="VALIDATION"
            )
        path = path.replace("{" + name + "}", quote(text, safe=""))
    if action.http.method == "GET":
        query: list[tuple[str, str]] = []
        for key, value in rest.items():
            if value is None:
                continue
            if isinstance(value, list):
                query += [(key, _scalar(v)) for v in value if v is not None]
            else:
                query.append((key, _scalar(value)))
        return path, query, None
    return path, None, rest


def validate_input(action: NodeAction, payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Erreurs `(champ, message)` de l'entrée contre `input_schema` (champ racine = "").
    Un `$ref` introuvable (manifeste mal formé, adresse extérieure jamais lue) est une erreur
    de l'entrée, jamais une exception : l'action est refusée sans requête."""
    validator = Draft202012Validator(action.input_schema)
    try:
        found = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    except Unresolvable:
        return [("", f"schéma d'entrée de {action.id} illisible (référence $ref introuvable)")]
    errors = []
    for error in found:
        path = list(error.absolute_path)
        field_name = str(path[0]) if path else ""
        if not path and error.validator == "required":
            missing = error.message.split("'")
            field_name = missing[1] if len(missing) > 2 else ""
        if not path and error.validator == "additionalProperties":
            field_name = ""
        errors.append((field_name, error.message))
    return errors


def summarize(label: str, data: Any, *, replayed: bool = False) -> str:
    """Résumé texte court d'une sortie d'action (le détail est dans `data`)."""
    suffix = " (déjà faite : réponse rejouée)" if replayed else ""
    if is_atelier_table(data):
        total = data.get("total")
        shown = len(data["rows"])
        more = f" sur {total}" if isinstance(total, int) and total != shown else ""
        return f"{label} : {shown} ligne(s){more}{suffix}."
    if isinstance(data, dict):
        ident = data.get("id")
        if ident is not None:
            return f"{label} : terminé (id {ident}){suffix}."
        keys = ", ".join(list(data)[:8])
        return f"{label} : terminé ({keys}){suffix}." if keys else f"{label} : terminé{suffix}."
    if isinstance(data, list):
        return f"{label} : {len(data)} élément(s){suffix}."
    if data is None:
        return f"{label} : terminé{suffix}."
    text = str(data)
    return f"{label} : {text if len(text) <= 300 else text[:299] + '…'}{suffix}"


def _read_capped(path: Path, folder: Path, limit: int) -> bytes | None:
    """Contenu d'un fichier du dossier (pas de lien qui en sort, taille bornée) ; None = absent."""
    try:
        real = path.resolve(strict=True)
    except OSError:
        return None
    if not real.is_relative_to(folder) or not real.is_file():
        return None
    with real.open("rb") as fh:
        raw = fh.read(limit + 1)
    if len(raw) > limit:
        raise ManifestError(f"{path.name} dépasse {limit // 1024} Kio.")
    return raw


# ─── Registre ─────────────────────────────────────────────────────


class SuiteNodes:
    """Accès aux nœuds pour UNE exécution (clients créés à la demande, fermés par `aclose`)."""

    def __init__(self, env: ToolEnvironment) -> None:
        self.env = env
        self._http: dict[str, NodeHttpClient] = {}

    async def aclose(self) -> None:
        for client in self._http.values():
            await client.aclose()
        self._http.clear()

    # ─── Configuration ────────────────────────────────────────────

    def base_url(self, app: str) -> str | None:
        if app not in HTTP_NODES:
            return None
        value: str | None = getattr(self.env.settings, HTTP_NODES[app][0])
        return value

    def http(self, app: str) -> NodeHttpClient:
        if app not in self._http:
            base = self.base_url(app)
            if not base:
                raise NodeActionError(
                    f"{app_name(app)} n'est pas configuré.", app=app, code="NOT_CONFIGURED"
                )
            self._http[app] = NodeHttpClient(
                app,
                app_name(app),
                base,
                # Événements : délai court (le passage des déclencheurs lit les apps l'une après
                # l'autre) ; manifeste borné à MANIFEST_TIMEOUT (`state`) ; actions : `action_timeout`
                timeout=self.env.settings.apps_timeout,
                transport=self.env.transport(HTTP_NODES[app][1]),
            )
        return self._http[app]

    def action_timeout(self, app: str) -> float:
        """Délai d'UNE action : `CONVERT_TIMEOUT` pour Convert (une conversion avec OCR est
        longue), `APPS_TIMEOUT` pour les autres nœuds."""
        s = self.env.settings
        return s.convert_timeout if app == "convert" else s.apps_timeout

    def _tab_folder(self) -> Path | None:
        folder = self.env.settings.tab_exports_dir
        return Path(folder).expanduser() if folder else None

    # ─── Manifestes ───────────────────────────────────────────────

    async def states(self, apps: tuple[str, ...] = NODE_APPS) -> list[NodeState]:
        return list(await asyncio.gather(*(self.state(app) for app in apps)))

    async def state(self, app: str, *, fresh: bool = False) -> NodeState:
        """État du nœud (cache court) ; `fresh` relit le manifeste et met le cache à jour
        (vérification demandée par l'utilisateur, `GET /api/apps/status`)."""
        key = _key(app, self.env)
        cached = _CACHE.get(key)
        now = time.monotonic()
        if cached and cached[0] > now and not fresh:
            return cached[1]
        try:
            state = await asyncio.wait_for(self._load(app), timeout=MANIFEST_TIMEOUT)
        except TimeoutError:
            state = NodeState(
                app,
                app_name(app),
                "unreachable",
                None,
                reason="délai de lecture du manifeste dépassé",
            )
        ttl = CACHE_OK_SECONDS if state.status in ("ok", "no_contract") else CACHE_FAIL_SECONDS
        if state.status != "not_configured":
            _CACHE[key] = (now + ttl, state)
        return state

    async def manifest(self, app: str) -> NodeManifest | None:
        return (await self.state(app)).manifest

    async def _load(self, app: str) -> NodeState:
        if app == "tab":
            return await self._load_tab()
        name = app_name(app)
        base = self.base_url(app)
        if not base:
            return NodeState(app, name, "not_configured", None, reason="adresse non définie")
        if not is_loopback(base):
            return NodeState(
                app,
                name,
                "unreachable",
                "http",
                reason=f"adresse non locale refusée ({base}) : le contrat n'autorise que le bouclage",
            )
        try:
            client = self.http(app)
            raw = await client.get_json(f"{client.api_path}/atelier/manifest")
        except NodeActionError as exc:
            if exc.status == 404:
                return NodeState(
                    app, name, "no_contract", "http", reason=f"{name} ne publie pas de manifeste"
                )
            return NodeState(app, name, "unreachable", "http", reason=str(exc))
        return self._parsed(app, raw, "http")

    def _parsed(
        self,
        app: str,
        raw: Any,
        transport: Transport,
        *,
        executable: bool = True,
        not_executable_reason: str | None = None,
    ) -> NodeState:
        name = app_name(app)
        try:
            manifest, ignored = parse_manifest(raw, app)
        except ManifestError as exc:
            return NodeState(app, name, "no_contract", transport, reason=str(exc))
        return NodeState(
            app,
            manifest.name or name,
            "ok",
            transport,
            manifest=manifest,
            ignored=ignored,
            executable=executable,
            not_executable_reason=not_executable_reason,
        )

    async def _load_tab(self) -> NodeState:
        s = self.env.settings
        name = app_name("tab")
        folder = self._tab_folder()
        has_mcp = bool(s.tab_mcp_command)
        transport: Transport = "mcp" if has_mcp else "files"
        no_mcp = (
            None if has_mcp else "TAB_MCP_COMMAND non défini : actions d'Atelier Tab impossibles"
        )
        if folder is None and not has_mcp:
            return NodeState(
                "tab", name, "not_configured", None, reason="TAB_EXPORTS_DIR non défini"
            )
        raw: Any = None
        if folder is not None and folder.is_dir():
            root = folder.resolve()
            try:
                content = await asyncio.to_thread(
                    _read_capped, root / ATELIER_DIR / "manifest.json", root, MAX_MANIFEST_BYTES
                )
                raw = json.loads(content.decode("utf-8-sig")) if content is not None else None
            except (OSError, ValueError, ManifestError) as exc:
                return NodeState(
                    "tab", name, "unreachable", transport, reason=f"manifeste illisible : {exc}"
                )
        if raw is None and has_mcp:
            try:
                raw = await self.env.tab_mcp().call("atelier_manifest", {})
            except AppError as exc:
                if "inconnu" in str(exc).lower() or "unknown" in str(exc).lower():
                    return NodeState(
                        "tab",
                        name,
                        "no_contract",
                        transport,
                        reason="outil atelier_manifest absent",
                    )
                return NodeState("tab", name, "unreachable", transport, reason=str(exc))
        if raw is None:
            if folder is not None and not folder.is_dir():
                return NodeState(
                    "tab", name, "unreachable", transport, reason=f"dossier {folder} introuvable"
                )
            return NodeState(
                "tab",
                name,
                "no_contract",
                transport,
                reason=f"{ATELIER_DIR}/manifest.json absent (Atelier Tab antérieure au contrat)",
            )
        return self._parsed("tab", raw, transport, executable=has_mcp, not_executable_reason=no_mcp)

    # ─── Actions ──────────────────────────────────────────────────

    async def resolve(self, app: str, action_id: str) -> tuple[NodeState, NodeAction]:
        state = await self.state(app)
        if state.status != "ok" or state.manifest is None:
            raise NodeActionError(
                f"{state.name} indisponible ({state.reason or state.status}).",
                app=app,
                code="UNAVAILABLE",
            )
        action = state.manifest.action(action_id)
        if action is None:
            raise NodeActionError(
                f"Action « {action_id} » absente du manifeste de {state.name}.",
                app=app,
                code="UNKNOWN_ACTION",
            )
        if not state.executable:
            raise NodeActionError(
                state.not_executable_reason or f"Actions de {state.name} impossibles.",
                app=app,
                code="UNAVAILABLE",
            )
        return state, action

    async def run_action(
        self,
        app: str,
        action_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> NodeResult:
        """Exécute une action déclarée. L'entrée est validée contre `input_schema` ; la clé
        d'idempotence n'est transmise que si l'action la déclare (`header` ou `field`)."""
        _, action = await self.resolve(app, action_id)
        body = dict(payload)
        if action.idempotency == "field" and idempotency_key:
            body["idempotency_key"] = idempotency_key
        checked = (
            body
            if "idempotency_key" in action.input_schema.get("properties", {})
            else dict(payload)
        )
        errors = validate_input(action, checked)
        if errors:
            details = "; ".join(f"{f or '(entrée)'} : {m}" for f, m in errors[:5])
            raise NodeActionError(
                f"Entrée refusée par le schéma de {action.id} — {details}",
                app=app,
                code="INPUT_INVALID",
            )
        label = action.label or action.id
        if action.http is not None:
            path, query, json_body = build_http_request(action, body)
            headers = (
                {"Idempotency-Key": idempotency_key}
                if action.idempotency == "header" and idempotency_key
                else None
            )
            response = await self.http(app).call(
                action.http.method,
                path,
                params=query,
                json_body=json_body,
                headers=headers,
                timeout=self.action_timeout(app),
            )
            data = _finite(response.body)
            return NodeResult(
                summarize(label, data, replayed=response.replayed), data, response.replayed
            )
        assert action.mcp_tool is not None
        refused, value = await self.env.tab_mcp().call_raw(action.mcp_tool, body)
        if refused:
            detail = value.get("detail") if isinstance(value, dict) else value
            code = value.get("code") if isinstance(value, dict) else None
            raise NodeActionError(
                f"{app_name(app)} : {detail or 'action refusée'}",
                app=app,
                code=code if isinstance(code, str) else "MCP_ERROR",
            )
        replayed = isinstance(value, dict) and value.get("replayed") is True
        data = _finite(value)
        return NodeResult(summarize(label, data, replayed=replayed), data, replayed)

    # ─── Événements ───────────────────────────────────────────────

    async def events(
        self,
        app: str,
        *,
        since: int | None = None,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> EventPage:
        limit = max(1, min(limit, MAX_EVENTS))
        if app == "tab":
            return await self._tab_events(since, limit, types)
        params: list[tuple[str, str]] = [("limit", str(limit))]
        if since is not None:
            params.append(("since", str(since)))
        if types:
            params.append(("types", ",".join(types)))
        client = self.http(app)
        raw = await client.get_json(f"{client.api_path}/atelier/events", params)
        return parse_events(raw, since)

    async def _tab_events(
        self, since: int | None, limit: int, types: list[str] | None
    ) -> EventPage:
        folder = self._tab_folder()
        content: bytes | None = None
        if folder is not None and folder.is_dir():
            root = folder.resolve()
            content = await asyncio.to_thread(
                _read_capped, root / ATELIER_DIR / "events.jsonl", root, MAX_EVENTS_BYTES
            )
        if content is None:
            if self.env.settings.tab_mcp_command:
                args: dict[str, Any] = {"limit": limit}
                if since is not None:
                    args["since"] = since
                return parse_events(await self.env.tab_mcp().call("atelier_events", args), since)
            return EventPage(next=since or 0)
        items = []
        for line in content.decode("utf-8", "replace").splitlines():
            try:
                items.append(json.loads(line))
            except ValueError:
                continue  # ligne en cours d'écriture
        page = parse_events({"events": items}, since)
        events = sorted(page.events, key=lambda e: e.seq)
        oldest = events[0].seq if events else None
        last = events[-1].seq if events else 0
        if types:
            events = [e for e in events if e.type in types]
        if since is None:
            chosen = events[-limit:]
        else:
            chosen = [e for e in events if e.seq > since][:limit]
        # §7.3 : trou si des événements ont été retirés (since < oldest - 1) ou si le journal a été
        # remis à zéro / remplacé (since au-delà du dernier seq connu).
        gap = since is not None and ((oldest is not None and since < oldest - 1) or since > last)
        nxt = (
            chosen[-1].seq
            if chosen
            else (since if since is not None else (events[-1].seq if events else 0))
        )
        return EventPage(events=chosen, next=nxt, oldest=oldest, gap=gap)


def _finite(value: Any) -> Any:
    """JSON sûr à stocker : NaN / infini remplacés par `null`."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value
