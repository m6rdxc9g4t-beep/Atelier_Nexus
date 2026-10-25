"""Écriture dans Atelier Tab par son serveur MCP (Étape 8).

Un faux serveur MCP (tests/fake_tab_mcp.py) est lancé pour de vrai, en sous-processus :
on vérifie la poignée de main, les appels, les refus, l'arrêt brutal, le délai et
l'environnement transmis (aucun secret de Nexus).
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.http import AppUnavailableError
from app.tools.tab_mcp import TabMcpClient, tab_write_tools
from app.tools.toolsets import build_tools, get_toolset

FAKE = str(Path(__file__).parent / "fake_tab_mcp.py")


def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "normal", timeout: float = 10
) -> TabMcpClient:
    monkeypatch.setenv("FAKE_MODE", mode)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ne-doit-pas-fuir")
    monkeypatch.setenv("SECRET_NEXUS", "x")
    # FAKE_* doivent passer : on les ajoute à la liste blanche pour ce test uniquement
    monkeypatch.setattr("app.tools.tab_mcp.SAFE_ENV", ("PATH", "HOME", "FAKE_MODE", "FAKE_LOG"))
    return TabMcpClient([sys.executable, FAKE], data_dir=str(tmp_path / "data"), timeout=timeout)


def logged(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


async def test_handshake_calls_and_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp = client(tmp_path, monkeypatch)
    try:
        tools = by_name(tab_write_tools(mcp))
        out = await tools["tab_set_cells"].invoke(
            {
                "table_id": "tbl_planning_lots",
                "cells": [{"row": 2, "column": "C", "value": "30 000"}],
            },
            ToolContext(),
        )
        assert "C2 = 30 000" in out.content and "D2 = #DIV/0! ⚠ Division par zéro" in out.content
        added = await tools["tab_add_rows"].invoke(
            {
                "table_id": "tbl_planning_lots",
                "rows": [{"Lot / Tâche": "Plomberie", "Coût HT": 12000}],
            },
            ToolContext(),
        )
        assert "ligne 4 (rec_new0) : Lot / Tâche = Plomberie, Coût HT = 12000" in added.content
        assert await mcp.list_tools() == [
            "set_cells",
            "add_rows",
            "delete_rows",
            "add_column",
            "create_table",
        ]
    finally:
        await mcp.aclose()

    log = logged(tmp_path)
    env = log[0]["env"]
    assert env == {"ATELIER_TAB_DATA": str(tmp_path / "data")}  # ni clé Anthropic ni secret Nexus
    methods = [m.get("method") for m in log[1:]]
    assert methods == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
        "tools/list",
    ]
    assert log[3]["params"] == {
        "name": "set_cells",
        "arguments": {
            "table": "tbl_planning_lots",
            "cells": [{"row": 2, "column": "C", "value": "30 000"}],
        },
    }
    assert log[4]["params"]["arguments"]["rows"] == [{"Lot / Tâche": "Plomberie", "Coût HT": 12000}]


async def test_every_write_needs_approval_with_readable_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = by_name(tab_write_tools(client(tmp_path, monkeypatch)))
    assert all(t.requires_approval and not t.sensitive for t in tools.values())

    def summary(name: str, params: dict[str, Any]) -> str:
        tool = tools[name]
        return tool.approval_summary(tool.input_model.model_validate(params))

    assert summary(
        "tab_set_cells",
        {"table_id": "tbl_a", "cells": [{"row": 2, "column": "C", "value": 30000.0}]},
    ) == ("Modifier 1 cellule(s) de la table tbl_a : C2 = 30000")
    assert summary(
        "tab_add_rows",
        {"table_id": "tbl_a", "rows": [{"A": "Plomberie"}, {"A": None, "B": "Peinture"}]},
    ) == ("Ajouter 2 ligne(s) à la table tbl_a : « Plomberie », « Peinture »")
    # Une suppression montre ce qui part (titres), pas seulement des numéros qui peuvent glisser
    assert summary(
        "tab_delete_rows",
        {"table_id": "tbl_a", "rows": [3, "rec_9"], "titles": ["Plomberie", "Peinture"]},
    ) == (
        "Supprimer définitivement 2 ligne(s) de la table tbl_a : « Plomberie » (ligne 3), "
        "« Peinture » (rec_9)"
    )
    assert "« Marge » (formule =D1-C1)" in summary(
        "tab_add_column",
        {"table_id": "tbl_a", "label": "Marge", "type": "formula", "formula": "=D1-C1"},
    )
    assert "colonnes : Lot, Coût" in summary(
        "tab_create_table",
        {
            "project": "Rénovation",
            "name": "Lots 2027",
            "columns": [{"label": "Lot", "type": "text"}, {"label": "Coût", "type": "currency"}],
        },
    )


async def test_invalid_inputs_never_reach_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp = client(tmp_path, monkeypatch)
    tools = by_name(tab_write_tools(mcp))
    bad = [
        (
            "tab_set_cells",
            {"table_id": "../atelier", "cells": [{"row": 1, "column": "A", "value": "x"}]},
        ),
        ("tab_add_column", {"table_id": "tbl_a", "label": "Marge", "type": "formula"}),
        (
            "tab_add_column",
            {"table_id": "tbl_a", "label": "Statut", "type": "text", "preset": "atelier"},
        ),
        ("tab_add_rows", {"table_id": "tbl_a", "rows": []}),
        ("tab_delete_rows", {"table_id": "tbl_a", "rows": [3]}),  # titre attendu manquant
        ("tab_delete_rows", {"table_id": "tbl_a", "rows": [3, 4], "titles": ["Plomberie"]}),
        ("tab_delete_rows", {"table_id": "tbl_a", "rows": [3, "3"], "titles": ["a", "a"]}),
    ]
    for name, params in bad:
        assert (await tools[name].invoke(params, ToolContext())).is_error
    assert mcp._proc is None  # aucun processus lancé


class MemoryTab(TabMcpClient):
    """Serveur MCP de Tab simulé en mémoire : `read_table` par pages (même forme que le vrai :
    `rows[].row / id / cells` par lettre), `delete_rows` consigné."""

    def __init__(self, titles: list[str]) -> None:
        super().__init__(["atelier-mcp-simule"])
        self.rows: list[dict[str, Any]] = [
            {"row": i, "id": f"rec_{i}", "cells": {"A": t, "C": 1000.0 * i}}
            for i, t in enumerate(titles, start=1)
        ]
        self.rows.append(
            {"row": len(titles) + 1, "id": "rec_total", "total_row": True, "cells": {"A": "Total"}}
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool, arguments))
        if tool == "read_table":
            start, size = arguments["offset"], arguments["limit"]
            page = self.rows[start : start + size]
            return {"id": "tbl_a", "name": "Lots", "total_rows": len(self.rows), "rows": page}
        if tool == "delete_rows":
            return {"deleted": len(arguments["rows"]), "remaining_rows": 3}
        raise AssertionError(f"appel inattendu : {tool}")


LOTS = ["Gros œuvre", "Charpente bois et couverture", "Plomberie", "Peinture"]


async def test_delete_rows_checks_titles_then_deletes_by_stable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.tools.tab_mcp.READ_PAGE", 2)  # table lue en plusieurs pages
    tab = MemoryTab(LOTS)
    tool = by_name(tab_write_tools(tab))["tab_delete_rows"]
    out = await tool.invoke(
        {"table_id": "tbl_a", "rows": [3, "rec_2"], "titles": [" plomberie", "Charpente bois…"]},
        ToolContext(),
    )
    assert not out.is_error, out.content
    assert [args["offset"] for name, args in tab.calls if name == "read_table"] == [0, 2, 4]
    # Les numéros vérifiés deviennent des identifiants : rien ne peut glisser entre-temps
    assert tab.calls[-1] == ("delete_rows", {"table": "tbl_a", "rows": ["rec_3", "rec_2"]})
    assert "« Plomberie » (ligne 3)" in out.content
    assert "« Charpente bois et couverture » (ligne 2)" in out.content


async def test_delete_rows_refuses_a_shifted_or_missing_row() -> None:
    tab = MemoryTab(LOTS)
    tool = by_name(tab_write_tools(tab))["tab_delete_rows"]
    shifted = await tool.invoke(
        {"table_id": "tbl_a", "rows": [2, 9], "titles": ["Plomberie", "Carrelage"]},
        ToolContext(),
    )
    assert shifted.is_error and "rien n'a été supprimé" in shifted.content
    assert "ligne 2 ne contient pas « Plomberie » (on y lit « Charpente bois" in shifted.content
    assert "ligne 9 introuvable" in shifted.content
    assert all(name == "read_table" for name, _ in tab.calls)  # aucune suppression envoyée


async def test_delete_rows_handles_empty_rows_and_a_row_cited_twice() -> None:
    tab = MemoryTab(LOTS)
    tab.rows.insert(4, {"row": 5, "id": "rec_vide", "cells": {"A": None, "C": ""}})
    tab.rows[-1]["row"] = 6  # la ligne de total reste la dernière
    tool = by_name(tab_write_tools(tab))["tab_delete_rows"]
    # Une ligne entièrement vide se désigne par un titre vide (carte : « ligne vide »)
    args = {"table_id": "tbl_a", "rows": [5], "titles": [""]}
    assert tool.summarize(args).endswith(": ligne vide (ligne 5)")
    out = await tool.invoke(args, ToolContext())
    assert not out.is_error, out.content
    assert tab.calls[-1] == ("delete_rows", {"table": "tbl_a", "rows": ["rec_vide"]})
    # … mais un titre vide ne supprime jamais une ligne qui contient quelque chose
    full = await tool.invoke({"table_id": "tbl_a", "rows": [3], "titles": [""]}, ToolContext())
    assert full.is_error and "ligne 3 n'est pas vide (on y lit « Plomberie »)" in full.content
    # La même ligne par son numéro et par son id : refusée, rien n'est supprimé
    calls = len(tab.calls)
    twice = await tool.invoke(
        {"table_id": "tbl_a", "rows": [3, "rec_3"], "titles": ["Plomberie", "Plomberie"]},
        ToolContext(),
    )
    assert twice.is_error and "citée deux fois" in twice.content
    assert all(name == "read_table" for name, _ in tab.calls[calls:])


def test_titles_keep_characters_without_ascii_equivalent() -> None:
    """« œ », emoji ou idéogrammes ne disparaissent pas à la comparaison : un titre qui n'a
    qu'eux n'est pas pris pour un titre vide."""
    from app.tools.tab_mcp import _title_match

    assert _title_match("Gros Œuvre", {"A": "gros œuvre"})[0]
    assert _title_match("Électricité", {"A": "electricite "})[0]
    assert not _title_match("✅", {"A": "❌"})[0]
    assert _title_match("✅", {"A": "✅"})[0]


def test_a_truncated_title_needs_a_long_enough_start() -> None:
    """« P… » vaudrait pour toute ligne qui commence par P : un début trop court ne désigne
    rien (comparé tel quel), un début d'au moins 4 caractères désigne sa ligne."""
    from app.tools.tab_mcp import _title_match

    assert not _title_match("P…", {"A": "Plomberie"})[0]
    assert not _title_match("Pl...", {"A": "Plomberie"})[0]
    assert _title_match("Plom…", {"A": "Plomberie et sanitaires"})[0]
    assert _title_match("Plomberie et san...", {"A": "plomberie et sanitaires"})[0]
    assert not _title_match("Peint…", {"A": "Plomberie"})[0]


async def test_refusal_from_tab_is_a_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp = client(tmp_path, monkeypatch)
    try:
        out = await by_name(tab_write_tools(mcp))["tab_set_cells"].invoke(
            {"table_id": "tbl_inconnue", "cells": [{"row": 1, "column": "A", "value": "x"}]},
            ToolContext(),
        )
        assert out.is_error and "introuvable" in out.content
    finally:
        await mcp.aclose()


async def test_crash_and_timeout_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crashing = client(tmp_path, monkeypatch, mode="crash")
    with pytest.raises(AppUnavailableError, match="dossier de données illisible"):
        await crashing.call("set_cells", {"table": "t", "cells": []})
    await crashing.aclose()

    slow = client(tmp_path, monkeypatch, mode="slow", timeout=0.5)
    with pytest.raises(AppUnavailableError, match="n'a pas répondu en 0.5 s"):
        await slow.call("add_rows", {"table": "t", "rows": [{}]})
    await slow.aclose()
    assert slow._proc is None


async def test_noisy_server_and_missing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noisy = client(tmp_path, monkeypatch, mode="noisy")
    try:
        result = await noisy.call("delete_rows", {"table": "t", "rows": [1]})
        assert result == {"deleted": 1, "remaining_rows": 2}
    finally:
        await noisy.aclose()

    missing = TabMcpClient(["/chemin/inexistant/atelier-mcp"])
    with pytest.raises(AppUnavailableError, match="TAB_MCP_COMMAND"):
        await missing.call("set_cells", {})


def test_toolset_is_skipped_without_command() -> None:
    assert get_toolset("tab_write").writes
    env = ToolEnvironment(Settings(tab_mcp_command=None))
    tools, unavailable = build_tools(["tab", "tab_write"], env)
    assert {t.name for t in tools} == {
        "tab_list_tables",
        "tab_read_table",
        "tab_aggregate",
        "tab_check_table",
    }
    assert [u.id for u in unavailable] == ["tab_write"]

    env = ToolEnvironment(Settings(tab_mcp_command=f"{sys.executable} {FAKE}"))
    tools, unavailable = build_tools(["tab_write"], env)
    assert len(tools) == 5 and unavailable == []
