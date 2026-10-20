"""Essai réel des connecteurs (applications lancées sur la machine).

    cd backend && python -m scripts.smoke_apps [--write] [--apps projets,tresorerie,tab,cine,savoir]

Lance chaque outil de lecture ; avec --write, joue aussi les écritures : Atelier Projets
(création d'un élément, saisie de temps, journal, statut), Atelier Savoir (cours, chapitre,
cartes, révisions) et Atelier Ciné (nouvelle analyse des dossiers). À N'UTILISER QUE SUR
DES DONNÉES DE TEST.
"""

import asyncio
import sys
from typing import Any

from app.core.config import get_settings
from app.tools import ToolContext
from app.tools.base import BaseTool
from app.tools.cine import cine_read_tools, cine_write_tools
from app.tools.environment import ToolEnvironment
from app.tools.projets import projets_read_tools, projets_write_tools
from app.tools.savoir import savoir_read_tools, savoir_write_tools
from app.tools.tab import tab_tools
from app.tools.tab_mcp import tab_write_tools
from app.tools.tresorerie import tresorerie_tools

ALL_APPS = ("projets", "tresorerie", "tab", "cine", "savoir")

failures: list[str] = []


async def call(tool: BaseTool[Any], args: dict[str, Any], ctx: ToolContext) -> str:
    out = await tool.invoke(args, ctx)
    status = "ERREUR" if out.is_error else "ok"
    if out.is_error:
        failures.append(f"{tool.name}: {out.content}")
    first = out.content.splitlines()[0] if out.content else ""
    print(f"[{status}] {tool.name} {args} → {first[:110]}")
    return out.content


async def projets(env: ToolEnvironment, ctx: ToolContext, write: bool) -> None:
    if True:  # noqa: SIM108 (bloc conservé pour la lisibilité du diff)
        p = {t.name: t for t in projets_read_tools(env.projets())}
        await call(p["projets_list_projects"], {}, ctx)
        await call(p["projets_dashboard"], {"project_id": 1}, ctx)
        structure = await call(p["projets_structure"], {"project_id": 1}, ctx)
        await call(
            p["projets_list_work_items"],
            {"project_id": 1, "status": ["IN_PROGRESS", "BLOCKED"]},
            ctx,
        )
        await call(p["projets_list_work_items"], {"project_id": 1, "query": "git"}, ctx)
        await call(p["projets_work_item"], {"work_item_id": 12345}, ctx)
        await call(p["projets_timesheet"], {"project_id": 1}, ctx)
        await call(p["projets_milestones"], {"project_id": 1}, ctx)
        await call(p["projets_work_item"], {"work_item_id": 999999}, ctx)  # 404 attendu
        failures.pop()  # l'erreur précédente est attendue

        if write:
            w = {t.name: t for t in projets_write_tools(env.projets())}
            story = int(structure.split("story_id ")[1].split(")")[0])
            created = await call(
                w["projets_create_work_item"],
                {"story_id": story, "type": "TASK", "title": "Test Nexus : saisie automatique",
                 "estimated_hours": 3, "description": "Créé par l'essai des connecteurs."},
                ctx,
            )  # fmt: skip
            item = int(created.split("#")[1].split(" ")[0])
            await call(
                w["projets_add_time_entry"],
                {"work_item_id": item, "hours": 1.5, "comment": "essai"},
                ctx,
            )
            await call(
                w["projets_add_log_entry"],
                {"work_item_id": item, "text": "Essai du journal.", "hours": 1.5},
                ctx,
            )
            await call(
                w["projets_update_work_item"],
                {"work_item_id": item, "status": "CLOSED", "progress": 40},
                ctx,
            )
            await call(p["projets_work_item"], {"work_item_id": item}, ctx)


async def tresorerie(env: ToolEnvironment, ctx: ToolContext, write: bool) -> None:
    if True:
        t = {x.name: x for x in tresorerie_tools(env.tresorerie())}
        await call(t["tresorerie_dashboard"], {}, ctx)
        await call(t["tresorerie_accounts"], {}, ctx)
        await call(t["tresorerie_categories"], {}, ctx)
        await call(t["tresorerie_transactions"], {"type": "expense", "limit": 20}, ctx)
        await call(t["tresorerie_transactions"], {"uncategorized": True}, ctx)
        await call(t["tresorerie_budgets"], {}, ctx)
        await call(t["tresorerie_goals"], {}, ctx)
        await call(t["tresorerie_holdings"], {}, ctx)


async def tab(env: ToolEnvironment, ctx: ToolContext, write: bool) -> None:
    t = {x.name: x for x in tab_tools(env.tab())}
    listing = await call(t["tab_list_tables"], {}, ctx)
    ids = [line.split("|")[1].strip() for line in listing.splitlines() if line.startswith("| tbl")]
    for table_id in ids[:3]:
        await call(t["tab_read_table"], {"table_id": table_id, "limit": 5}, ctx)
        await call(t["tab_check_table"], {"table_id": table_id}, ctx)
    if ids:
        await call(
            t["tab_aggregate"],
            {"table_id": ids[0], "measures": [{"column": "A", "agg": "count"}]},
            ctx,
        )
    if write and "tbl_planning_lots" in ids and env.settings.tab_mcp_command:
        # Écritures réelles par le serveur MCP de Tab, puis contrôle dans l'instantané
        w = {x.name: x for x in tab_write_tools(env.tab_mcp())}
        added = await call(
            w["tab_add_rows"],
            {"table_id": "tbl_planning_lots",
             "rows": [{"Lot / Tâche": "Essai Nexus", "Statut": "À faire", "Coût HT": "12 000",
                       "Échéance": "15/01/2027"}]},
            ctx,
        )  # fmt: skip
        row = int(added.split("ligne ")[1].split(" ")[0])
        await call(
            w["tab_set_cells"],
            {"table_id": "tbl_planning_lots",
             "cells": [{"row": row, "column": "Coût HT", "value": "13 500"}]},
            ctx,
        )  # fmt: skip
        check = await call(
            t["tab_aggregate"],
            {"table_id": "tbl_planning_lots", "measures": [{"column": "Coût HT"}],
             "filters": {"Lot / Tâche": "Essai Nexus"}},
            ctx,
        )  # fmt: skip
        if "| 1 | 13500 |" not in check:
            failures.append("tab : l'instantané ne reflète pas l'écriture")
        await call(w["tab_delete_rows"], {"table_id": "tbl_planning_lots", "rows": [row]}, ctx)
        await call(
            t["tab_read_table"], {"table_id": "tbl_planning_lots", "columns": ["A", "C"]}, ctx
        )


async def cine(env: ToolEnvironment, ctx: ToolContext, write: bool) -> None:
    c = {x.name: x for x in cine_read_tools(env.cine())}
    lib = await call(c["cine_library"], {}, ctx)
    await call(c["cine_library"], {"kind": "movie", "quality": "4K"}, ctx)
    await call(c["cine_library_report"], {}, ctx)
    for media_id in [w for w in lib.split() if w.startswith(("m-", "s-"))][:3]:
        await call(c["cine_title"], {"media_id": media_id}, ctx)
    if write:
        await call(cine_write_tools(env.cine())[0], {}, ctx)


async def savoir(env: ToolEnvironment, ctx: ToolContext, write: bool) -> None:
    r = {x.name: x for x in savoir_read_tools(env.savoir())}
    await call(r["savoir_overview"], {}, ctx)
    await call(r["savoir_course"], {"course_id": 1}, ctx)
    await call(r["savoir_chapter"], {"chapter_id": 1, "max_chars": 500}, ctx)
    await call(r["savoir_flashcards"], {"course_id": 1}, ctx)
    due = await call(r["savoir_due_cards"], {"limit": 5}, ctx)
    if write:
        w = {x.name: x for x in savoir_write_tools(env.savoir())}
        course = await call(
            w["savoir_create_course"], {"title": "Essai Nexus", "subject": "Test"}, ctx
        )
        course_id = int(course.split("#")[1].split(" ")[0])
        chapter = await call(
            w["savoir_add_chapter"],
            {
                "course_id": course_id,
                "title": "Chapitre d'essai",
                "content": "La loi d'Ohm : $U = RI$.",
            },
            ctx,
        )
        chapter_id = int(chapter.split("#")[1].split(" ")[0])
        await call(
            w["savoir_add_flashcards"],
            {
                "chapter_id": chapter_id,
                "cards": [{"question": "Loi d'Ohm ?", "answer": "$U = RI$", "type": "formule"}],
            },
            ctx,
        )
        first = [line for line in due.splitlines() if line.startswith("- #")]
        if first:
            card_id = int(first[0].split("#")[1].split(" ")[0])
            await call(
                w["savoir_record_reviews"],
                {"reviews": [{"card_id": card_id, "rating": "correct"}]},
                ctx,
            )


SECTIONS = {
    "projets": projets,
    "tresorerie": tresorerie,
    "tab": tab,
    "cine": cine,
    "savoir": savoir,
}


async def main(write: bool, apps: tuple[str, ...]) -> int:
    env = ToolEnvironment(get_settings())
    ctx = ToolContext()
    try:
        for app in apps:
            print(f"\n── {app} ──")
            await SECTIONS[app](env, ctx, write)
    finally:
        await env.aclose()
    print("\nÉchecs :", failures or "aucun")
    return 1 if failures else 0


if __name__ == "__main__":
    chosen: tuple[str, ...] = ALL_APPS
    for arg in sys.argv[1:]:
        if arg.startswith("--apps"):
            chosen = tuple(a for a in arg.split("=", 1)[1].split(",") if a in SECTIONS)
    raise SystemExit(asyncio.run(main("--write" in sys.argv, chosen)))
