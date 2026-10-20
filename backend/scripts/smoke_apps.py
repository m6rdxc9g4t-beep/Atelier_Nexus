"""Essai réel des connecteurs Projets et Trésorerie (applications lancées sur la machine).

    cd backend && python -m scripts.smoke_apps [--write]

Lance chaque outil de lecture ; avec --write, joue aussi les écritures d'Atelier Projets
(création d'un élément, saisie de temps, journal, statut) : À N'UTILISER QUE SUR UNE BASE
DE TEST.
"""

import asyncio
import sys
from typing import Any

from app.core.config import get_settings
from app.tools import ToolContext
from app.tools.base import BaseTool
from app.tools.environment import ToolEnvironment
from app.tools.projets import projets_read_tools, projets_write_tools
from app.tools.tresorerie import tresorerie_tools

failures: list[str] = []


async def call(tool: BaseTool[Any], args: dict[str, Any], ctx: ToolContext) -> str:
    out = await tool.invoke(args, ctx)
    status = "ERREUR" if out.is_error else "ok"
    if out.is_error:
        failures.append(f"{tool.name}: {out.content}")
    first = out.content.splitlines()[0] if out.content else ""
    print(f"[{status}] {tool.name} {args} → {first[:110]}")
    return out.content


async def main(write: bool) -> int:
    env = ToolEnvironment(get_settings())
    ctx = ToolContext()
    try:
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

        t = {x.name: x for x in tresorerie_tools(env.tresorerie())}
        await call(t["tresorerie_dashboard"], {}, ctx)
        await call(t["tresorerie_accounts"], {}, ctx)
        await call(t["tresorerie_categories"], {}, ctx)
        await call(t["tresorerie_transactions"], {"type": "expense", "limit": 20}, ctx)
        await call(t["tresorerie_transactions"], {"uncategorized": True}, ctx)
        await call(t["tresorerie_budgets"], {}, ctx)
        await call(t["tresorerie_goals"], {}, ctx)
        await call(t["tresorerie_holdings"], {}, ctx)
    finally:
        await env.aclose()
    print("\nÉchecs :", failures or "aucun")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--write" in sys.argv)))
