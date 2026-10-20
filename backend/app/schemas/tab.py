"""Enveloppe DataFlow v2.1.0 publiée par Atelier Tab (`~/Atelier_Tab/exports/<table>.json`).

Contrat de référence : `atelier-tab/src/dataflow/schema/atelier.v2_1.ts` et
`docs/DATAFLOW_SPEC.md`. Une enveloppe décrit UNE table. `col_letter` et `row_index`
bougent quand on insère des colonnes ou des lignes : les identifiants stables sont
`columns_schema[].id` et `record_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ColumnType = Literal[
    "text", "number", "currency", "percent", "select", "date", "checkbox", "owner", "formula"
]
#: Codes d'erreur de formule (liste fermée du moteur de Tab)
FORMULA_ERRORS = frozenset(
    {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#N/A", "#CYCLE!", "#ERROR!"}
)
MAPPING_LABELS: dict[str, str] = {
    "entity_title": "titre",
    "workflow_state": "statut",
    "financial_ht": "montant HT",
    "financial_ttc": "montant TTC",
    "assignee": "responsable",
    "due_date": "échéance",
    "start_date": "début",
    "quantity": "quantité",
    "description": "description",
    "flag": "indicateur",
    "custom": "libre",
}

Computed = float | int | str | bool | None


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Ref(_R):
    id: str = Field(min_length=1)
    name: str = ""


class Column(_R):
    col_letter: str = Field(pattern=r"^[A-Z]{1,3}$")
    id: str
    label: str = ""
    type: ColumnType
    atelier_mapping: str = "custom"


class Cell(_R):
    raw: str = ""
    computed: Computed = None


class Record(_R):
    row_index: int
    record_id: str
    values: dict[str, Cell] = Field(default_factory=dict)


class SummaryMetrics(_R):
    total_rows: int = 0
    computed_totals: dict[str, float] = Field(default_factory=dict)


class Project(_R):
    id: str = Field(min_length=1)
    name: str = ""
    source_table: Ref | None = None
    summary_metrics: SummaryMetrics = Field(default_factory=SummaryMetrics)
    columns_schema: list[Column] = Field(min_length=1)
    records: list[Record] = Field(default_factory=list)
    summary_rows: list[Record] = Field(default_factory=list)


class Envelope(_R):
    target_system: Literal["atelier_projets"]
    schema_version: Literal["2.1.0"]
    exported_at: datetime
    workspace: Ref
    project: Project

    @property
    def table_id(self) -> str:
        return self.project.source_table.id if self.project.source_table else self.project.id

    @property
    def table_name(self) -> str:
        st = self.project.source_table
        return (st.name if st and st.name else self.project.name) or "Table Atelier Tab"


class TableInfo(BaseModel):
    id: str
    name: str
    project: str
    workspace: str
    rows: int
    columns: int
    exported_at: datetime
    #: « instantané » (tenu à jour par l'app) ou « export manuel » (fichier daté, figé)
    source: Literal["instantané", "export manuel"]
    file: str
