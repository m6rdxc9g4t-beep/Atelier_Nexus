"""Pont Atelier Tab → Atelier Projets (docs/SUITE.md §4) : une table de Tab devient des
éléments de Projets.

L'enveloppe DataFlow v2.1.0 est lue telle que Tab l'a publiée (`TabSnapshots`, app/tools/tab.py)
puis envoyée à l'import d'Atelier Projets (`ProjetsClient`, app/tools/projets.py) :
- `projets_preview_tab_import` : aperçu (rien n'est modifié), lecture libre ;
- `projets_import_tab_table` : import, soumis à validation, idempotent (la même table, les mêmes
  lignes et les mêmes options rejouées ne créent rien de plus).
Les lignes sont rattachées par `record_id` : réimporter une table met à jour les éléments
déjà créés au lieu de les dupliquer.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from app.schemas.projets import IMPORT_ACTION_LABELS, STATUS_LABELS, ImportResult
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import markdown_table
from app.tools.http import AppError, AppRequestError
from app.tools.projets import ProjetsClient
from app.tools.tab import TABLE_ID, TabSnapshots

NUMERIC = {"number", "currency", "percent", "formula"}


def select_rows(envelope: dict[str, Any], rows: list[int | str] | None) -> dict[str, Any]:
    """Copie de l'enveloppe limitée aux lignes choisies (numéro affiché ou `rec_…`),
    compteurs et totaux recalculés comme le fait Tab (lignes de total exclues)."""
    if not rows:
        return envelope
    project = envelope.get("project", {})
    wanted = {str(r) for r in rows}
    records = [
        r
        for r in project.get("records", [])
        if str(r.get("row_index")) in wanted or str(r.get("record_id")) in wanted
    ]
    found = {str(r.get("row_index")) for r in records} | {str(r.get("record_id")) for r in records}
    missing = sorted(wanted - found)
    if missing:
        raise AppRequestError(
            f"Ligne(s) introuvable(s) dans la table : {', '.join(missing)}.", app="tab"
        )
    out = copy.deepcopy(envelope)
    out["project"]["records"] = records
    totals: dict[str, float] = {}
    for col in project.get("columns_schema", []):
        if col.get("type") not in NUMERIC:
            continue
        letter = col.get("col_letter")
        values = [(r.get("values", {}).get(letter) or {}).get("computed") for r in records]
        nums = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
        if nums:
            totals[letter] = float(f"{sum(nums):.15g}")
    out["project"]["summary_metrics"] = {"total_rows": len(records), "computed_totals": totals}
    return out


def idempotency_key(envelope: dict[str, Any], project_id: int | None, item_type: str | None) -> str:
    """Clé stable : même contenu + mêmes options = même import (rejoué sans effet par Projets)."""
    digest = hashlib.sha256(
        json.dumps([envelope, project_id, item_type], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"nexus-{digest[:40]}"


def describe(result: ImportResult, *, preview: bool) -> str:
    verb = "ferait" if preview else "a fait"
    lines = [
        f"L'import {verb} : {result.created} création(s), {result.updated} mise(s) à jour, "
        f"{result.unchanged} inchangé(s), {result.skipped} ligne(s) ignorée(s)."
    ]
    rows = [
        [
            i.rowIndex,
            i.title or "∅",
            IMPORT_ACTION_LABELS[i.action],
            f"#{i.workItemId}" if i.workItemId else "∅",
            STATUS_LABELS.get(i.status or "", "∅"),
            i.dueDate or "∅",
            i.reason or "",
        ]
        for i in result.items[:50]
    ]
    if rows:
        lines.append(
            markdown_table(
                ["ligne", "titre", "action", "élément", "statut", "échéance", "raison"], rows
            )
        )
    if result.warnings:
        lines.append("Avertissements :")
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


class _BridgeTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)

    def __init__(self, projets: ProjetsClient, snapshots: TabSnapshots) -> None:
        self.projets = projets
        self.snapshots = snapshots

    async def envelope(self, params: TabImportInput) -> tuple[dict[str, Any], str]:
        data, info = await self.snapshots.envelope_json(params.table_id)
        version = data.get("schema_version")
        if version != "2.1.0" or data.get("target_system") != "atelier_projets":
            raise AppRequestError(
                f"Instantané « {info.file} » au format {version} : Atelier Projets attend 2.1.0.",
                app="tab",
            )
        return select_rows(data, params.rows), info.name


class TabImportInput(ToolInput):
    table_id: str = Field(pattern=TABLE_ID, description="Table d'Atelier Tab (tab_list_tables).")
    project_id: int | None = Field(
        default=None,
        gt=0,
        description="Projet cible dans Projets ; sinon le projet du même nom (créé au besoin).",
    )
    type: Literal["FEATURE", "TASK", "BUG"] | None = Field(
        default=None, description="Type des éléments créés (TASK par défaut)."
    )
    rows: list[int | str] | None = Field(
        default=None,
        max_length=1000,
        description="Lignes à importer (numéros ou rec_…) ; par défaut toutes.",
    )


class PreviewTabImportTool(_BridgeTool[TabImportInput]):
    name = "projets_preview_tab_import"
    description = (
        "Aperçu de l'import d'une table d'Atelier Tab dans Atelier Projets : projet, phase, epic et "
        "story cibles, éléments qui seraient créés, mis à jour ou ignorés (et pourquoi). Ne modifie rien. "
        "À appeler avant projets_import_tab_table."
    )
    input_model = TabImportInput

    async def run(self, params: TabImportInput, ctx: ToolContext) -> ToolOutput:
        envelope, name = await self.envelope(params)
        preview = await self.projets.preview_tab_import(
            envelope, project_id=params.project_id, item_type=params.type
        )
        t = preview.target

        def state(exists: bool) -> str:
            return "existant" if exists else "à créer"

        head = [
            f"Table « {name} » → Atelier Projets (aperçu, rien n'est modifié).",
            f"- Projet : {t.project.name}{f' (#{t.project.id})' if t.project.id else ''}, {state(t.project.exists)}",
            f"- Phase « {t.phase.title} » ({state(t.phase.exists)}), epic « {t.epic.title} » "
            f"({state(t.epic.exists)}), story « {t.story.title} » ({state(t.story.exists)})",
            f"- Éléments de type {t.type}",
        ]
        return ToolOutput(content="\n".join([*head, describe(preview, preview=True)]))


class ImportTabTableTool(_BridgeTool[TabImportInput]):
    name = "projets_import_tab_table"
    description = (
        "Importe une table d'Atelier Tab dans Atelier Projets : crée ou met à jour un élément par "
        "ligne (titre, statut, dates, responsable, budget selon les rôles des colonnes). Action "
        "soumise à validation ; rejouer le même import ne crée pas de doublon."
    )
    input_model = TabImportInput
    requires_approval = True

    def approval_summary(self, params: TabImportInput) -> str:
        rows = f"{len(params.rows)} ligne(s)" if params.rows else "toutes les lignes"
        target = f"le projet #{params.project_id}" if params.project_id else "le projet du même nom"
        return (
            f"Importer {rows} de la table {params.table_id} dans Atelier Projets ({target}, "
            f"éléments {params.type or 'TASK'})"
        )

    async def run(self, params: TabImportInput, ctx: ToolContext) -> ToolOutput:
        envelope, name = await self.envelope(params)
        result = await self.projets.import_tab(
            envelope,
            project_id=params.project_id,
            item_type=params.type,
            idempotency_key=idempotency_key(envelope, params.project_id, params.type),
        )
        where = (
            f"projet #{result.projectId}, story #{result.storyId}"
            if result.projectId
            else "Atelier Projets"
        )
        if result.replayed:
            return ToolOutput(
                content=f"Table « {name} » déjà importée telle quelle ({where}) : rien de nouveau. "
                "Modifiez la table dans Atelier Tab pour un nouvel import."
            )
        return ToolOutput(
            content=f"Table « {name} » importée ({where}).\n" + describe(result, preview=False)
        )


def tab_projets_tools(projets: ProjetsClient, snapshots: TabSnapshots) -> list[BaseTool[Any]]:
    return [PreviewTabImportTool(projets, snapshots), ImportTabTableTool(projets, snapshots)]
