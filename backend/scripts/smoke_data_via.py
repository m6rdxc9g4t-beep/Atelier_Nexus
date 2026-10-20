"""Essai de bout en bout du connecteur contre un Atelier Viz réel.

Usage (Atelier Viz lancé, données d'exemple importées) :
    cd backend && python -m scripts.smoke_data_via [http://127.0.0.1:8000/api]

Simule le parcours d'un agent : liste → schéma → requête → vérification de mesure.
"""

import asyncio
import json
import sys

from app.schemas.data_via import DatasetProfile
from app.tools import ToolContext
from app.tools.data_via import DataViaClient, data_via_tools


async def main(base_url: str) -> int:
    async with DataViaClient(base_url) as client:
        status = await client.status()
        print("Statut :", status.model_dump_json())
        if not status.available:
            return 1
        tools = {t.name: t for t in data_via_tools(client)}
        ctx = ToolContext()

        listing = await tools["data_via_list_datasets"].invoke({}, ctx)
        print("\n## Liste\n" + listing.content)

        datasets = await client.list_datasets()
        target = next((d for d in datasets if "ventes" in d.name), datasets[0])
        described = await tools["data_via_describe_dataset"].invoke({"dataset_id": target.id}, ctx)
        print("\n## Schéma\n" + described.content)

        profile: DatasetProfile = ctx.state["data_via.profiles"][target.id]
        dim = next(c.name for c in profile.columns if c.type == "string")
        num = next(c.name for c in profile.columns if c.type == "number")
        date = next((c.name for c in profile.columns if c.type == "date"), None)

        query = {
            "dataset_id": target.id,
            "dimensions": [{"field": dim}],
            "measures": [{"field": num, "agg": "sum"}, {"agg": "count"}],
            "sort": [{"key": f"sum({num})", "desc": True}],
            "limit": 10,
        }
        result = await tools["data_via_query"].invoke(query, ctx)
        print(f"\n## Requête ({dim} × somme de {num})\n" + result.content)
        if result.is_error:
            return 1

        if date:
            by_month = {
                "dataset_id": target.id,
                "dimensions": [{"field": date, "bin": "month"}],
                "measures": [{"field": num, "agg": "sum"}],
                "sort": [{"key": f"{date}|month"}],
            }
            monthly = await tools["data_via_query"].invoke(by_month, ctx)
            print(f"\n## Par mois ({date}|month)\n" + monthly.content)
            if monthly.is_error:
                return 1

        check = await tools["data_via_check_expression"].invoke(
            {"dataset_id": target.id, "expression": f"DIVIDE(SUM({num}), COUNT(*))"}, ctx
        )
        print("\n## Vérification de mesure\n" + check.content)

        bad = await tools["data_via_query"].invoke(
            {**query, "dimensions": [{"field": dim[:-1] + "x"}]}, ctx
        )
        print("\n## Champ erroné (attendu : refus local)\n" + bad.content)

        artifact = json.loads(result.artifacts[0].content)
        print(f"\nArtefact : {len(artifact['rows'])} lignes, colonnes {artifact['columns']}")
        return 0 if (not check.is_error and bad.is_error) else 1


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api"
    raise SystemExit(asyncio.run(main(url)))
