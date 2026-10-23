import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.data_via import get_data_via_client
from app.schemas.data_via import Dimension, Measure, QueryRequest
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
from tests.fake_data_via import DATASET_ID, FakeDataVia


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
    import httpx

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
