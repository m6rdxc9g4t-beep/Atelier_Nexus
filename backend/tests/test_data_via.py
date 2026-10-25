import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.data_via import get_data_via_client
from app.schemas.data_via import Dimension, Measure, QueryRequest, ShowAs
from app.tools import ToolContext
from app.tools.data_via import (
    DataViaClient,
    DataViaNotFoundError,
    DataViaRequestError,
    DataViaUnavailableError,
    data_via_tools,
    validate_query,
)
from main import app
from tests.fake_data_via import DATASET_ID, PROFILE, FakeDataVia


@pytest.fixture
def viz() -> FakeDataVia:
    return FakeDataVia()


@pytest.fixture
def client(viz: FakeDataVia) -> DataViaClient:
    return DataViaClient("http://viz.test/api", transport=viz.transport)


def tools(client: DataViaClient) -> dict[str, Any]:
    return {t.name: t for t in data_via_tools(client)}


# ─── Client ───────────────────────────────────────────────────────


async def test_profile_is_parsed_and_unknown_fields_ignored(client: DataViaClient) -> None:
    profile = await client.get_dataset(DATASET_ID)
    assert profile.column("chiffre_affaires") is not None
    assert profile.measure_names == ["marge"]


async def test_query_sends_validated_body(client: DataViaClient, viz: FakeDataVia) -> None:
    req = QueryRequest(
        dataset_id=DATASET_ID,
        dimensions=[Dimension(field="region")],
        measures=[Measure(field="chiffre_affaires", agg="sum")],
    )
    result = await client.query(req)
    sent = json.loads(viz.requests[-1].content)
    assert sent["dimensions"] == [{"field": "region", "bin": None}]
    assert result.columns[1].key == "sum(chiffre_affaires)"


async def test_not_found_maps_to_error(client: DataViaClient) -> None:
    with pytest.raises(DataViaNotFoundError):
        await client.get_dataset("inconnu")


async def test_unreachable_maps_to_unavailable(client: DataViaClient, viz: FakeDataVia) -> None:
    viz.down = True
    with pytest.raises(DataViaUnavailableError, match="Atelier Viz est-il lancé"):
        await client.list_datasets()


@pytest.mark.parametrize("bad_id", ["../settings", "a/b", "", "x?y=1"])
async def test_dataset_id_cannot_escape_path(client: DataViaClient, bad_id: str) -> None:
    with pytest.raises(DataViaRequestError):
        await client.get_dataset(bad_id)


async def test_status_never_raises(client: DataViaClient, viz: FakeDataVia) -> None:
    ok = await client.status()
    assert ok.available and ok.datasets == 1 and ok.version == "0.6.0"
    viz.down = True
    ko = await client.status()
    assert not ko.available and ko.error


# ─── Validation locale des requêtes ───────────────────────────────


async def test_validate_query_reports_unknown_fields_with_suggestion(
    client: DataViaClient,
) -> None:
    profile = await client.get_dataset(DATASET_ID)
    req = QueryRequest(
        dataset_id=DATASET_ID,
        dimensions=[Dimension(field="regoin"), Dimension(field="region", bin="month")],
        measures=[Measure(field="region", agg="sum"), Measure(field="margee", agg="calc")],
    )
    errors = validate_query(req, profile)
    assert any("Vouliez-vous dire : region" in e for e in errors)
    assert any("n'est pas une date" in e for e in errors)
    assert any("exige une colonne numérique" in e for e in errors)
    assert any("Mesure calculée inconnue" in e and "marge" in e for e in errors)


# ─── Outils d'agent ───────────────────────────────────────────────


async def test_list_datasets_tool(client: DataViaClient) -> None:
    out = await tools(client)["data_via_list_datasets"].invoke({}, ToolContext())
    assert not out.is_error and DATASET_ID in out.content


async def test_list_datasets_accepts_both_origin_shapes() -> None:
    """Viz renvoie deux formes d'origine : connexion, ou table publiée par un nœud de workflow
    (`kind = "atelier-table"`, sans connexion). Une seule forme reconnue faisait échouer
    toute la liste dès qu'un workflow ou une extension avait publié une table."""
    from tests.fake_data_via import SUMMARY

    published = {
        **SUMMARY,
        "id": "ds_publie",
        "name": "tableau",
        "origin": {
            "kind": "atelier-table",
            "key": "convert:41e64052a1fc",
            "table_name": "tableau",
            "refreshed_at": "2026-10-23T09:29:31.803572Z",
        },
    }
    connected = {
        **SUMMARY,
        "id": "ds_sql",
        "origin": {
            "kind": "sql",
            "connection_id": "c1",
            "connection_name": "Entrepôt",
            "refreshed_at": "2026-10-23T08:00:00Z",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[SUMMARY, published, connected])

    viz = DataViaClient("http://viz.test/api", transport=httpx.MockTransport(handler))
    out = await tools(viz)["data_via_list_datasets"].invoke({}, ToolContext())
    assert not out.is_error, out.content
    assert "table publiée (convert:41e64052a1fc)" in out.content and "Entrepôt" in out.content
    await viz.aclose()


async def test_query_requires_schema_exploration_first(client: DataViaClient) -> None:
    ctx = ToolContext()
    t = tools(client)
    query = {"dataset_id": DATASET_ID, "measures": [{"agg": "count"}]}
    refused = await t["data_via_query"].invoke(query, ctx)
    assert refused.is_error and "data_via_describe_dataset" in refused.content

    described = await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    assert "`chiffre_affaires` (number)" in described.content
    assert "`marge` = SUM(chiffre_affaires) - SUM(cout)" in described.content
    assert described.artifacts[0].kind == "data_preview"

    accepted = await t["data_via_query"].invoke(query, ctx)
    assert not accepted.is_error


async def test_query_tool_truncates_for_model_but_not_artifact(client: DataViaClient) -> None:
    ctx = ToolContext()
    t = tools(client)
    await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    out = await t["data_via_query"].invoke(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "region"}],
            "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
            "sort": [{"key": "sum(chiffre_affaires)", "desc": True}],
        },
        ctx,
    )
    assert not out.is_error
    assert "60 ligne(s)" in out.content and "50 premières" in out.content
    assert out.content.count("\n| Région") == 50
    artifact = json.loads(out.artifacts[0].content)
    assert len(artifact["rows"]) == 60
    assert out.artifacts[0].metadata["query"]["sort"][0]["desc"] is True


async def test_query_tool_rejects_unknown_field_locally(
    client: DataViaClient, viz: FakeDataVia
) -> None:
    ctx = ToolContext()
    t = tools(client)
    await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    calls = len(viz.requests)
    out = await t["data_via_query"].invoke(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "pays"}],
            "measures": [{"agg": "count"}],
        },
        ctx,
    )
    assert out.is_error and "Dimension inconnue « pays »" in out.content
    assert len(viz.requests) == calls  # rien n'est parti vers Data Via


async def test_check_expression_tool(client: DataViaClient) -> None:
    ctx = ToolContext()
    t = tools(client)
    await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    ok = await t["data_via_check_expression"].invoke(
        {"dataset_id": DATASET_ID, "expression": "SUM(chiffre_affaires)"}, ctx
    )
    assert not ok.is_error and "type number" in ok.content
    ko = await t["data_via_check_expression"].invoke(
        {"dataset_id": DATASET_ID, "expression": "FOO(x)"}, ctx
    )
    assert ko.is_error and "caractère 0" in ko.content


async def test_tool_reports_viz_down_without_crashing(
    client: DataViaClient, viz: FakeDataVia
) -> None:
    viz.down = True
    out = await tools(client)["data_via_list_datasets"].invoke({}, ToolContext())
    assert out.is_error and "injoignable" in out.content


def test_tool_schemas_are_portable(client: DataViaClient) -> None:
    for tool in data_via_tools(client):
        assert "$ref" not in json.dumps(tool.spec().input_schema)


# ─── Calculs rapides (`show`), lignes brutes, relations ───────────


def test_show_keys_mirror_viz() -> None:
    """Clés des colonnes comme Viz (`ShowAs.suffix`) : elles servent au tri et à l'affichage."""
    ytd = Measure(field="ca", agg="sum", show=ShowAs(kind="ytd", date="date"))
    moving = Measure(field="ca", show=ShowAs(kind="moving_avg", date="date", window=6))
    share = Measure(agg="count", show=ShowAs(kind="pct_total"))  # sans date : part du total
    assert [ytd.key, moving.key, share.key] == [
        "sum(ca)@ytd",
        "sum(ca)@moving_avg6",
        "count(*)@pct_total",
    ]
    with pytest.raises(ValidationError, match="demande une colonne date"):
        ShowAs(kind="yoy_pct")


async def test_validate_query_checks_show_dates_and_duplicates(client: DataViaClient) -> None:
    profile = await client.get_dataset(DATASET_ID)
    ca = {"field": "chiffre_affaires", "agg": "sum"}
    req = QueryRequest.model_validate(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "region"}],
            "measures": [
                ca,
                ca,
                {**ca, "show": {"kind": "yoy_pct", "date": "dat"}},
                {**ca, "show": {"kind": "ytd", "date": "region"}},
            ],
        }
    )
    errors = validate_query(req, profile)
    assert any("Colonne date inconnue « dat »" in e and "date" in e for e in errors)
    assert any("« region » n'est pas une date" in e for e in errors)
    assert any("deux fois : sum(chiffre_affaires)" in e for e in errors)
    ok = QueryRequest.model_validate(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "region"}],
            "measures": [{**ca, "show": {"kind": "pct_total"}}],
            "sort": [{"key": "sum(chiffre_affaires)@pct_total", "desc": True}],
        }
    )
    assert validate_query(ok, profile) == []


async def test_query_tool_sends_show_and_flags_percent_points(
    client: DataViaClient, viz: FakeDataVia
) -> None:
    ctx = ToolContext()
    t = tools(client)
    await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    out = await t["data_via_query"].invoke(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "region"}],
            "measures": [
                {"field": "chiffre_affaires", "agg": "sum", "show": {"kind": "pct_total"}}
            ],
        },
        ctx,
    )
    assert not out.is_error, out.content
    sent = json.loads(viz.requests[-1].content)
    assert sent["measures"][0]["show"] == {"kind": "pct_total", "date": None, "window": 3}
    assert "points de pourcentage (12.5 = 12,5 %) : sum(chiffre_affaires)@pct_total" in out.content
    assert "show" in t["data_via_query"].description  # le modèle sait que Viz fait ces calculs


def viz_with(routes: dict[tuple[str, str], Any]) -> tuple[DataViaClient, list[httpx.Request]]:
    """Faux Viz habituel, avec quelques routes remplacées : (méthode, chemin) → JSON."""
    base = FakeDataVia()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = (request.method, request.url.path.removeprefix("/api"))
        if key in routes:
            return httpx.Response(200, json=routes[key])
        return base.handler(request)

    return DataViaClient("http://viz.test/api", transport=httpx.MockTransport(handler)), seen


async def test_describe_shows_the_star_schema_relations() -> None:
    profile = {
        **PROFILE,
        "columns": [
            *PROFILE["columns"],
            {"name": "regions.population", "type": "number", "nulls": 0, "distinct": 5,
             "top_values": [], "related": "regions"},
        ],
        "model": {
            **PROFILE["model"],
            "relations": [{"name": "regions", "dataset_id": "a1b2c3d4e5f6",
                           "from_column": "region", "to_column": "nom", "columns": ["population"]}],
        },
    }  # fmt: skip
    viz, _ = viz_with({("GET", f"/datasets/{DATASET_ID}"): profile})
    out = await tools(viz)["data_via_describe_dataset"].invoke(
        {"dataset_id": DATASET_ID}, ToolContext()
    )
    assert (
        "`regions.population` (number)" in out.content
        and "[liée : relation regions]" in out.content
    )
    assert "- `regions` : region → jeu a1b2c3d4e5f6.nom" in out.content
    assert out.data["relations"] == [
        {
            "name": "regions",
            "dataset_id": "a1b2c3d4e5f6",
            "from_column": "region",
            "to_column": "nom",
        }
    ]
    await viz.aclose()


async def test_rows_tool_pages_raw_lines_after_the_schema(
    client: DataViaClient, viz: FakeDataVia
) -> None:
    ctx = ToolContext()
    t = tools(client)
    refused = await t["data_via_rows"].invoke({"dataset_id": DATASET_ID}, ctx)
    assert refused.is_error and "data_via_describe_dataset" in refused.content
    await t["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    unknown = await t["data_via_rows"].invoke(
        {"dataset_id": DATASET_ID, "columns": ["regoin"]}, ctx
    )
    assert unknown.is_error and "Vouliez-vous dire : region" in unknown.content
    too_many = await t["data_via_rows"].invoke({"dataset_id": DATASET_ID, "limit": 500}, ctx)
    assert too_many.is_error  # au plus 50 lignes par appel pour le modèle

    out = await t["data_via_rows"].invoke(
        {"dataset_id": DATASET_ID, "columns": ["region"], "limit": 10}, ctx
    )
    assert not out.is_error and "Lignes 1 à 1 sur 573" in out.content
    assert "| Bretagne |" in out.content and "offset=1" in out.content
    assert viz.requests[-1].url.params["limit"] == "10"
    assert out.data["rows"] == [{"region": "Bretagne"}] and out.data["total"] == 573


async def test_check_relation_reports_matches_orphans_and_duplicates() -> None:
    check = {"ok": True, "rows": 573, "matched": 560, "duplicates": 1,
             "unmatched_sample": ["Corse", "Guyane"]}  # fmt: skip
    viz, seen = viz_with({("POST", f"/datasets/{DATASET_ID}/relations/check"): check})
    tool = tools(viz)["data_via_check_relation"]
    params = {"dataset_id": DATASET_ID, "from_column": "region",
              "related_dataset_id": "a1b2c3d4e5f6", "to_column": "nom"}  # fmt: skip
    out = await tool.invoke(params, ToolContext())
    assert not out.is_error and not tool.requires_approval  # lecture : rien n'est enregistré
    assert json.loads(seen[-1].content) == {
        "name": "relation",
        "dataset_id": "a1b2c3d4e5f6",
        "from_column": "region",
        "to_column": "nom",
    }
    assert "560 ligne(s) sur 573 trouvent leur clé (97.7 %)" in out.content
    assert (
        "13 ligne(s) sans correspondance (clé vide ou absente du jeu de dimension), ex. "
        "« Corse », « Guyane »" in out.content
    )
    assert "1 clé(s) en double" in out.content and "À corriger en amont" in out.content
    assert out.data == {"ok": False, "rows": 573, "matched": 560, "unmatched": 13,
                        "duplicates": 1, "sample": ["Corse", "Guyane"]}  # fmt: skip

    # Schéma déjà lu : une colonne inconnue est refusée sur place, avec suggestion
    ctx = ToolContext()
    await tools(viz)["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    calls = len(seen)
    bad = await tool.invoke({**params, "from_column": "regoin"}, ctx)
    assert bad.is_error and "Vouliez-vous dire : region" in bad.content and len(seen) == calls
    await viz.aclose()


async def test_check_relation_relays_a_refusal_from_viz() -> None:
    viz, seen = viz_with(
        {("POST", f"/datasets/{DATASET_ID}/relations/check"): {"ok": False, "error": "Le jeu lié n'existe pas."}}
    )  # fmt: skip
    params = {"dataset_id": DATASET_ID, "from_column": "region",
              "related_dataset_id": "0123456789ab", "to_column": "nom"}  # fmt: skip
    out = await tools(viz)["data_via_check_relation"].invoke(params, ToolContext())
    assert out.is_error and "Le jeu lié n'existe pas" in out.content
    # Identifiant mal formé (Viz : 12 caractères hexadécimaux) : refusé en clair, sans appel
    calls = len(seen)
    bad = await tools(viz)["data_via_check_relation"].invoke(
        {**params, "related_dataset_id": "regions"}, ToolContext()
    )
    assert bad.is_error and "12 caractères hexadécimaux" in bad.content and len(seen) == calls
    await viz.aclose()


# ─── Endpoints /api/data-via ──────────────────────────────────────


@pytest.fixture
def api(client: DataViaClient) -> Iterator[TestClient]:
    async def override() -> AsyncIterator[DataViaClient]:
        yield client

    app.dependency_overrides[get_data_via_client] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_list_and_get(api: TestClient) -> None:
    assert api.get("/api/data-via/datasets").json()[0]["id"] == DATASET_ID
    profile = api.get(f"/api/data-via/datasets/{DATASET_ID}").json()
    assert profile["model"]["measures"][0]["name"] == "marge"
    rows = api.get(f"/api/data-via/datasets/{DATASET_ID}/rows?limit=5").json()
    assert rows["limit"] == 5


def test_api_query_and_errors(api: TestClient) -> None:
    body = {"dataset_id": DATASET_ID, "dimensions": [{"field": "region"}]}
    assert api.post("/api/data-via/query", json=body).status_code == 200

    bad = {"dataset_id": DATASET_ID, "dimensions": [{"field": "boom"}]}
    response = api.post("/api/data-via/query", json=bad)
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Champ inconnu : boom"

    missing = api.get("/api/data-via/datasets/inconnu")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "data_via_not_found"

    empty = api.post("/api/data-via/query", json={"dataset_id": DATASET_ID})
    assert empty.status_code == 422  # validé côté Nexus avant tout appel


def test_api_viz_down_is_503(api: TestClient, viz: FakeDataVia) -> None:
    viz.down = True
    response = api.get("/api/data-via/datasets")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_via_unavailable"


def test_suite_health_alias() -> None:
    assert TestClient(app).get("/api/health").json()["status"] == "ok"


def test_markdown_table_escapes_pipes_in_keys() -> None:
    from app.tools.data_via import markdown_table

    table = markdown_table(["date|month", "sum(ca)"], [["2026-01-01", 1.5]])
    header = table.splitlines()[0]
    assert header == "| date\\|month | sum(ca) |"


def test_numbers_keep_full_precision_for_the_model() -> None:
    from app.tools.data_via import markdown_table

    table = markdown_table(["ca"], [[1940427.5600000003], [0.000012345], [-2.5], [3.0]])
    assert "| 1940427.56 |" in table
    assert "| 0.000012345 |" in table  # petites valeurs : aucun chiffre significatif perdu
    assert "| -2.5 |" in table and "| 3 |" in table
    assert "e+" not in table
