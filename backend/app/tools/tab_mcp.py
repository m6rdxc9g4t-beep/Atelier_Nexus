"""Écriture dans Atelier Tab par son serveur MCP (stdio).

Atelier Tab n'a pas d'API HTTP. Pour modifier une table, on lance son serveur MCP
(`desktop/mcp-server.ts`, le même moteur et le même store que l'application) et on lui
envoie des appels `tools/call` en JSON-RPC, une ligne par message. À chaque appel, le
serveur relit le dossier de données, applique l'outil, écrit les fichiers modifiés et
met à jour l'instantané lu par `app/tools/tab.py` : la lecture voit aussitôt le changement.

Le processus est lancé à la première écriture d'un tour d'agent et arrêté à la fin
(`aclose`). Il ne reçoit qu'un environnement minimal : aucun secret de Nexus.

Windows : la commande (`TAB_MCP_COMMAND`, réglage du `.env` jamais modifiable depuis
l'interface) peut être un script `.cmd` ; un shim npm est lancé par `node.exe` directement
(`windows_command`), un autre script par `cmd.exe` implicitement, ce qui est sans risque : ses
arguments viennent du réglage, jamais des données (elles passent par l'entrée standard). Aucune
console visible ; à l'arrêt forcé, `cmd.exe` et ses enfants sont arrêtés ensemble.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import Settings
from app.core.processes import NO_WINDOW, WINDOWS_VARS, kill_tree, split_command, windows_command
from app.schemas.tab import MAPPING_LABELS, ColumnType
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import fmt
from app.tools.http import AppError, AppNotConfiguredError, AppRequestError, AppUnavailableError
from app.tools.tab import TABLE_ID, TYPE_LABELS

PROTOCOL_VERSION = "2025-06-18"
#: Variables transmises au serveur MCP (le reste de l'environnement, dont les clés, est retiré)
SAFE_ENV = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "XDG_CONFIG_HOME", "NODE_PATH")
MAX_LINE = 8 * 1024 * 1024


class TabMcpClient:
    app = "tab"
    label = "Atelier Tab (serveur MCP)"

    def __init__(
        self, command: list[str], *, data_dir: str | None = None, timeout: float = 30.0
    ) -> None:
        if not command:
            raise AppNotConfiguredError("TAB_MCP_COMMAND est vide.", app=self.app)
        self.command = command
        self.data_dir = data_dir
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr: bytearray = bytearray()
        self._stderr_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> TabMcpClient | None:
        if not settings.tab_mcp_command:
            return None
        return cls(
            split_command(settings.tab_mcp_command),
            data_dir=settings.tab_data_dir,
            timeout=settings.tab_mcp_timeout,
        )

    # ─── Processus ────────────────────────────────────────────────

    def _env(self) -> dict[str, str]:
        names = set(SAFE_ENV)
        if sys.platform == "win32":  # SystemRoot, APPDATA… : sans elles Node.js échoue
            names |= set(WINDOWS_VARS)
        windows = sys.platform == "win32"
        env = {k: v for k, v in os.environ.items() if (k.upper() if windows else k) in names}
        if self.data_dir:
            env["ATELIER_TAB_DATA"] = os.path.expanduser(self.data_dir)
        return env

    def _stderr_tail(self) -> str:
        text = self._stderr.decode("utf-8", "replace").strip()
        return text[-500:]

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(4096):
            self._stderr += chunk
            del self._stderr[:-4096]  # on ne garde que la fin

    async def _start(self) -> asyncio.subprocess.Process:
        if self._proc and self._proc.returncode is None:
            return self._proc
        try:
            proc = await asyncio.create_subprocess_exec(
                *windows_command(self.command),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
                limit=MAX_LINE,
                creationflags=NO_WINDOW,
            )
        except (FileNotFoundError, PermissionError) as exc:
            raise AppUnavailableError(
                f"Serveur MCP d'Atelier Tab introuvable ({self.command[0]}). Vérifiez TAB_MCP_COMMAND "
                "(app Mac : /Applications/Atelier_Tab.app/Contents/Resources/atelier-mcp ; dépôt : "
                "node dist-desktop/atelier-mcp.mjs après `npm run build:desktop` ; Windows : "
                "docs/apps/tab.md).",
                app=self.app,
            ) from exc
        self._proc = proc
        assert proc.stderr is not None
        self._stderr_task = asyncio.create_task(self._drain_stderr(proc.stderr))
        await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "atelier-nexus", "version": "0.7"},
            },
        )
        await self._notify("notifications/initialized")
        return proc

    async def aclose(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.returncode is None:
            if proc.stdin:
                with contextlib.suppress(OSError):
                    proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except TimeoutError:
                kill_tree(proc.pid)  # Windows : un script .cmd laisserait node.exe derrière lui
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task

    # ─── JSON-RPC ─────────────────────────────────────────────────

    async def _write(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise self._died()
        try:
            proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise self._died() from exc

    def _died(self) -> AppUnavailableError:
        tail = self._stderr_tail()
        return AppUnavailableError(
            "Le serveur MCP d'Atelier Tab s'est arrêté" + (f" : {tail}" if tail else "."),
            app=self.app,
        )

    async def _notify(self, method: str) -> None:
        await self._write({"jsonrpc": "2.0", "method": method})

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        proc = self._proc
        assert proc is not None and proc.stdout is not None

        async def read_reply() -> dict[str, Any]:
            while True:
                line = await proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise self._died()
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # ligne de journal parasite
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
                # notifications et requêtes du serveur : ignorées (aucune capacité déclarée)

        try:
            reply = await asyncio.wait_for(read_reply(), timeout=self.timeout)
        except TimeoutError as exc:
            raise AppUnavailableError(
                f"Atelier Tab n'a pas répondu en {self.timeout:g} s.", app=self.app
            ) from exc
        if "error" in reply:
            err = reply["error"] if isinstance(reply["error"], dict) else {}
            raise AppRequestError(
                f"Atelier Tab : {err.get('message') or 'erreur du serveur MCP'}", app=self.app
            )
        result = reply.get("result")
        if not isinstance(result, dict):
            raise AppRequestError("Réponse du serveur MCP d'Atelier Tab illisible.", app=self.app)
        return result

    async def call_raw(self, tool: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
        """Appelle un outil de Tab ; renvoie (refusé ?, résultat JSON décodé si possible, sinon
        texte). Un refus n'est pas levé : l'appelant lit le `{detail, code}` éventuel."""
        async with self._lock:
            await self._start()
            result = await self._rpc("tools/call", {"name": tool, "arguments": arguments})
        texts = [
            c.get("text", "")
            for c in result.get("content", [])
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t).strip()
        first = texts[0] if texts else ""
        try:
            return bool(result.get("isError")), json.loads(first)
        except ValueError:
            return bool(result.get("isError")), text

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        """Appelle un outil de Tab ; renvoie son résultat (JSON décodé si possible, sinon texte)."""
        refused, value = await self.call_raw(tool, arguments)
        if refused:
            if isinstance(value, dict) and isinstance(value.get("detail"), str):
                text = value["detail"]
            else:
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            raise AppRequestError(text or f"Atelier Tab a refusé « {tool} ».", app=self.app)
        return value

    async def list_tools(self) -> list[str]:
        async with self._lock:
            await self._start()
            result = await self._rpc("tools/list", {})
        return [t.get("name", "") for t in result.get("tools", []) if isinstance(t, dict)]


# ─── Outils d'écriture (boîte `tab_write`, validation obligatoire) ──────────

CellValue = str | float | bool | None
StatusPreset = Literal["atelier"]


def _value(v: CellValue) -> str:
    if v is None:
        return "(vide)"
    if isinstance(v, bool):
        return "oui" if v else "non"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    text = str(v)
    return text if len(text) <= 40 else text[:39] + "…"


def _rows_text(rows: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in rows:
        cells = r.get("cells") or {}
        shown = ", ".join(f"{k} = {fmt(v)}" for k, v in cells.items() if v not in (None, ""))
        out.append(f"- ligne {r.get('row')} ({r.get('id')}) : {shown or 'vide'}")
    return out


class _TabWriteTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)
    requires_approval = True

    def __init__(self, client: TabMcpClient) -> None:
        self.client = client


class CellEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int | str = Field(description="Numéro de ligne affiché (1 = première) ou id rec_….")
    column: str = Field(min_length=1, max_length=100, description="Lettre, libellé ou id.")
    value: CellValue = Field(
        description='Comme une saisie dans la grille : "45 000", "30/11/2026", "En cours", "=SUM(C1:C3)" ; null vide la cellule.'
    )


class SetCellsInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    cells: list[CellEdit] = Field(min_length=1, max_length=100)


class SetCellsTool(_TabWriteTool[SetCellsInput]):
    name = "tab_set_cells"
    description = (
        "Modifie des cellules d'une table d'Atelier Tab (valeurs saisies comme dans la grille, "
        'formules comprises). Ex. cells = [{"row": 2, "column": "C", "value": "30 000"}]. '
        "Action soumise à validation."
    )
    input_model = SetCellsInput

    def approval_summary(self, params: SetCellsInput) -> str:
        edits = ", ".join(f"{c.column}{c.row} = {_value(c.value)}" for c in params.cells[:6])
        more = f" (+{len(params.cells) - 6})" if len(params.cells) > 6 else ""
        return (
            f"Modifier {len(params.cells)} cellule(s) de la table {params.table_id} : {edits}{more}"
        )

    async def run(self, params: SetCellsInput, ctx: ToolContext) -> ToolOutput:
        result = await self.client.call(
            "set_cells",
            {"table": params.table_id, "cells": [c.model_dump() for c in params.cells]},
        )
        updated = result.get("updated", []) if isinstance(result, dict) else []
        lines = [f"{len(updated)} cellule(s) modifiée(s) :"]
        for u in updated:
            err = f" ⚠ {u['error']}" if u.get("error") else ""
            lines.append(f"- {u.get('cell')} = {fmt(u.get('value'))}{err}")
        return ToolOutput(content="\n".join(lines))


class AddRowsInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    rows: list[dict[str, CellValue]] = Field(
        min_length=1,
        max_length=100,
        description='Une ligne = {colonne: valeur} (lettre, libellé ou id), ex. [{"Lot / Tâche": '
        '"Plomberie", "Coût HT": "12 000", "Statut": "À faire"}].',
    )
    before_row: int | None = Field(
        default=None,
        gt=0,
        description="Insérer avant cette ligne ; par défaut avant la ligne de total.",
    )


class AddRowsTool(_TabWriteTool[AddRowsInput]):
    name = "tab_add_rows"
    description = (
        "Ajoute des lignes à une table d'Atelier Tab, juste au-dessus de la ligne de total par "
        "défaut (elle les inclut alors dans ses sommes). Action soumise à validation."
    )
    input_model = AddRowsInput

    def approval_summary(self, params: AddRowsInput) -> str:
        firsts = [
            _value(next((v for v in row.values() if v not in (None, "")), None))
            for row in params.rows[:4]
        ]
        names = ", ".join(f"« {n} »" for n in firsts)
        more = f" (+{len(params.rows) - 4})" if len(params.rows) > 4 else ""
        where = f" avant la ligne {params.before_row}" if params.before_row else ""
        return f"Ajouter {len(params.rows)} ligne(s) à la table {params.table_id}{where} : {names}{more}"

    async def run(self, params: AddRowsInput, ctx: ToolContext) -> ToolOutput:
        args: dict[str, Any] = {"table": params.table_id, "rows": params.rows}
        if params.before_row:
            args["before_row"] = params.before_row
        result = await self.client.call("add_rows", args)
        added = result.get("added", []) if isinstance(result, dict) else []
        return ToolOutput(
            content="\n".join([f"{len(added)} ligne(s) ajoutée(s) :", *_rows_text(added)])
        )


class DeleteRowsInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    rows: list[int | str] = Field(
        min_length=1, max_length=100, description="Numéros affichés ou ids rec_…."
    )
    titles: list[str] = Field(
        min_length=1,
        max_length=100,
        description="Pour chaque ligne, dans le même ordre, son titre (ou une valeur qui "
        'l\'identifie) tel que lu par tab_read_table ; "" pour une ligne entièrement vide. Ex. '
        'rows = [5, 7], titles = ["Plomberie", "Peinture"]. Rien n\'est supprimé si une ligne '
        "ne le contient plus.",
    )

    @model_validator(mode="after")
    def _one_title_per_row(self) -> DeleteRowsInput:
        if len(self.titles) != len(self.rows):
            raise ValueError("Donner un titre par ligne à supprimer, dans le même ordre (titles).")
        if len({str(r).strip() for r in self.rows}) != len(self.rows):
            raise ValueError("Une ligne est citée deux fois.")
        return self


#: Lignes lues par appel de `read_table` (maximum du serveur MCP de Tab)
READ_PAGE = 500
#: Titres attendus d'une ligne sans aucune valeur (`_value(None)` affiche « (vide) »)
EMPTY_TITLES = frozenset({"", "(vide)"})
#: Caractères au moins avant « … » pour qu'un début de titre désigne une ligne : « P… » vaudrait
#: pour toute ligne qui commence par P
MIN_PREFIX = 4


def _row_number(ref: int | str) -> int | None:
    """Numéro affiché d'une référence de ligne (`5` ou `"5"`), None pour un id `rec_…`."""
    if isinstance(ref, int):
        return ref
    return int(ref) if ref.strip().isdigit() else None


def _norm(text: str) -> str:
    """Casse, accents et espaces ignorés ; les autres caractères (œ, emoji, idéogrammes) sont
    gardés, pour qu'un titre qui n'en contient pas d'autres ne devienne jamais vide."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _same_text(expected: str, value: Any) -> bool:
    """Valeur de cellule = titre attendu (casse, accents et espaces ignorés) ; un titre recopié
    tronqué (« Charpente bois et couv… ») vaut pour son début, s'il a au moins `MIN_PREFIX`
    caractères (sinon il est comparé tel quel, points compris)."""
    if value is None or isinstance(value, bool):
        return False
    shown = _value(value) if isinstance(value, float) else str(value)
    text = expected.strip()
    prefix = _norm(text.rstrip("…. ")) if text.endswith(("…", "...")) else ""
    got = _norm(shown)
    if len(prefix) >= MIN_PREFIX:
        return got.startswith(prefix)
    want = _norm(text)
    return bool(want) and want == got


def _shown_title(title: CellValue) -> str:
    """Titre d'une ligne dans une carte ou un résultat : « Plomberie », ou « ligne vide »."""
    if title is None or (isinstance(title, str) and title.strip() in EMPTY_TITLES):
        return "ligne vide"
    return f"« {_value(title)} »"


def _title_match(expected: str, cells: dict[str, Any]) -> tuple[bool, CellValue]:
    """(la ligne correspond ?, valeur reconnue) ; un titre vide ne désigne qu'une ligne vide."""
    if expected.strip() in EMPTY_TITLES:
        return all(_is_blank(v) for v in cells.values()), None
    match = next((v for v in cells.values() if _same_text(expected, v)), None)
    return match is not None, match


class DeleteRowsTool(_TabWriteTool[DeleteRowsInput]):
    name = "tab_delete_rows"
    description = (
        "Supprime des lignes d'une table d'Atelier Tab ; les formules qui les lisaient sont "
        "ajustées comme dans Excel. Le titre de chaque ligne est vérifié juste avant : une "
        "ligne décalée ou modifiée entre-temps n'est jamais supprimée. Action soumise à validation."
    )
    input_model = DeleteRowsInput

    def approval_summary(self, params: DeleteRowsInput) -> str:
        shown = [
            f"{_shown_title(t)} ({'ligne ' + str(r) if _row_number(r) else r})"
            for r, t in zip(params.rows[:10], params.titles[:10], strict=True)
        ]
        more = f" (+{len(params.rows) - 10})" if len(params.rows) > 10 else ""
        return (
            f"Supprimer définitivement {len(params.rows)} ligne(s) de la table "
            f"{params.table_id} : {', '.join(shown)}{more}"
        )

    async def _read_rows(self, table_id: str) -> list[dict[str, Any]]:
        """Toutes les lignes de la table telles que Tab les voit à l'instant (serveur MCP :
        même store que l'app, aucun retard d'instantané)."""
        rows: list[dict[str, Any]] = []
        while True:
            page = await self.client.call(
                "read_table", {"table": table_id, "offset": len(rows), "limit": READ_PAGE}
            )
            if not isinstance(page, dict):
                raise AppRequestError("Lecture de la table illisible.", app="tab")
            batch = [r for r in page.get("rows", []) if isinstance(r, dict)]
            rows += batch
            if not batch or len(rows) >= int(page.get("total_rows") or 0):
                return rows

    async def run(self, params: DeleteRowsInput, ctx: ToolContext) -> ToolOutput:
        current = await self._read_rows(params.table_id)
        by_number = {r.get("row"): r for r in current}
        by_id = {r.get("id"): r for r in current}
        problems: list[str] = []
        targets: list[tuple[dict[str, Any], CellValue]] = []
        for ref, title in zip(params.rows, params.titles, strict=True):
            number = _row_number(ref)
            row = by_number.get(number) if number else by_id.get(str(ref).strip())
            where = f"ligne {number}" if number else str(ref)
            if row is None:
                problems.append(f"{where} introuvable (la table a {len(current)} ligne(s))")
                continue
            if not isinstance(row.get("id"), str):  # sans id stable, rien ne part
                raise AppRequestError("Lecture de la table illisible (ligne sans id).", app="tab")
            if any(row is other for other, _ in targets):  # même ligne par numéro et par id
                problems.append(f"{where} citée deux fois (numéro et id {row['id']})")
                continue
            raw = row.get("cells")
            cells: dict[str, Any] = raw if isinstance(raw, dict) else {}
            matched, value = _title_match(title, cells)
            if not matched:
                found = next((v for v in cells.values() if not _is_blank(v)), None)
                expected = (
                    "n'est pas vide"
                    if title.strip() in EMPTY_TITLES
                    else f"ne contient pas « {_value(title)} »"
                )
                problems.append(
                    f"{where} {expected}"
                    + (f" (on y lit « {_value(found)} »)" if found is not None else " (ligne vide)")
                )
                continue
            targets.append((row, value))
        if problems:
            return ToolOutput(
                content="Suppression refusée, rien n'a été supprimé : "
                + " ; ".join(problems)
                + ". Relis la table (tab_read_table) puis propose de nouveau la suppression.",
                is_error=True,
            )
        # Suppression par identifiant stable (rec_…) : les numéros vérifiés ne peuvent plus glisser
        result = await self.client.call(
            "delete_rows", {"table": params.table_id, "rows": [r.get("id") for r, _ in targets]}
        )
        gone = ", ".join(f"{_shown_title(t)} (ligne {r.get('row')})" for r, t in targets[:10]) + (
            f" (+{len(targets) - 10})" if len(targets) > 10 else ""
        )
        if not isinstance(result, dict):
            return ToolOutput(content=f"Supprimé : {gone}. {result}")
        return ToolOutput(
            content=f"{result.get('deleted')} ligne(s) supprimée(s) : {gone} ; "
            f"{result.get('remaining_rows')} restante(s)."
        )


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=100)
    type: ColumnType
    formula: str | None = Field(
        default=None, description='Pour type=formula : formule de la ligne 1, ex. "=C1*1.2".'
    )
    format: Literal["number", "currency", "percent", "text"] | None = None
    choices: list[str] | None = Field(default=None, max_length=30, description="Pour type=select.")
    preset: StatusPreset | None = Field(
        default=None, description="« atelier » : les 8 statuts de la suite."
    )
    mapping: Literal[tuple(MAPPING_LABELS)] | None = Field(  # type: ignore[valid-type]
        default=None, description="Rôle de la colonne à l'export vers Atelier Projets."
    )

    @model_validator(mode="after")
    def _formula(self) -> ColumnSpec:
        if self.type == "formula" and not self.formula:
            raise ValueError("Une colonne formula a besoin de sa formule pour la ligne 1.")
        if self.preset and self.type != "select":
            raise ValueError("Le préréglage de statuts ne vaut que pour type=select.")
        return self


class AddColumnInput(ColumnSpec, ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    position: str | None = Field(
        default=None, description="Insérer avant cette colonne ; par défaut à la fin."
    )


class AddColumnTool(_TabWriteTool[AddColumnInput]):
    name = "tab_add_column"
    description = (
        "Ajoute une colonne typée à une table d'Atelier Tab ; une colonne formula est recopiée "
        "sur chaque ligne. Action soumise à validation."
    )
    input_model = AddColumnInput

    def approval_summary(self, params: AddColumnInput) -> str:
        extra = f" {params.formula}" if params.formula else ""
        return f"Ajouter la colonne « {params.label} » ({TYPE_LABELS[params.type]}{extra}) à la table {params.table_id}"

    async def run(self, params: AddColumnInput, ctx: ToolContext) -> ToolOutput:
        args = params.model_dump(exclude_none=True, exclude={"table_id"})
        result = await self.client.call("add_column", {"table": params.table_id, **args})
        col = result.get("added", {}) if isinstance(result, dict) else {}
        return ToolOutput(
            content=f"Colonne {col.get('letter')} « {col.get('label')} » ajoutée ({TYPE_LABELS.get(col.get('type', ''), col.get('type'))})."
        )


class CreateTableInput(ToolInput):
    project: str = Field(min_length=1, max_length=200, description="Projet Tab : id ou nom.")
    name: str = Field(min_length=1, max_length=200)
    columns: list[ColumnSpec] | None = Field(default=None, max_length=40)


class CreateTableTool(_TabWriteTool[CreateTableInput]):
    name = "tab_create_table"
    description = (
        "Crée une table dans un projet d'Atelier Tab, avec les colonnes données (sinon Nom, "
        "Statut, Notes). Action soumise à validation. Remplir ensuite avec tab_add_rows."
    )
    input_model = CreateTableInput

    def approval_summary(self, params: CreateTableInput) -> str:
        cols = ", ".join(c.label for c in (params.columns or [])[:8]) or "Nom, Statut, Notes"
        return f"Créer la table « {params.name} » dans le projet « {params.project} » (colonnes : {cols})"

    async def run(self, params: CreateTableInput, ctx: ToolContext) -> ToolOutput:
        args = params.model_dump(exclude_none=True)
        result = await self.client.call("create_table", args)
        if not isinstance(result, dict):
            return ToolOutput(content=str(result))
        cols = ", ".join(f"{c.get('letter')} {c.get('label')}" for c in result.get("columns", []))
        return ToolOutput(content=f"Table {result.get('table_id')} créée : {cols}.")


def tab_write_tools(client: TabMcpClient) -> list[BaseTool[Any]]:
    return [
        SetCellsTool(client),
        AddRowsTool(client),
        DeleteRowsTool(client),
        AddColumnTool(client),
        CreateTableTool(client),
    ]
