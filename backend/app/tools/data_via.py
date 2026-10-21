"""Connecteur Data Via — point d'entrée UNIQUE vers l'API d'Atelier Viz.

Deux couches :
  - `DataViaClient` : client HTTP asynchrone typé (lecture seule), entrées/sorties
    validées par les schémas Pydantic de `app/schemas/data_via.py` ;
  - outils d'agent (`data_via_tools()`) : liste, exploration du schéma, requête
    d'agrégation, vérification d'expression.

Règle « exploration préalable » (CLAUDE.md §3) : `data_via_query` et
`data_via_check_expression` refusent un jeu dont le schéma n'a pas été consulté
par `data_via_describe_dataset` pendant le tour en cours.
"""

from __future__ import annotations

import difflib
import json
from typing import Any, ClassVar, Literal, Self

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.schemas.data_via import (
    DatasetProfile,
    DatasetRows,
    DatasetSummary,
    DataViaHealth,
    DataViaStatus,
    Dimension,
    ExpressionCheck,
    ExpressionResult,
    Filter,
    Measure,
    QueryRequest,
    QueryResponse,
    Sort,
)
from app.tools.base import (
    Artifact,
    BaseTool,
    ToolContext,
    ToolInput,
    ToolOutput,
    register_state_codec,
)
from app.tools.formatting import TableType, atelier_table, table_hint

# ═══ Erreurs ══════════════════════════════════════════════════════


class DataViaError(Exception):
    """Base des erreurs du connecteur."""


class DataViaNotConfiguredError(DataViaError):
    """`DATA_VIA_BASE_URL` absent."""


class DataViaUnavailableError(DataViaError):
    """Atelier Viz injoignable, délai dépassé ou erreur 5xx."""


class DataViaNotFoundError(DataViaError):
    """Jeu de données introuvable (404)."""


class DataViaRequestError(DataViaError):
    """Requête refusée par Data Via (4xx) ou réponse non conforme au contrat."""


# ═══ Client HTTP ══════════════════════════════════════════════════


class DataViaClient:
    """Client lecture seule de l'API Data Via (Atelier Viz)."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:  # Atelier Viz n'en exige pas aujourd'hui ; prévu pour un déploiement protégé
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.AsyncClient(
            base_url=self.base_url + "/",
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> DataViaClient | None:
        if not settings.data_via_base_url:
            return None
        key = settings.data_via_api_key.get_secret_value() if settings.data_via_api_key else None
        return cls(settings.data_via_base_url, api_key=key, timeout=settings.data_via_timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ─── Transport ────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, int] | None = None,
    ) -> Any:
        try:
            response = await self._http.request(method, path, json=json_body, params=params)
        except httpx.TimeoutException as exc:
            raise DataViaUnavailableError(f"Data Via ne répond pas ({self.base_url}).") from exc
        except httpx.TransportError as exc:
            raise DataViaUnavailableError(
                f"Data Via injoignable sur {self.base_url} : Atelier Viz est-il lancé ?"
            ) from exc
        if response.status_code == 404:
            raise DataViaNotFoundError(_detail(response) or "Ressource introuvable.")
        if response.status_code >= 500:
            raise DataViaUnavailableError(f"Data Via : erreur {response.status_code}.")
        if response.status_code >= 400:
            raise DataViaRequestError(_detail(response) or f"Erreur {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise DataViaRequestError("Réponse de Data Via illisible (JSON attendu).") from exc

    async def _get[T: BaseModel](self, model: type[T], path: str, **kw: Any) -> T:
        return _parse(model, await self._request("GET", path, **kw))

    # ─── Endpoints (lecture seule) ────────────────────────────────

    async def health(self) -> DataViaHealth:
        return await self._get(DataViaHealth, "health")

    async def list_datasets(self) -> list[DatasetSummary]:
        data = await self._request("GET", "datasets")
        if not isinstance(data, list):
            raise DataViaRequestError("Liste de jeux de données attendue.")
        return [_parse(DatasetSummary, item) for item in data]

    async def get_dataset(self, dataset_id: str) -> DatasetProfile:
        return await self._get(DatasetProfile, f"datasets/{_segment(dataset_id)}")

    async def get_rows(self, dataset_id: str, *, offset: int = 0, limit: int = 100) -> DatasetRows:
        return await self._get(
            DatasetRows,
            f"datasets/{_segment(dataset_id)}/rows",
            params={"offset": offset, "limit": limit},
        )

    async def query(self, request: QueryRequest) -> QueryResponse:
        data = await self._request("POST", "query", json_body=request.model_dump(mode="json"))
        return _parse(QueryResponse, data)

    async def check_expression(self, dataset_id: str, check: ExpressionCheck) -> ExpressionResult:
        data = await self._request(
            "POST",
            f"datasets/{_segment(dataset_id)}/model/check",
            json_body=check.model_dump(mode="json"),
        )
        return _parse(ExpressionResult, data)

    async def status(self) -> DataViaStatus:
        try:
            health = await self.health()
            datasets = await self.list_datasets()
        except DataViaError as exc:
            return DataViaStatus(
                configured=True, available=False, base_url=self.base_url, error=str(exc)
            )
        return DataViaStatus(
            configured=True,
            available=True,
            base_url=self.base_url,
            version=health.version,
            datasets=len(datasets),
        )


def _segment(value: str) -> str:
    """Identifiant inséré dans un chemin : jamais de « / », « .. » ni d'encodage."""
    if not value or not all(c.isalnum() or c in "-_" for c in value):
        raise DataViaRequestError(f"Identifiant de jeu de données invalide : {value!r}")
    return value


def _detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return str(detail["message"])
    if isinstance(detail, list):  # erreurs de validation FastAPI
        return "; ".join(str(d.get("msg", d)) for d in detail if isinstance(d, dict))
    return None


def _parse[T: BaseModel](model: type[T], data: Any) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise DataViaRequestError(
            f"Réponse de Data Via non conforme au contrat ({model.__name__}) : "
            f"{exc.error_count()} erreur(s)."
        ) from exc


# ═══ Mise en forme pour le modèle ═════════════════════════════════

_DESCRIBED = "data_via.described"
_PROFILES = "data_via.profiles"
MAX_ROWS_FOR_MODEL = 50


def _fmt(value: Any) -> str:
    if value is None:
        return "∅"
    if isinstance(value, float):
        # Jamais de notation scientifique ni de chiffres perdus : le modèle cite ces valeurs
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        text = format(round(value, 4), "f") if abs(value) >= 1 else format(value, ".10f")
        return text.rstrip("0").rstrip(".") or "0"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 60 else text[:57] + "…"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "| " + " | ".join(_fmt(h) for h in headers) + " |"
    sep = "|" + "---|" * len(headers)
    body = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in rows]
    return "\n".join([head, sep, *body])


def describe_for_model(profile: DatasetProfile) -> str:
    """Schéma compact : ce que le modèle doit savoir pour écrire requêtes et mesures."""
    lines = [
        f"Jeu « {profile.name} » (id {profile.id}) : {profile.rows} lignes, "
        f"{profile.columns_count} colonnes, source {profile.format}.",
        "",
        "Colonnes :",
    ]
    for col in profile.columns:
        stats = [f"{col.distinct} valeurs distinctes"]
        if col.nulls:
            stats.append(f"{col.nulls} vides")
        if col.min is not None or col.max is not None:
            stats.append(f"min {_fmt(col.min)} · max {_fmt(col.max)}")
        if col.type == "string" and col.top_values:
            stats.append("ex. " + ", ".join(_fmt(v.value) for v in col.top_values[:5]))
        calc = f" [calculée : {col.expression}]" if col.calculated else ""
        lines.append(f"- `{col.name}` ({col.type}) : {' ; '.join(stats)}{calc}")
    if profile.model.measures:
        lines += ["", "Mesures calculées (à utiliser avec agg = calc) :"]
        lines += [
            f"- `{m.name}` = {m.expression}" + (f" — {m.description}" if m.description else "")
            for m in profile.model.measures
        ]
    if profile.sample:
        headers = [c.name for c in profile.columns]
        sample = [[row.get(h) for h in headers] for row in profile.sample[:5]]
        lines += ["", "Échantillon (5 lignes) :", markdown_table(headers, sample)]
    return "\n".join(lines)


def _suggest(name: str, candidates: list[str]) -> str:
    close = difflib.get_close_matches(name, candidates, n=3, cutoff=0.5)
    return f" Vouliez-vous dire : {', '.join(close)} ?" if close else ""


def validate_query(request: QueryRequest, profile: DatasetProfile) -> list[str]:
    """Contrôle local des champs avant l'appel : erreurs explicites pour le modèle."""
    columns = {c.name: c for c in profile.columns}
    names = list(columns)
    errors: list[str] = []
    for dim in request.dimensions:
        col = columns.get(dim.field)
        if col is None:
            errors.append(f"Dimension inconnue « {dim.field} ».{_suggest(dim.field, names)}")
        elif dim.bin and col.type != "date":
            errors.append(f"« {dim.field} » n'est pas une date : `bin` interdit.")
    for m in request.measures:
        if m.agg == "calc":
            if m.field not in profile.measure_names:
                errors.append(
                    f"Mesure calculée inconnue « {m.field} »."
                    f"{_suggest(m.field or '', profile.measure_names)}"
                )
        elif m.field is None:
            if m.agg != "count":
                errors.append(f"L'agrégat « {m.agg} » exige un champ.")
        elif m.field not in columns:
            errors.append(f"Champ de mesure inconnu « {m.field} ».{_suggest(m.field, names)}")
        elif m.agg in {"sum", "avg", "median"} and columns[m.field].type != "number":
            errors.append(f"« {m.agg} » exige une colonne numérique ; « {m.field} » ne l'est pas.")
    for f in request.filters:
        if f.field not in columns:
            errors.append(f"Champ de filtre inconnu « {f.field} ».{_suggest(f.field, names)}")
    keys = [d.key for d in request.dimensions] + [m.key for m in request.measures]
    for s in request.sort:
        if s.key not in keys:
            errors.append(f"Tri sur « {s.key} » impossible ; clés disponibles : {', '.join(keys)}.")
    return errors


register_state_codec(
    _PROFILES,
    lambda profiles: {k: v.model_dump(mode="json") for k, v in profiles.items()},
    lambda data: {k: DatasetProfile.model_validate(v) for k, v in data.items()},
)


def _require_described(ctx: ToolContext, dataset_id: str) -> DatasetProfile | None:
    profile = ctx.state.get(_PROFILES, {}).get(dataset_id)
    return profile if isinstance(profile, DatasetProfile) else None


_NOT_DESCRIBED = (
    "Schéma non consulté : appelle d'abord `data_via_describe_dataset` avec "
    "dataset_id « {id} » pour vérifier les colonnes et leurs types."
)


# ═══ Outils d'agent ═══════════════════════════════════════════════


class _DataViaTool[InputT: ToolInput](BaseTool[InputT]):
    # Pannes attendues (Viz arrêté, jeu inconnu) : message au modèle, sans trace d'erreur
    expected_errors: ClassVar[tuple[type[Exception], ...]] = (DataViaError,)

    def __init__(self, client: DataViaClient) -> None:
        self.client = client


class ListDatasetsInput(ToolInput):
    pass


_DATASET_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("id", "Identifiant", "string"),
    ("name", "Nom", "string"),
    ("rows", "Lignes", "number"),
    ("columns", "Colonnes", "number"),
    ("connection", "Connexion", "string"),
)


class ListDatasetsTool(_DataViaTool[ListDatasetsInput]):
    name = "data_via_list_datasets"
    description = (
        "Liste les jeux de données disponibles dans Data Via (Atelier Viz) : identifiant, "
        "nom, nombre de lignes et de colonnes. Point de départ de toute analyse."
    )
    input_model = ListDatasetsInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*_DATASET_COLUMNS)

    async def run(self, params: ListDatasetsInput, ctx: ToolContext) -> ToolOutput:
        datasets = await self.client.list_datasets()
        data = atelier_table(
            "datasets",
            "Jeux de données",
            _DATASET_COLUMNS,
            [
                [
                    d.id,
                    d.name,
                    d.rows,
                    d.columns_count,
                    d.origin.connection_name if d.origin else None,
                ]
                for d in datasets
            ],
        )
        if not datasets:
            return ToolOutput(content="Aucun jeu de données dans Data Via.", data=data)
        rows = [
            [d.id, d.name, d.rows, d.columns_count, d.origin.connection_name if d.origin else "—"]
            for d in datasets
        ]
        table = markdown_table(["id", "nom", "lignes", "colonnes", "connexion"], rows)
        return ToolOutput(content=f"{len(datasets)} jeu(x) de données :\n{table}", data=data)


class DescribeDatasetInput(ToolInput):
    dataset_id: str = Field(description="Identifiant renvoyé par data_via_list_datasets.")


class DescribeDatasetTool(_DataViaTool[DescribeDatasetInput]):
    name = "data_via_describe_dataset"
    description = (
        "Renvoie le schéma d'un jeu de données Data Via : colonnes et types, statistiques, "
        "valeurs fréquentes, mesures calculées existantes et un échantillon. OBLIGATOIRE "
        "avant toute requête, formule DAX ou mesure portant sur ce jeu."
    )
    input_model = DescribeDatasetInput
    output_format = "json"
    output_hint = {"fields": ["id", "name", "rows", "columns", "measures"]}

    async def run(self, params: DescribeDatasetInput, ctx: ToolContext) -> ToolOutput:
        profile = await self.client.get_dataset(params.dataset_id)
        ctx.state.setdefault(_PROFILES, {})[profile.id] = profile
        preview = {
            "columns": [c.model_dump(mode="json") for c in profile.columns],
            "measures": [m.model_dump(mode="json") for m in profile.model.measures],
            "sample": profile.sample[:20],
        }
        artifact = Artifact(
            kind="data_preview",
            title=f"Schéma — {profile.name}",
            content=json.dumps(preview, ensure_ascii=False, default=str),
            language="json",
            metadata={"source": "data_via", "dataset_id": profile.id, "view": "schema"},
        )
        data = {
            "id": profile.id,
            "name": profile.name,
            "format": profile.format,
            "rows": profile.rows,
            "columns": [
                {"name": c.name, "type": c.type, "nulls": c.nulls, "distinct": c.distinct}
                for c in profile.columns
            ],
            "measures": [
                {"name": m.name, "expression": m.expression} for m in profile.model.measures
            ],
        }
        return ToolOutput(content=describe_for_model(profile), artifacts=[artifact], data=data)


class QueryInput(ToolInput):
    dataset_id: str
    dimensions: list[Dimension] = Field(
        default_factory=list, max_length=8, description="Champs de regroupement."
    )
    measures: list[Measure] = Field(
        default_factory=list,
        max_length=12,
        description="Agrégats. Ex. {field: chiffre_affaires, agg: sum} ; {agg: count} = lignes.",
    )
    filters: list[Filter] = Field(default_factory=list)
    sort: list[Sort] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=5000)


class QueryTool(_DataViaTool[QueryInput]):
    name = "data_via_query"
    description = (
        "Exécute une requête d'agrégation sur un jeu Data Via (regrouper, agréger, filtrer, "
        "trier), sans SQL. Clés des colonnes du résultat : `champ`, `champ|month`, `sum(champ)`. "
        "Le résultat complet s'affiche dans le panneau Artefacts ; tu reçois au plus "
        f"{MAX_ROWS_FOR_MODEL} lignes. Le schéma doit avoir été consulté avant."
    )
    input_model = QueryInput
    output_format = "atelier-table/1"

    async def run(self, params: QueryInput, ctx: ToolContext) -> ToolOutput:
        profile = _require_described(ctx, params.dataset_id)
        if profile is None:
            return ToolOutput(content=_NOT_DESCRIBED.format(id=params.dataset_id), is_error=True)
        try:
            request = QueryRequest.model_validate(params.model_dump())
        except ValidationError as exc:
            return ToolOutput(content=f"Requête invalide : {exc.errors()[0]['msg']}", is_error=True)
        errors = validate_query(request, profile)
        if errors:
            return ToolOutput(content="Requête refusée :\n- " + "\n- ".join(errors), is_error=True)

        result = await self.client.query(request)
        headers = [c.key for c in result.columns]
        shown = result.rows[:MAX_ROWS_FOR_MODEL]
        summary = f"{len(result.rows)} ligne(s)"
        if result.truncated:
            summary += f" (tronqué à la limite de {request.limit})"
        if len(result.rows) > len(shown):
            summary += f" ; {len(shown)} premières affichées ci-dessous"
        artifact = Artifact(
            kind="data_preview",
            title=f"Requête — {profile.name}",
            content=json.dumps(
                {"columns": [c.model_dump() for c in result.columns], "rows": result.rows},
                ensure_ascii=False,
                default=str,
            ),
            language="json",
            metadata={
                "source": "data_via",
                "dataset_id": profile.id,
                "view": "query",
                "query": request.model_dump(mode="json", exclude_defaults=True),
                "truncated": result.truncated,
            },
        )
        content = f"{summary}.\n{markdown_table(headers, [list(r) for r in shown])}"
        data = atelier_table(
            "query",
            f"Requête — {profile.name}",
            [(c.key, c.key, c.type) for c in result.columns],
            result.rows,
            total=None if result.truncated else len(result.rows),
            truncated=result.truncated,
        )
        return ToolOutput(content=content, artifacts=[artifact], data=data)


class CheckExpressionInput(ToolInput):
    dataset_id: str
    kind: Literal["measure", "column"] = Field(
        default="measure",
        description="measure (agrégats : SUM, DIVIDE…) ou column (calcul ligne à ligne).",
    )
    name: str = Field(default="", max_length=80)
    expression: str = Field(
        min_length=1,
        max_length=2000,
        description="Ex. DIVIDE(SUM(marge), SUM(chiffre_affaires)) ; noms avec espaces entre [ ].",
    )


class CheckExpressionTool(_DataViaTool[CheckExpressionInput]):
    name = "data_via_check_expression"
    description = (
        "Vérifie (sans rien enregistrer) une mesure ou une colonne calculée dans le langage "
        "d'expressions de Data Via (proche du DAX : SUM, AVG, DIVIDE, COALESCE, IF/SI, YEAR…). "
        "Renvoie l'erreur localisée ou le type et un aperçu des valeurs."
    )
    input_model = CheckExpressionInput

    async def run(self, params: CheckExpressionInput, ctx: ToolContext) -> ToolOutput:
        if _require_described(ctx, params.dataset_id) is None:
            return ToolOutput(content=_NOT_DESCRIBED.format(id=params.dataset_id), is_error=True)
        check = ExpressionCheck.model_validate(
            {"kind": params.kind, "name": params.name, "expression": params.expression}
        )
        result = await self.client.check_expression(params.dataset_id, check)
        if not result.ok:
            where = f" (caractère {result.position})" if result.position is not None else ""
            return ToolOutput(content=f"Expression invalide{where} : {result.error}", is_error=True)
        preview = ", ".join(_fmt(v) for v in result.preview)
        return ToolOutput(content=f"Expression valide, type {result.type}. Aperçu : {preview}")


def data_via_tools(client: DataViaClient) -> list[BaseTool[Any]]:
    """Outils Data Via à déclarer dans `default_tools()` d'un agent."""
    return [
        ListDatasetsTool(client),
        DescribeDatasetTool(client),
        QueryTool(client),
        CheckExpressionTool(client),
    ]
