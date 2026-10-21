"""Sortie structurée des outils (`ToolOutput.data`) : tables `atelier-table/1` et fiches.

Le texte envoyé au modèle (`content`) ne change pas : ces tests ne vérifient que `data`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.tools import ToolContext
from app.tools.data_via import DataViaClient, data_via_tools
from app.tools.formatting import atelier_table, is_atelier_table, snake_key
from app.tools.projets import ProjetsClient, projets_read_tools, projets_write_tools
from app.tools.tab import TabSnapshots, tab_tools
from app.tools.tab_projets import tab_projets_tools
from tests.fake_data_via import DATASET_ID, FakeDataVia
from tests.test_connectors import FakeProjets
from tests.test_tab_projets import FakeImport

FIX = Path(__file__).parent / "fixtures"


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


def test_atelier_table_normalises_keys_and_values() -> None:
    from datetime import date

    table = atelier_table(
        "essai",
        "Essai",
        [("Coût HT", "Coût HT", "number"), ("cout ht", "Coût bis", "number"), ("2e", "x", "date")],
        [[1.5, "", date(2026, 10, 21)]],
    )
    assert [c["key"] for c in table["columns"]] == ["cout_ht", "cout_ht_2", "c_2e"]
    assert table["rows"] == [{"cout_ht": 1.5, "cout_ht_2": None, "c_2e": "2026-10-21"}]
    assert table["total"] == 1 and table["truncated"] is False and is_atelier_table(table)
    assert snake_key("sum(chiffre_affaires)") == "sum_chiffre_affaires"
    assert atelier_table("x", "x", [], [], truncated=True)["total"] is None


async def test_data_via_tools_fill_data() -> None:
    viz = FakeDataVia()
    tools = by_name(data_via_tools(DataViaClient("http://viz.test/api", transport=viz.transport)))
    ctx = ToolContext()
    listed = await tools["data_via_list_datasets"].invoke({}, ctx)
    assert listed.data["rows"][0]["id"] == DATASET_ID and is_atelier_table(listed.data)
    described = await tools["data_via_describe_dataset"].invoke({"dataset_id": DATASET_ID}, ctx)
    assert described.data["columns"][1] == {
        "name": "region",
        "type": "string",
        "nulls": 0,
        "distinct": 5,
    }
    assert described.data["measures"][0]["name"] == "marge"
    query = await tools["data_via_query"].invoke(
        {
            "dataset_id": DATASET_ID,
            "dimensions": [{"field": "region"}],
            "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
        },
        ctx,
    )
    assert [c["key"] for c in query.data["columns"]] == ["region", "sum_chiffre_affaires"]
    assert query.data["columns"][1]["label"] == "sum(chiffre_affaires)"
    assert len(query.data["rows"]) == 60 and query.data["total"] == 60
    # Le texte du modèle est inchangé : tableau Markdown tronqué à 50 lignes
    assert "60 ligne(s) ; 50 premières affichées" in query.content


@pytest.fixture
def snapshots(tmp_path: Path) -> TabSnapshots:
    for name in ("tbl_planning_lots", "tbl_materiaux"):
        shutil.copy(FIX / "tab" / f"{name}.json", tmp_path / f"{name}.json")
    return TabSnapshots(str(tmp_path))


async def test_tab_tools_fill_atelier_tables(snapshots: TabSnapshots) -> None:
    tools = by_name(tab_tools(snapshots))
    listed = await tools["tab_list_tables"].invoke({}, ToolContext())
    assert {r["id"] for r in listed.data["rows"]} == {"tbl_planning_lots", "tbl_materiaux"}

    read = await tools["tab_read_table"].invoke({"table_id": "tbl_planning_lots"}, ToolContext())
    table = read.data
    assert table["name"] == "tbl_planning_lots" and table["label"] == "Planning & Lots"
    assert [c["key"] for c in table["columns"]][:4] == ["_ligne", "_id", "task_name", "status"]
    assert {c["key"]: c["type"] for c in table["columns"]}["cost_ttc"] == "number"  # formule
    assert table["rows"][0] == {
        "_ligne": 1,
        "_id": "rec_01",
        "task_name": "Gros œuvre",
        "status": "En cours",
        "cost_ht": 45000,
        "cost_ttc": 54000,
        "owner": "Marie Dubois",
        "due_date": "2026-11-30",
    }
    assert table["total"] == 3 and not table["truncated"]
    page = await tools["tab_read_table"].invoke(
        {"table_id": "tbl_planning_lots", "limit": 1}, ToolContext()
    )
    assert len(page.data["rows"]) == 1 and page.data["truncated"] and page.data["total"] == 3

    agg = await tools["tab_aggregate"].invoke(
        {"table_id": "tbl_planning_lots", "group_by": "Statut", "measures": [{"column": "C"}]},
        ToolContext(),
    )
    assert agg.data["rows"][1] == {"status": "En cours", "lignes": 1, "sum_cost_ht": 45000.0}


async def test_projets_tools_fill_tables_and_records() -> None:
    fake = FakeProjets()
    client = ProjetsClient("http://projets.test/api", transport=httpx.MockTransport(fake))
    tools = by_name(projets_read_tools(client) + projets_write_tools(client))
    ctx = ToolContext()
    projects = await tools["projets_list_projects"].invoke({}, ctx)
    assert projects.data["rows"][0]["name"] == "App E-Commerce v2"
    items = await tools["projets_list_work_items"].invoke({"project_id": 1}, ctx)
    assert items.data["name"] == "work-items" and len(items.data["rows"]) == 17
    assert {"id", "status", "title", "estimated_hours", "due_date"} <= set(items.data["rows"][0])
    detail = await tools["projets_work_item"].invoke({"work_item_id": 12345}, ctx)
    assert detail.data["id"] == 12345 and detail.data["path"]["story"]["id"] == 2
    sheet = await tools["projets_timesheet"].invoke({"project_id": 1}, ctx)
    assert is_atelier_table(sheet.data) and sheet.data["rows"]
    milestones = await tools["projets_milestones"].invoke({"project_id": 1}, ctx)
    assert milestones.data["columns"][3] == {
        "key": "reached",
        "label": "Atteint",
        "type": "boolean",
    }
    created = await tools["projets_create_work_item"].invoke(
        {"story_id": 2, "type": "TASK", "title": "Relire"}, ctx
    )
    assert created.data["id"] == 20001 and created.data["title"] == "Relire"
    updated = await tools["projets_update_work_item"].invoke(
        {"work_item_id": 12345, "status": "IN_REVIEW"}, ctx
    )
    assert updated.data["status"] == "IN_REVIEW"


async def test_tab_projets_bridge_returns_a_summary(snapshots: TabSnapshots) -> None:
    fake = FakeImport()
    projets = ProjetsClient("http://projets.test/api", transport=httpx.MockTransport(fake))
    tools = by_name(tab_projets_tools(projets, snapshots))
    preview = await tools["projets_preview_tab_import"].invoke(
        {"table_id": "tbl_planning_lots"}, ToolContext()
    )
    assert preview.data["created"] == 3 and preview.data["target"]["story"]["exists"] is False
    done = await tools["projets_import_tab_table"].invoke(
        {"table_id": "tbl_planning_lots"}, ToolContext()
    )
    assert done.data["items"][0]["work_item_id"] == 100 and done.data["replayed"] is False
    json.dumps(done.data)  # sérialisable tel quel
