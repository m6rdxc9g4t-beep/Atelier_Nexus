"""Nœuds de la suite (atelier-node/1) : manifestes, exécuteur d'action, événements.

Viz et Projets simulés par httpx.MockTransport ; Tab par un dossier `_atelier/` réel et le faux
serveur MCP (sous-processus). Aucune requête réseau réelle.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.suite.http import NodeActionError, NodeHttpClient, is_loopback
from app.suite.manifest import ManifestError, parse_manifest
from app.suite.nodes import build_http_request, validate_input
from app.tools.environment import ToolEnvironment
from tests.fake_suite import (
    PROJETS_MANIFEST,
    TAB_MANIFEST,
    VIZ_MANIFEST,
    FakeProjetsNode,
    FakeVizNode,
    mcp_command,
    write_tab_manifest,
)

FIX = Path(__file__).parent / "fixtures"


class Suite:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.viz = FakeVizNode()
        self.projets = FakeProjetsNode()
        self.exports = tmp_path / "exports"
        self.exports.mkdir()
        shutil.copy(FIX / "tab" / "tbl_planning_lots.json", self.exports)
        self.manifest_file = write_tab_manifest(self.exports)
        self.log = tmp_path / "mcp.jsonl"
        # Le serveur MCP simulé lit sa propre copie (le test peut retirer celle du dossier)
        mcp_manifest = tmp_path / "mcp_manifest.json"
        mcp_manifest.write_text(self.manifest_file.read_text())
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_MANIFEST", str(mcp_manifest))
        monkeypatch.setattr(
            "app.tools.tab_mcp.SAFE_ENV", ("PATH", "HOME", "FAKE_MODE", "FAKE_LOG", "FAKE_MANIFEST")
        )
        self.mcp = True
        #: APPROVAL_MODE des environnements créés (défaut de l'application : chaque étape)
        self.approval_mode = "every_step"

    def settings(self, **extra: Any) -> Settings:
        values: dict[str, Any] = {
            "_env_file": None,
            "data_via_base_url": "http://127.0.0.1:8000/api",
            "projets_base_url": "http://127.0.0.1:3000/api",
            "tresorerie_base_url": None,
            "cine_base_url": None,
            "savoir_base_url": None,
            "tab_exports_dir": str(self.exports),
            "tab_mcp_command": mcp_command() if self.mcp else None,
            "github_repo": None,
            "approval_mode": self.approval_mode,
        }
        return Settings(**(values | extra))

    def env(self, **extra: Any) -> ToolEnvironment:
        return ToolEnvironment(
            self.settings(**extra),
            transports={
                "data_via": self.viz.transport,
                "projets": httpx.MockTransport(self.projets),
            },
        )

    def mcp_calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        lines = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [m["params"] for m in lines if m.get("method") == "tools/call"]


@pytest.fixture
def suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Suite:
    return Suite(tmp_path, monkeypatch)


# ─── Manifestes ───────────────────────────────────────────────────


def test_manifest_parsing_keeps_valid_actions_and_reports_the_others() -> None:
    manifest, ignored = parse_manifest(VIZ_MANIFEST, "viz")
    assert [a.id for a in manifest.actions] == [
        "datasets.query",
        "datasets.list",
        "datasets.upsert_rows",
        "datasets.delete",
    ]
    assert ignored and ignored[0].startswith("Mauvais id")
    assert manifest.action("datasets.upsert_rows").http.path_params == ["name"]  # type: ignore[union-attr]
    with pytest.raises(ManifestError, match="Contrat inconnu"):
        parse_manifest(VIZ_MANIFEST | {"contract": "autre/2"}, "viz")
    with pytest.raises(ManifestError, match="autre application"):
        parse_manifest(VIZ_MANIFEST, "projets")
    both = dict(PROJETS_MANIFEST)
    both["actions"] = [
        PROJETS_MANIFEST["actions"][0] | {"mcp_tool": "x"},
        PROJETS_MANIFEST["actions"][1] | {"http": {"method": "GET", "path": "/api/../secret"}},
        PROJETS_MANIFEST["actions"][2] | {"input_schema": {"type": "nope"}},
        PROJETS_MANIFEST["actions"][0],
        PROJETS_MANIFEST["actions"][0],
    ]
    parsed, problems = parse_manifest(both, "projets")
    assert [a.id for a in parsed.actions] == ["work_items.list"]
    assert len(problems) == 4 and any("double" in p for p in problems)


async def test_states_of_the_three_nodes(suite: Suite) -> None:
    env = suite.env()
    try:
        states = {s.app: s for s in await env.suite().states()}
    finally:
        await env.aclose()
    assert {a: s.status for a, s in states.items()} == {"viz": "ok", "tab": "ok", "projets": "ok"}
    assert states["tab"].transport == "mcp" and states["viz"].transport == "http"
    assert states["viz"].ignored  # action mal formée signalée
    # Lu une seule fois grâce au cache (60 s)
    env = suite.env()
    try:
        await env.suite().state("viz")
    finally:
        await env.aclose()
    manifests = [r for r in suite.viz.requests if r.url.path == "/api/atelier/manifest"]
    assert len(manifests) == 1
    assert str(manifests[0].url) == "http://127.0.0.1:8000/api/atelier/manifest"


async def test_status_unreachable_no_contract_and_not_configured(suite: Suite) -> None:
    suite.viz.mode = "down"
    suite.projets.mode = "no_contract"
    suite.manifest_file.unlink()
    suite.mcp = False
    env = suite.env()
    try:
        states = {s.app: s for s in await env.suite().states()}
    finally:
        await env.aclose()
    assert states["viz"].status == "unreachable" and "injoignable" in (states["viz"].reason or "")
    assert states["projets"].status == "no_contract"
    assert states["tab"].status == "no_contract" and states["tab"].transport == "files"
    env = ToolEnvironment(
        suite.settings(data_via_base_url=None, projets_base_url=None, tab_exports_dir=None)
    )
    try:
        assert {s.status for s in await env.suite().states()} == {"not_configured"}
    finally:
        await env.aclose()


async def test_non_loopback_addresses_are_refused(suite: Suite) -> None:
    assert is_loopback("http://127.0.0.1:8000/api") and is_loopback("http://[::1]:3000/api")
    assert is_loopback("http://localhost:3000") and not is_loopback("http://192.168.1.4:8000")
    assert not is_loopback("http://host.docker.internal:8000/api")
    env = suite.env(data_via_base_url="http://viz.example.com/api")
    try:
        state = await env.suite().state("viz")
    finally:
        await env.aclose()
    assert state.status == "unreachable" and "bouclage" in (state.reason or "")
    assert not suite.viz.requests
    with pytest.raises(NodeActionError) as exc:
        NodeHttpClient("viz", "Atelier Viz", "http://10.0.0.2/api")
    assert exc.value.code == "FORBIDDEN_HOST"


async def test_tab_manifest_falls_back_to_mcp(suite: Suite) -> None:
    suite.manifest_file.unlink()
    env = suite.env()
    try:
        state = await env.suite().state("tab")
    finally:
        await env.aclose()
    assert state.status == "ok" and state.manifest is not None
    assert [a.id for a in state.manifest.actions] == ["tables.query", "rows.add", "rows.delete"]
    assert suite.mcp_calls()[0]["name"] == "atelier_manifest"


# ─── Exécuteur ────────────────────────────────────────────────────


def test_http_request_building_encodes_path_and_splits_query_and_body() -> None:
    manifest, _ = parse_manifest(VIZ_MANIFEST, "viz")
    upsert = manifest.action("datasets.upsert_rows")
    listing = manifest.action("datasets.list")
    assert upsert is not None and listing is not None
    path, query, body = build_http_request(upsert, {"name": "a b/../c", "table": {}, "note": "x"})
    assert path == "/api/atelier/datasets/a%20b%2F..%2Fc/rows" and query is None
    assert body == {"table": {}, "note": "x"}
    path, query, body = build_http_request(listing, {"limit": 5, "tags": ["a", "b"], "x": None})
    assert query == [("limit", "5"), ("tags", "a"), ("tags", "b")] and body is None
    for bad in ("..", ".", ""):
        with pytest.raises(NodeActionError):
            build_http_request(upsert, {"name": bad, "table": {}})
    with pytest.raises(NodeActionError):
        build_http_request(upsert, {"table": {}})
    assert validate_input(upsert, {"name": "x"}) == [("table", "'table' is a required property")]


async def test_http_action_validates_sends_idempotency_and_replays(suite: Suite) -> None:
    env = suite.env()
    nodes = env.suite()
    table = {"format": "atelier-table/1", "columns": [], "rows": [{"a": 1}]}
    try:
        with pytest.raises(NodeActionError) as invalid:
            await nodes.run_action("viz", "datasets.upsert_rows", {"name": "x"})
        assert invalid.value.code == "INPUT_INVALID" and not [
            r for r in suite.viz.requests if r.method == "POST"
        ]
        first = await nodes.run_action(
            "viz", "datasets.upsert_rows", {"name": "ventes", "table": table}, idempotency_key="k1"
        )
        again = await nodes.run_action(
            "viz", "datasets.upsert_rows", {"name": "ventes", "table": table}, idempotency_key="k1"
        )
        listed = await nodes.run_action("viz", "datasets.list", {"limit": 3, "tags": ["a", "b"]})
    finally:
        await env.aclose()
    assert first.data == {"id": "ds_ventes", "rows": 1} and not first.replayed
    assert again.replayed and "rejouée" in again.content and len(suite.viz.published) == 1
    post = next(r for r in suite.viz.requests if r.method == "POST")
    assert post.headers["idempotency-key"] == "k1"
    assert listed.data["query"] == "limit=3&tags=a&tags=b"


async def test_http_errors_are_relayed_with_their_code(suite: Suite) -> None:
    env = suite.env()
    nodes = env.suite()
    try:
        with pytest.raises(NodeActionError) as missing:
            await nodes.run_action("viz", "datasets.query", {"dataset_id": "inconnu"})
        with pytest.raises(NodeActionError) as unknown:
            await nodes.run_action("viz", "datasets.nope", {})
        suite.viz.mode = "redirect"
        with pytest.raises(NodeActionError) as redirect:
            await nodes.run_action("viz", "datasets.query", {"dataset_id": "ds_ventes"})
    finally:
        await env.aclose()
    assert missing.value.code == "NOT_FOUND" and "Jeu introuvable" in str(missing.value)
    assert unknown.value.code == "UNKNOWN_ACTION"
    assert redirect.value.code == "REDIRECT"
    assert all("ailleurs" not in str(r.url) for r in suite.viz.requests)


async def test_response_size_is_bounded(suite: Suite) -> None:
    suite.viz.mode = "huge"
    env = suite.env()
    nodes = env.suite()
    nodes.http("viz").max_bytes = 100_000
    try:
        with pytest.raises(NodeActionError) as exc:
            await nodes.run_action("viz", "datasets.query", {"dataset_id": "ds_ventes"})
    finally:
        await env.aclose()
    assert exc.value.code == "RESPONSE_TOO_LARGE"


async def test_mcp_action_passes_the_idempotency_field(suite: Suite) -> None:
    env = suite.env()
    nodes = env.suite()
    try:
        table = await nodes.run_action("tab", "tables.query", {"table_id": "tbl_planning_lots"})
        added = await nodes.run_action(
            "tab", "rows.add", {"table": "t", "rows": [{"A": "x"}]}, idempotency_key="nexus:r:s"
        )
        replay = await nodes.run_action(
            "tab", "rows.add", {"table": "t", "rows": [{"A": "x"}]}, idempotency_key="nexus:r:s"
        )
        with pytest.raises(NodeActionError) as refused:
            await nodes.run_action("tab", "tables.query", {"table_id": "tbl_inconnue"})
    finally:
        await env.aclose()
    assert table.data["format"] == "atelier-table/1" and "2 ligne(s)" in table.content
    assert added.data["added"][0]["id"] == "rec_new0" and not added.replayed
    assert replay.replayed
    assert refused.value.code == "NOT_FOUND" and "Table introuvable" in str(refused.value)
    calls = [c for c in suite.mcp_calls() if c["name"] == "add_rows"]
    assert calls[0]["arguments"]["idempotency_key"] == "nexus:r:s"


async def test_tab_actions_need_the_mcp_server(suite: Suite) -> None:
    suite.mcp = False
    env = suite.env()
    try:
        state = await env.suite().state("tab")
        with pytest.raises(NodeActionError) as exc:
            await env.suite().run_action("tab", "tables.query", {"table_id": "x"})
    finally:
        await env.aclose()
    assert state.status == "ok" and state.transport == "files" and not state.executable
    assert exc.value.code == "UNAVAILABLE"


# ─── Événements ───────────────────────────────────────────────────


async def test_events_http_and_tab_file(suite: Suite) -> None:
    lines = [
        {"seq": s, "type": "tab.table.changed", "at": "2026-10-21T21:00:00+02:00",
         "subject": {"kind": "table", "id": "t", "label": "T"}, "data": {"revision": s}}
        for s in (10, 11, 12)
    ]  # fmt: skip
    (suite.exports / "_atelier" / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in lines) + "\n{incomplet"
    )
    env = suite.env()
    nodes = env.suite()
    try:
        viz = await nodes.events("viz", since=40, limit=10)
        tab = await nodes.events("tab", since=10)
        tab_gap = await nodes.events("tab", since=2)
        tab_reset = await nodes.events("tab", since=99)
        latest = await nodes.events("tab", limit=1)
    finally:
        await env.aclose()
    assert [e.seq for e in viz.events] == [41, 42] and viz.next == 42
    assert [e.seq for e in tab.events] == [11, 12] and tab.next == 12 and not tab.gap
    assert tab_gap.gap and [e.seq for e in latest.events] == [12]
    assert tab_reset.gap and tab_reset.events == []  # journal remis à zéro (§7.3)


async def test_tab_events_fall_back_to_mcp(suite: Suite) -> None:
    env = suite.env()
    try:
        page = await env.suite().events("tab", since=7)
    finally:
        await env.aclose()
    assert [e.seq for e in page.events] == [8] and page.next == 8


def test_tab_manifest_double_matches_the_mcp_double() -> None:
    assert TAB_MANIFEST["transport"] == "mcp"
    assert {a["mcp_tool"] for a in TAB_MANIFEST["actions"]} == {
        "query_table",
        "add_rows",
        "delete_rows",
    }
