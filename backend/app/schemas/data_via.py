"""Schémas de l'API Data Via (= API REST d'Atelier Viz, `http://127.0.0.1:8000/api`).

Miroir des schémas d'Atelier Viz (`backend/app/schemas/dataset.py` et `query.py`).
- Requêtes envoyées à Data Via : `extra="forbid"` (aucun champ inventé ne part).
- Réponses reçues : types stricts, champs inconnus ignorés, pour qu'un ajout de champ
  côté Atelier Viz ne casse pas le connecteur (compatibilité ascendante).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ColumnType = Literal["number", "string", "date", "boolean"]
Scalar = float | int | str | bool | None
Agg = Literal["sum", "avg", "min", "max", "count", "count_distinct", "median", "calc"]
DateBin = Literal["year", "quarter", "month", "week", "day"]
#: Calculs rapides de Viz (« Afficher la valeur comme ») : cumul annuel, cumul, N-1, écart et
#: évolution vs N-1, moyenne mobile, part du total. `yoy_pct` et `pct_total` sont en points de %.
ShowKind = Literal["ytd", "running", "prev_year", "yoy_diff", "yoy_pct", "moving_avg", "pct_total"]
PERCENT_SHOWS = frozenset({"yoy_pct", "pct_total"})
FilterOp = Literal[
    "in",
    "not_in",
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "contains",
    "is_null",
    "not_null",
]


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─── Jeux de données ──────────────────────────────────────────────


class DataViaHealth(_Response):
    status: Literal["ok"]
    version: str
    environment: str


class ValueCount(_Response):
    value: str
    count: int


class ColumnProfile(_Response):
    name: str
    type: ColumnType
    nulls: int
    distinct: int
    min: Scalar = None
    max: Scalar = None
    mean: float | None = None
    top_values: list[ValueCount] = Field(default_factory=list)
    calculated: bool = False
    expression: str | None = None
    #: Relation d'origine d'une colonne liée (`magasins.ville` → « magasins »)
    related: str | None = None


class CalculatedColumn(_Response):
    name: str
    expression: str


class CalculatedMeasure(_Response):
    name: str
    expression: str
    description: str | None = None


class Relation(_Response):
    """Relation plusieurs-à-un vers un autre jeu (modèle en étoile : fait → dimension). Les
    colonnes du jeu lié apparaissent dans le profil sous le nom `<name>.<colonne>`."""

    name: str
    dataset_id: str
    from_column: str
    to_column: str
    columns: list[str] | None = None


class DatasetModel(_Response):
    columns: list[CalculatedColumn] = Field(default_factory=list)
    measures: list[CalculatedMeasure] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class DatasetOrigin(_Response):
    """Provenance d'un jeu (`AnyOrigin` d'Atelier Viz, `schemas/connection.py`) : une connexion
    (jeu actualisable), ou `kind = "atelier-table"` pour une table publiée par un nœud de
    workflow (`datasets.upsert_table`), sans connexion mais avec une clé externe."""

    kind: str
    refreshed_at: datetime
    connection_id: str | None = None
    connection_name: str | None = None
    key: str | None = None
    table_name: str | None = None
    truncated: bool = False

    @property
    def label(self) -> str:
        """Ce qu'on montre : nom de la connexion, ou « table publiée (clé) »."""
        if self.connection_name:
            return self.connection_name
        return f"table publiée ({self.key})" if self.key else self.kind


class DatasetSummary(_Response):
    id: str
    name: str
    format: str
    rows: int
    columns_count: int
    created_at: datetime
    origin: DatasetOrigin | None = None


class DatasetProfile(DatasetSummary):
    columns: list[ColumnProfile]
    sample: list[dict[str, Any]]
    model: DatasetModel = Field(default_factory=DatasetModel)

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def measure_names(self) -> list[str]:
        return [m.name for m in self.model.measures]


class DatasetRows(_Response):
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


# ─── Langage de requête ───────────────────────────────────────────


class Dimension(_Request):
    """Champ de regroupement ; `bin` tronque une date à une période."""

    field: str = Field(description="Nom exact d'une colonne du jeu de données.")
    bin: DateBin | None = Field(default=None, description="Période pour une colonne date.")

    @property
    def key(self) -> str:
        return f"{self.field}|{self.bin}" if self.bin else self.field


class ShowAs(_Request):
    """Calcul rapide appliqué à une mesure, selon un champ date (sauf `pct_total`)."""

    kind: ShowKind = Field(
        description="ytd (cumul annuel), running (cumul), prev_year (N-1), yoy_diff (écart vs N-1), "
        "yoy_pct (évolution vs N-1, en %), moving_avg (moyenne mobile), pct_total (part du total, en %)."
    )
    date: str | None = Field(
        default=None, description="Colonne date de référence (obligatoire sauf pour pct_total)."
    )
    window: int = Field(default=3, ge=2, le=60, description="Périodes de la moyenne mobile.")

    @model_validator(mode="after")
    def _date_required(self) -> Self:
        if self.kind != "pct_total" and not self.date:
            raise ValueError(f"Le calcul « {self.kind} » demande une colonne date (`date`).")
        return self

    @property
    def suffix(self) -> str:
        return f"@{self.kind}{self.window if self.kind == 'moving_avg' else ''}"


class Measure(_Request):
    """Agrégat. `field` vide avec `count` = nombre de lignes ; `calc` = mesure du modèle ;
    `show` = calcul rapide fait par Viz (cumul, N-1, part du total…)."""

    field: str | None = Field(
        default=None,
        description="Colonne à agréger, ou nom de la mesure calculée si agg = calc.",
    )
    agg: Agg = "sum"
    show: ShowAs | None = Field(
        default=None,
        description='Calcul rapide, ex. {"kind": "pct_total"} ou {"kind": "yoy_pct", "date": "date"}.',
    )

    @property
    def base_key(self) -> str:
        return f"{self.agg}({self.field or '*'})"

    @property
    def key(self) -> str:
        """Clé de la colonne du résultat, comme Viz : `sum(ca)`, `sum(ca)@ytd`, `sum(ca)@moving_avg3`."""
        return self.base_key + (self.show.suffix if self.show else "")


class Filter(_Request):
    field: str
    op: FilterOp = "in"
    values: list[Scalar] = Field(default_factory=list)
    bin: DateBin | None = None

    @model_validator(mode="after")
    def _check_arity(self) -> Self:
        if self.op == "between" and len(self.values) != 2:
            raise ValueError("Le filtre « between » attend exactement deux valeurs (min, max).")
        single = {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}
        if self.op in single and len(self.values) != 1:
            raise ValueError(f"Le filtre « {self.op} » attend exactement une valeur.")
        return self


class Sort(_Request):
    key: str = Field(
        description="Clé d'une colonne de la requête : `champ`, `champ|month`, "
        "`sum(chiffre_affaires)`, `sum(chiffre_affaires)@pct_total`."
    )
    desc: bool = False


class QueryRequest(_Request):
    dataset_id: str
    dimensions: list[Dimension] = Field(default_factory=list, max_length=8)
    measures: list[Measure] = Field(default_factory=list, max_length=12)
    filters: list[Filter] = Field(default_factory=list)
    sort: list[Sort] = Field(default_factory=list)
    limit: int = Field(default=5000, ge=1, le=50_000)

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.dimensions and not self.measures:
            raise ValueError("Une requête doit contenir au moins une dimension ou une mesure.")
        return self


class QueryColumn(_Response):
    key: str
    field: str | None
    role: Literal["dimension", "measure", "grouping"]
    type: ColumnType


class QueryResponse(_Response):
    columns: list[QueryColumn]
    rows: list[list[Scalar]]
    truncated: bool = False


# ─── Vérification d'expression (mesures / colonnes calculées) ─────


class ExpressionCheck(_Request):
    kind: Literal["column", "measure"]
    name: str = Field(default="", max_length=80)
    expression: str = Field(max_length=2000)


class ExpressionResult(_Response):
    ok: bool
    type: ColumnType | None = None
    error: str | None = None
    position: int | None = None
    preview: list[Scalar] = Field(default_factory=list)


# ─── Vérification d'une relation (modèle en étoile), sans enregistrement ──


class RelationDraft(_Request):
    """Corps de `POST /datasets/{id}/relations/check` (schéma `Relation` de Viz). `name` n'est
    qu'un préfixe de colonnes : la vérification ne l'utilise pas."""

    name: str = Field(default="relation", min_length=1, max_length=40, pattern=r"^[^.|\[\]\"]+$")
    dataset_id: str = Field(description="Jeu lié, côté « un » (la dimension).")
    from_column: str = Field(min_length=1, description="Colonne de ce jeu (clé étrangère).")
    to_column: str = Field(min_length=1, description="Colonne du jeu lié (clé, valeurs uniques).")


class RelationCheck(_Response):
    ok: bool
    error: str | None = None
    rows: int = 0
    matched: int = 0
    duplicates: int = 0
    unmatched_sample: list[str] = Field(default_factory=list)


# ─── Statut du connecteur (exposé par Atelier Nexus) ──────────────


class DataViaStatus(BaseModel):
    configured: bool
    available: bool
    base_url: str | None
    version: str | None = None
    datasets: int | None = None
    error: str | None = None
