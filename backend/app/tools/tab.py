"""Connecteur Atelier Tab — tables du tableur, en lecture, depuis ses instantanés DataFlow.

Atelier Tab n'a pas d'API HTTP : l'app de bureau publie chaque table dans
`~/Atelier_Tab/exports/<id de table>.json` (enveloppe DataFlow v2.1.0, valeurs calculées
par son moteur de formules), à chaque enregistrement. On lit ces fichiers, comme Atelier
Viz, avec les mêmes garde-fous : nom de fichier sûr, pas de lien hors du dossier, taille
plafonnée, fichier à moitié écrit ignoré.

Les exports manuels (`atelier_projets_<projet>_<date>.json`) partagent le dossier : pour
une même table, l'instantané (nom de fichier = id de la table) l'emporte, sinon l'export
le plus récent. L'écriture dans Tab passe par son serveur MCP : hors du périmètre ici.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.schemas.tab import (
    FORMULA_ERRORS,
    MAPPING_LABELS,
    Cell,
    Column,
    Envelope,
    Record,
    TableInfo,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import data_artifact, fmt, markdown_table, table_for_model
from app.tools.http import AppError, AppNotFoundError, AppRequestError, AppUnavailableError

FILE_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,199}$")
TABLE_ID = r"^[A-Za-z0-9_-]{1,200}$"
TYPE_LABELS = {
    "text": "texte",
    "number": "nombre",
    "currency": "montant",
    "percent": "pourcentage",
    "select": "choix",
    "date": "date",
    "checkbox": "case à cocher",
    "owner": "responsable",
    "formula": "formule",
}
DONE_STATES = {
    "termine", "terminee", "resolu", "resolue", "rejete", "rejetee", "fait", "clos", "close",
    "done", "annule", "annulee", "livre", "livree", "valide", "validee",
}  # fmt: skip

_CACHE: dict[tuple[str, int, int], Envelope | None] = {}
_CACHE_MAX = 256


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


class TabSnapshots:
    """Lecture du dossier d'instantanés (même interface d'erreurs que les clients HTTP)."""

    app = "tab"
    label = "Atelier Tab"

    def __init__(self, folder: str, *, max_mb: int = 50) -> None:
        self.folder_setting = folder
        self.max_bytes = max_mb * 1024 * 1024

    @classmethod
    def from_settings(cls, settings: Settings) -> TabSnapshots | None:
        if not settings.tab_exports_dir:
            return None
        return cls(settings.tab_exports_dir, max_mb=settings.tab_max_snapshot_mb)

    async def aclose(self) -> None:
        return None

    def _folder(self) -> Path:
        folder = Path(self.folder_setting).expanduser()
        if not folder.is_dir():
            raise AppUnavailableError(
                f"Dossier des instantanés d'Atelier Tab introuvable ({folder}). Ouvrez l'app de "
                "bureau Atelier Tab au moins une fois : le mode navigateur n'écrit rien sur le disque.",
                app=self.app,
            )
        return folder.resolve()

    def _load(self, path: Path, mtime_ns: int, size: int) -> Envelope | None:
        key = (str(path), mtime_ns, size)
        if key in _CACHE:
            return _CACHE[key]
        envelope: Envelope | None = None
        try:
            with path.open("rb") as fh:
                raw = fh.read(self.max_bytes + 1)
            if len(raw) <= self.max_bytes:
                envelope = Envelope.model_validate(json.loads(raw.decode("utf-8-sig")))
        except (OSError, ValueError, ValidationError):
            envelope = None  # pas une enveloppe, version inconnue ou fichier en cours d'écriture
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = envelope
        return envelope

    def _scan(self) -> tuple[dict[str, tuple[Envelope, TableInfo]], list[str]]:
        folder = self._folder()
        best: dict[str, tuple[Envelope, TableInfo]] = {}
        too_big: list[str] = []
        for path in sorted(folder.glob("*.json")):
            if not FILE_STEM.match(path.stem):
                continue
            try:
                real = path.resolve(strict=True)
                if not real.is_relative_to(folder) or not real.is_file():
                    continue
                stat = real.stat()
            except OSError:
                continue
            if stat.st_size > self.max_bytes:
                too_big.append(path.name)
                continue
            env = self._load(real, stat.st_mtime_ns, stat.st_size)
            if env is None:
                continue
            snapshot = path.stem == env.table_id
            info = TableInfo(
                id=env.table_id,
                name=env.table_name,
                project=env.project.name,
                workspace=env.workspace.name,
                rows=len(env.project.records),
                columns=len(env.project.columns_schema),
                exported_at=env.exported_at,
                source="instantané" if snapshot else "export manuel",
                file=path.name,
            )
            current = best.get(info.id)
            if current is None or (
                (info.source == "instantané", info.exported_at)
                > (current[1].source == "instantané", current[1].exported_at)
            ):
                best[info.id] = (env, info)
        return best, too_big

    async def tables(self) -> tuple[list[TableInfo], list[str]]:
        best, too_big = await asyncio.to_thread(self._scan)
        infos = sorted(
            (info for _, info in best.values()),
            key=lambda t: (_plain(t.workspace), _plain(t.project), _plain(t.name)),
        )
        return infos, too_big

    async def table(self, table_id: str) -> tuple[Envelope, TableInfo]:
        if not re.match(TABLE_ID, table_id):
            raise AppRequestError("Identifiant de table invalide.", app=self.app)
        best, _ = await asyncio.to_thread(self._scan)
        if table_id not in best:
            raise AppNotFoundError(
                f"Table « {table_id} » introuvable dans les instantanés d'Atelier Tab "
                "(voir tab_list_tables).",
                app=self.app,
            )
        return best[table_id]


# ─── Valeurs et colonnes ──────────────────────────────────────────


def number(cell: Cell | None) -> float | None:
    if cell is None or isinstance(cell.computed, bool):
        return None
    return float(cell.computed) if isinstance(cell.computed, int | float) else None


def is_error(cell: Cell | None) -> bool:
    return cell is not None and isinstance(cell.computed, str) and cell.computed in FORMULA_ERRORS


def display(column: Column, cell: Cell | None) -> Any:
    """Valeur lisible : pourcentages en %, cases en oui/non, erreurs telles quelles."""
    if cell is None or cell.computed is None or cell.computed == "":
        return None
    value = cell.computed
    if column.type == "percent" and isinstance(value, int | float) and not isinstance(value, bool):
        return f"{fmt(value * 100)} %"
    return value


def text_of(column: Column, cell: Cell | None) -> str:
    value = display(column, cell)
    return "" if value is None else fmt(value)


def resolve_column(columns: list[Column], name: str) -> Column:
    """Colonne désignée par son libellé, son identifiant ou sa lettre (insensible à la casse)."""
    wanted = _plain(name)
    for col in columns:
        if wanted in (_plain(col.label), _plain(col.id)) or name.strip().upper() == col.col_letter:
            return col
    labels = ", ".join(f"« {c.label or c.id} »" for c in columns)
    raise AppRequestError(f"Colonne « {name} » inconnue. Colonnes : {labels}.", app="tab")


def by_role(columns: list[Column], role: str) -> Column | None:
    return next((c for c in columns if c.atelier_mapping == role), None)


def schema_lines(env: Envelope) -> list[str]:
    return [
        f"- {c.col_letter} « {c.label or c.id} » : {TYPE_LABELS[c.type]}"
        + (
            f", rôle {MAPPING_LABELS.get(c.atelier_mapping, c.atelier_mapping)}"
            if c.atelier_mapping != "custom"
            else ""
        )
        for c in env.project.columns_schema
    ]


def sorted_records(records: list[Record]) -> list[Record]:
    return sorted(records, key=lambda r: r.row_index)


# ─── Outils ───────────────────────────────────────────────────────


class _TabTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)

    def __init__(self, snapshots: TabSnapshots) -> None:
        self.snapshots = snapshots


class NoInput(ToolInput):
    pass


class ListTablesTool(_TabTool[NoInput]):
    name = "tab_list_tables"
    description = (
        "Tables d'Atelier Tab disponibles (espace › projet › table), avec nombre de lignes et "
        "de colonnes et date de la dernière modification."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        infos, too_big = await self.snapshots.tables()
        if not infos:
            return ToolOutput(
                content="Aucune table publiée par Atelier Tab pour l'instant (ouvrez l'app de bureau "
                "et enregistrez une table)."
            )
        rows = [
            [t.id, t.workspace, t.project, t.name, t.rows, t.columns,
             t.exported_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"), t.source]
            for t in infos
        ]  # fmt: skip
        text = markdown_table(
            ["id", "espace", "projet", "table", "lignes", "colonnes", "modifiée le", "source"], rows
        )
        if too_big:
            text += f"\nIgnorées car trop volumineuses : {', '.join(too_big)}."
        return ToolOutput(content=f"{len(infos)} table(s).\n{text}")


class ReadTableInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID, description="Identifiant donné par tab_list_tables.")
    columns: list[str] | None = Field(
        default=None, max_length=30, description="Colonnes à garder (libellé, id ou lettre)."
    )
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class ReadTableTool(_TabTool[ReadTableInput]):
    name = "tab_read_table"
    description = (
        "Contenu d'une table d'Atelier Tab : colonnes (type, rôle), lignes avec les valeurs "
        "calculées par ses formules, lignes de total. Pourcentages affichés en %."
    )
    input_model = ReadTableInput

    async def run(self, params: ReadTableInput, ctx: ToolContext) -> ToolOutput:
        env, info = await self.snapshots.table(params.table_id)
        all_cols = env.project.columns_schema
        cols = [resolve_column(all_cols, n) for n in params.columns] if params.columns else all_cols
        headers = ["ligne", *[c.label or c.id for c in cols]]
        records = sorted_records(env.project.records)
        rows = [
            [r.row_index, *[display(c, r.values.get(c.col_letter)) for c in cols]] for r in records
        ]
        page = rows[params.offset : params.offset + params.limit]
        lines = [
            f"Table « {info.name} » (projet {info.project}, espace {info.workspace}) : "
            f"{len(records)} ligne(s), modifiée le {info.exported_at:%Y-%m-%d %H:%M} UTC ({info.source}).",
            "Colonnes :",
            *schema_lines(env),
            "",
            f"Lignes {params.offset + 1} à {params.offset + len(page)} :"
            if page
            else "Aucune ligne dans cette plage.",
        ]
        if page:
            lines.append(markdown_table(headers, page))
        if params.offset + len(page) < len(rows):
            lines.append(
                f"[{len(rows) - params.offset - len(page)} ligne(s) suivante(s) : offset={params.offset + len(page)}]"
            )
        totals = sorted_records(env.project.summary_rows)
        if totals:
            lines.append("\nLignes de total (exclues des calculs) :")
            lines.append(
                markdown_table(
                    headers,
                    [
                        [r.row_index, *[display(c, r.values.get(c.col_letter)) for c in cols]]
                        for r in totals
                    ],
                )
            )
        artifacts = []
        if len(rows) > len(page):
            numeric = {c.label or c.id for c in cols if c.type in ("number", "currency", "formula")}
            artifacts.append(data_artifact(f"Tab · {info.name}", headers, rows, numeric=numeric))
        return ToolOutput(content="\n".join(lines), artifacts=artifacts)


class Measure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=100)
    agg: Literal["sum", "avg", "min", "max", "count"] = "sum"


class AggregateInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    measures: list[Measure] = Field(min_length=1, max_length=6)
    group_by: str | None = Field(default=None, description="Colonne de regroupement (ex. Statut).")
    filters: dict[str, str] | None = Field(
        default=None, description='Égalité sur la valeur affichée, ex. {"Statut": "En cours"}.'
    )


AGG_LABELS = {"sum": "somme", "avg": "moyenne", "min": "min", "max": "max", "count": "nombre"}


class AggregateTool(_TabTool[AggregateInput]):
    name = "tab_aggregate"
    description = (
        "Calcule des totaux sur une table d'Atelier Tab (somme, moyenne, min, max, nombre), "
        "éventuellement par groupe et après filtre. Les lignes de total et les erreurs de "
        "formule sont exclues. Préférer cet outil au calcul de tête."
    )
    input_model = AggregateInput

    async def run(self, params: AggregateInput, ctx: ToolContext) -> ToolOutput:
        env, info = await self.snapshots.table(params.table_id)
        cols = env.project.columns_schema
        group = resolve_column(cols, params.group_by) if params.group_by else None
        measures = [(resolve_column(cols, m.column), m.agg) for m in params.measures]
        filters = [(resolve_column(cols, k), _plain(v)) for k, v in (params.filters or {}).items()]

        records = [
            r
            for r in env.project.records
            if all(_plain(text_of(c, r.values.get(c.col_letter))) == v for c, v in filters)
        ]
        groups: dict[str, list[Record]] = defaultdict(list)
        for r in records:
            key = text_of(group, r.values.get(group.col_letter)) if group else "Total"
            groups[key or "(vide)"].append(r)

        skipped = 0
        rows = []
        for key, members in sorted(groups.items(), key=lambda kv: _plain(kv[0])):
            row: list[Any] = [key, len(members)] if group else [len(members)]
            for col, agg in measures:
                cells = [r.values.get(col.col_letter) for r in members]
                skipped += sum(is_error(c) for c in cells)
                if agg == "count":
                    row.append(
                        sum(1 for c in cells if c is not None and c.computed not in (None, ""))
                    )
                    continue
                nums = [n for n in (number(c) for c in cells) if n is not None]
                if not nums:
                    row.append(None)
                elif agg == "sum":
                    row.append(round(sum(nums), 6))
                elif agg == "avg":
                    row.append(round(sum(nums) / len(nums), 6))
                else:
                    row.append(min(nums) if agg == "min" else max(nums))
            rows.append(row)

        headers = ([group.label or group.id] if group else []) + ["lignes"]
        headers += [f"{AGG_LABELS[agg]} {col.label or col.id}" for col, agg in measures]
        table, truncated = table_for_model(headers, rows, noun="groupe")
        text = f"Table « {info.name} », {len(records)} ligne(s) retenue(s) sur {len(env.project.records)}.\n{table}"
        if any(col.type == "percent" for col, _ in measures):
            text += "\nLes pourcentages sont des fractions (0,2 = 20 %)."
        if skipped:
            text += (
                f"\n{skipped} cellule(s) en erreur de formule ignorée(s) (voir tab_check_table)."
            )
        artifacts = (
            [data_artifact(f"Tab · {info.name} · totaux", headers, rows)] if truncated else []
        )
        return ToolOutput(content=text, artifacts=artifacts)


class CheckInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID)
    as_of: date | None = Field(
        default=None, description="Date de référence (aujourd'hui par défaut)."
    )


class CheckTableTool(_TabTool[CheckInput]):
    name = "tab_check_table"
    description = (
        "Contrôle d'une table d'Atelier Tab : erreurs de formule (#DIV/0!, #REF!…), titres "
        "vides ou en double, échéances dépassées non terminées, responsables manquants, "
        "et préparation à l'import dans Atelier Projets."
    )
    input_model = CheckInput

    async def run(self, params: CheckInput, ctx: ToolContext) -> ToolOutput:
        env, info = await self.snapshots.table(params.table_id)
        today = params.as_of or datetime.now(UTC).date()
        cols = env.project.columns_schema
        records = sorted_records(env.project.records)
        findings: list[str] = []

        errors: Counter[str] = Counter()
        where: dict[str, list[int]] = defaultdict(list)
        for r in [*records, *env.project.summary_rows]:
            for c in cols:
                cell = r.values.get(c.col_letter)
                if is_error(cell) and cell is not None:
                    errors[f"{c.label or c.id} : {cell.computed}"] += 1
                    where[f"{c.label or c.id} : {cell.computed}"].append(r.row_index)
        if errors:
            findings.append("Erreurs de formule :")
            findings += [
                f"- {k} ({n} cellule(s), lignes {', '.join(map(str, where[k][:10]))})"
                for k, n in errors.most_common()
            ]

        title = by_role(cols, "entity_title")
        status = by_role(cols, "workflow_state")
        due = by_role(cols, "due_date")
        owner = by_role(cols, "assignee")
        if title:
            empty = [
                r.row_index for r in records if not text_of(title, r.values.get(title.col_letter))
            ]
            if empty:
                findings.append(
                    f"Titre vide (colonne « {title.label} ») : lignes {', '.join(map(str, empty))}."
                )
            seen: dict[str, list[int]] = defaultdict(list)
            for r in records:
                t = _plain(text_of(title, r.values.get(title.col_letter)))
                if t:
                    seen[t].append(r.row_index)
            dupes = [rows for rows in seen.values() if len(rows) > 1]
            if dupes:
                findings.append(
                    "Titres en double : "
                    + "; ".join("lignes " + ", ".join(map(str, d)) for d in dupes)
                    + "."
                )

        if due:
            late = []
            for r in records:
                raw = text_of(due, r.values.get(due.col_letter))
                try:
                    deadline = date.fromisoformat(raw[:10])
                except ValueError:
                    continue
                state = text_of(status, r.values.get(status.col_letter)) if status else ""
                if deadline < today and _plain(state) not in DONE_STATES:
                    name = (
                        text_of(title, r.values.get(title.col_letter))
                        if title
                        else f"ligne {r.row_index}"
                    )
                    late.append(
                        f"- {name} : échéance {deadline.isoformat()}{f', statut {state}' if state else ''}"
                    )
            if late:
                findings.append(f"Échéances dépassées au {today.isoformat()} (non terminées) :")
                findings += late
        if owner:
            missing = [
                r.row_index for r in records if not text_of(owner, r.values.get(owner.col_letter))
            ]
            if missing:
                findings.append(f"Sans responsable : lignes {', '.join(map(str, missing))}.")

        ready = (
            title is not None
            and records
            and not any(not text_of(title, r.values.get(title.col_letter)) for r in records)
        )
        import_note = (
            "Prête pour l'import dans Atelier Projets (colonne de titre renseignée)."
            if ready
            else "Pas encore importable dans Atelier Projets : il faut une colonne au rôle « titre » "
            "(entity_title) renseignée sur chaque ligne."
        )
        head = f"Contrôle de « {info.name} » ({len(records)} ligne(s), au {today.isoformat()}) :"
        body = "\n".join(findings) if findings else "Aucune anomalie détectée."
        return ToolOutput(content=f"{head}\n{body}\n{import_note}")


def tab_tools(snapshots: TabSnapshots) -> list[BaseTool[Any]]:
    return [
        ListTablesTool(snapshots),
        ReadTableTool(snapshots),
        AggregateTool(snapshots),
        CheckTableTool(snapshots),
    ]
