"""Pont Atelier Tab → Atelier Projets (Étape 10) : aperçu, import idempotent, choix des lignes.

L'instantané est une vraie enveloppe produite par Atelier Tab (fixture partagée) ; l'API
d'import de Projets est simulée par httpx.MockTransport, au format de ses schémas
(`backend/src/schemas/atelier-tab.ts` d'Atelier Projets).
"""

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.projets import ProjetsClient
from app.tools.tab import TabSnapshots
from app.tools.tab_projets import idempotency_key, select_rows, tab_projets_tools
from app.tools.toolsets import build_tools

FIX = Path(__file__).parent / "fixtures"


def item(row: int, title: str, action: str, wid: int | None = None) -> dict[str, Any]:
    return {"recordId": f"rec_0{row}", "rowIndex": row, "workItemId": wid, "action": action,
            "title": title, "status": "OPEN", "startDate": None, "dueDate": "2026-11-30", "reason": None}  # fmt: skip


class FakeImport:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.seen_keys: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        titles = [r["values"]["A"]["computed"] for r in body["project"]["records"]]
        counts = {"projectId": 7, "storyId": 70, "updated": 0, "unchanged": 0, "skipped": 0,
                  "warnings": ["Colonne « Responsable » : 1 nom inconnu"]}  # fmt: skip
        if request.url.path.endswith("/preview"):
            return httpx.Response(200, json=counts | {
                "created": len(titles), "items": [item(i + 1, t, "created") for i, t in enumerate(titles)],
                "target": {"project": {"id": None, "name": body["project"]["name"], "exists": False},
                           "phase": {"title": "Imports Atelier Tab", "exists": False},
                           "epic": {"title": "Espace Architecture", "exists": False},
                           "story": {"title": "Planning & Lots", "exists": False}, "type": "TASK"},
            })  # fmt: skip
        key = request.headers["idempotency-key"]
        replay = key in self.seen_keys
        self.seen_keys.add(key)
        result = counts | {
            "created": len(titles),
            "items": [item(i + 1, t, "created", 100 + i) for i, t in enumerate(titles)],
        }
        return httpx.Response(
            200, json=result, headers={"idempotency-replayed": "true"} if replay else {}
        )


@pytest.fixture
def bridge(tmp_path: Path) -> tuple[dict[str, Any], FakeImport]:
    folder = tmp_path / "exports"
    folder.mkdir()
    shutil.copy(FIX / "tab" / "tbl_planning_lots.json", folder / "tbl_planning_lots.json")
    fake = FakeImport()
    projets = ProjetsClient("http://projets.test/api", transport=httpx.MockTransport(fake))
    projets.import_token = "jeton-test"
    tools = {t.name: t for t in tab_projets_tools(projets, TabSnapshots(str(folder)))}
    return tools, fake


async def test_preview_shows_target_and_items(bridge: tuple[dict[str, Any], FakeImport]) -> None:
    tools, fake = bridge
    tool = tools["projets_preview_tab_import"]
    assert not tool.requires_approval
    out = await tool.invoke({"table_id": "tbl_planning_lots", "type": "FEATURE"}, ToolContext())
    assert not out.is_error
    assert "Projet : Rénovation Urbaine 2026, à créer" in out.content
    assert "story « Planning & Lots » (à créer)" in out.content
    assert (
        "L'import ferait : 3 création(s)" in out.content
        and "| 1 | Gros œuvre | créé |" in out.content
    )
    assert "1 nom inconnu" in out.content
    req = fake.requests[0]
    assert req.url.path == "/api/imports/atelier-tab/preview"
    assert req.url.params["type"] == "FEATURE"
    assert req.headers["x-atelier-schema-version"] == "2.1.0"
    assert req.headers["authorization"] == "Bearer jeton-test"
    assert "idempotency-key" not in req.headers
    # L'enveloppe est transmise telle que Tab l'a publiée (extensions comprises)
    sent = json.loads(req.content)
    assert sent == json.loads((FIX / "tab" / "tbl_planning_lots.json").read_text())


async def test_import_needs_approval_and_replays_without_duplicates(
    bridge: tuple[dict[str, Any], FakeImport],
) -> None:
    tools, fake = bridge
    tool = tools["projets_import_tab_table"]
    assert tool.requires_approval
    params = {"table_id": "tbl_planning_lots", "project_id": 7, "rows": [1, "rec_03"]}
    assert tool.approval_summary(tool.input_model.model_validate(params)) == (
        "Importer 2 ligne(s) de la table tbl_planning_lots dans Atelier Projets (le projet #7, éléments TASK)"
    )
    first = await tool.invoke(params, ToolContext())
    assert (
        "importée (projet #7, story #70)" in first.content
        and "| 2 | Isolation thermique | créé | #101 |" in first.content
    )
    again = await tool.invoke(params, ToolContext())
    assert "déjà importée telle quelle" in again.content
    keys = [r.headers["idempotency-key"] for r in fake.requests]
    assert keys[0] == keys[1] and keys[0].startswith("nexus-")
    assert fake.requests[0].url.params["projectId"] == "7"


def test_select_rows_recomputes_counts_and_totals() -> None:
    envelope = json.loads((FIX / "tab" / "tbl_planning_lots.json").read_text())
    picked = select_rows(envelope, [1, "rec_03"])
    project = picked["project"]
    assert [r["record_id"] for r in project["records"]] == ["rec_01", "rec_03"]
    assert project["summary_metrics"] == {
        "total_rows": 2,
        "computed_totals": {"C": 60000.0, "D": 72000.0},
    }
    assert envelope["project"]["summary_metrics"]["total_rows"] == 3  # original intact
    assert select_rows(envelope, None) is envelope
    with pytest.raises(Exception, match="introuvable.*rec_99"):
        select_rows(envelope, ["rec_99"])


def test_idempotency_key_depends_on_content_and_options() -> None:
    envelope = json.loads((FIX / "tab" / "tbl_planning_lots.json").read_text())
    base = idempotency_key(envelope, None, None)
    assert base == idempotency_key(json.loads(json.dumps(envelope)), None, None)
    assert base != idempotency_key(envelope, 1, None) != idempotency_key(envelope, None, "BUG")
    changed = json.loads(json.dumps(envelope))
    changed["project"]["records"][0]["values"]["B"]["computed"] = "Terminé"
    assert base != idempotency_key(changed, None, None)


async def test_unknown_table_sends_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    data = json.loads((FIX / "tab" / "tbl_planning_lots.json").read_text())
    (folder / "tbl_planning_lots.json").write_text(json.dumps(data))
    fake = FakeImport()
    projets = ProjetsClient("http://p.test/api", transport=httpx.MockTransport(fake))
    tools = {t.name: t for t in tab_projets_tools(projets, TabSnapshots(str(folder)))}
    out = await tools["projets_preview_tab_import"].invoke(
        {"table_id": "tbl_inconnue"}, ToolContext()
    )
    assert out.is_error and "introuvable" in out.content and fake.requests == []


def test_toolset_needs_tab_and_projets() -> None:
    tools, unavailable = build_tools(
        ["tab_projets"], ToolEnvironment(Settings(tab_exports_dir=None))
    )
    assert tools == [] and [u.id for u in unavailable] == ["tab_projets"]
    tools, _ = build_tools(
        ["tab_projets"], ToolEnvironment(Settings(projets_import_token="s3cret"))
    )
    assert {t.name for t in tools} == {"projets_preview_tab_import", "projets_import_tab_table"}
