"""Serveur de démonstration SANS LLM : vérifier l'interface de bout en bout.

Remplace le routeur LLM par un moteur scripté qui joue le parcours d'un agent
(liste des jeux Data Via → schéma → requête → publication d'un DAX → réponse).
Les outils, eux, sont réels : il faut Atelier Viz lancé avec ses données d'exemple.

    cd backend && python -m scripts.demo_server     # http://localhost:8100
Usage réservé au développement : jamais en production.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import uvicorn

from app.agents.base import BaseAgent
from app.agents.registry import register_agent
from app.core.config import get_settings
from app.core.llm.providers.base import LLMProvider
from app.core.llm.router import LLMRouter, get_llm_router
from app.core.llm.types import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    ResponseComplete,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from app.tools import BaseTool, PublishArtifactTool
from app.tools.data_via import DataViaClient, data_via_tools
from main import app

DAX = """// Chiffre d'affaires sur la période filtrée
CA Total =
VAR CA = SUM ( Ventes[chiffre_affaires] )
RETURN
    CA

// Part de chaque produit dans le CA total
Part du CA =
VAR CAProduit = [CA Total]
VAR CAToutes =
    CALCULATE ( [CA Total], REMOVEFILTERS ( Ventes[produit] ) )
RETURN
    DIVIDE ( CAProduit, CAToutes )"""

NOTES = (
    "1. Accueil › **Nouvelle mesure** dans la table `Ventes`.\n"
    "2. Collez chaque mesure séparément.\n"
    "3. Format de `Part du CA` : **Pourcentage**, 1 décimale."
)


def _last_results(request: LLMRequest) -> list[ToolResultBlock]:
    last = request.messages[-1]
    return [b for b in last.content if isinstance(b, ToolResultBlock)]


class DemoProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        super().__init__("demo-scripte")

    @property
    def is_configured(self) -> bool:
        return True

    def _step(self, request: LLMRequest) -> LLMResponse:
        results = _last_results(request)
        done = {
            r.tool_name
            for m in request.messages
            for r in m.content
            if isinstance(r, ToolResultBlock)
        }
        tools = {t.name for t in request.tools}

        def call(name: str, args: dict[str, Any], text: str = "") -> LLMResponse:
            content: list[TextBlock | ToolUseBlock] = [TextBlock(text=text)] if text else []
            content.append(ToolUseBlock(id=f"demo_{len(done)}", name=name, input=args))
            return LLMResponse(
                provider="anthropic", model="demo-scripte", content=list(content),
                stop_reason="tool_use", usage=Usage(input_tokens=420, output_tokens=60),
            )  # fmt: skip

        if "data_via_list_datasets" in tools and "data_via_list_datasets" not in done:
            return call(
                "data_via_list_datasets", {}, "Je regarde les jeux disponibles dans Data Via."
            )
        if "data_via_describe_dataset" not in done and results:
            ids = re.findall(r"\| ([0-9a-f]{12}) \| ventes", results[0].content)
            if ids:
                return call("data_via_describe_dataset", {"dataset_id": ids[0]})
        if "data_via_query" not in done and "data_via_describe_dataset" in done:
            ds = re.search(r"\(id ([0-9a-f]{12})\)", results[0].content) if results else None
            if ds:
                return call(
                    "data_via_query",
                    {
                        "dataset_id": ds.group(1),
                        "dimensions": [{"field": "produit"}],
                        "measures": [{"field": "chiffre_affaires", "agg": "sum"}, {"agg": "count"}],
                        "sort": [{"key": "sum(chiffre_affaires)", "desc": True}],
                    },
                    "Le schéma est clair : je calcule le chiffre d'affaires par produit.",
                )
        if "publish_artifact" not in done and "data_via_query" in done:
            return call(
                "publish_artifact",
                {"kind": "dax", "title": "Mesures CA et part du CA", "content": DAX,
                 "language": "dax", "notes": NOTES},
                "Je prépare les mesures DAX correspondantes.",
            )  # fmt: skip
        answer = (
            "**Le logiciel porte l'activité** : c'est le premier produit en chiffre d'affaires, "
            "devant le matériel, la formation puis le support.\n\n"
            "| Produit | Lecture |\n|---|---|\n"
            "| Logiciel | ≈ 44 % du CA, panier le plus élevé |\n"
            "| Support | moins de 10 % du CA : levier de récurrence |\n\n"
            "Le détail chiffré et les deux mesures DAX (`CA Total`, `Part du CA`) sont dans le "
            "panneau Artefacts, avec les étapes d'intégration dans Power BI Desktop."
        )
        if "data_via_list_datasets" not in tools:
            answer = (
                "Bonjour ! Ce serveur de démonstration ne joue un scénario complet "
                "qu'avec l'agent Démo Data Via."
            )
        return LLMResponse(
            provider="anthropic", model="demo-scripte", content=[TextBlock(text=answer)],
            stop_reason="end_turn", usage=Usage(input_tokens=900, output_tokens=180),
        )  # fmt: skip

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return self._step(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        import asyncio

        response = self._step(request)
        for chunk in re.findall(r"\S+\s*", response.text):
            await asyncio.sleep(0.02)
            yield TextDelta(text=chunk)
        yield ResponseComplete(response=response)

    async def list_models(self) -> list[str]:
        return ["demo-scripte"]


class _Offline(DemoProvider):
    name = "ollama"  # type: ignore[assignment]

    @property
    def is_configured(self) -> bool:
        return False


_client = DataViaClient.from_settings(get_settings())


@register_agent
class DemoDataViaAgent(BaseAgent):
    name = "demo_data_via"
    display_name = "Démo Data Via"
    description = (
        "Scénario de démonstration : analyse du CA par produit dans Atelier Viz, puis mesures DAX."
    )
    system_prompt = "Démonstration."

    def default_tools(self) -> list[BaseTool[Any]]:
        assert _client is not None
        return [*data_via_tools(_client), PublishArtifactTool()]


router = LLMRouter({"anthropic": DemoProvider(), "ollama": _Offline()}, default="anthropic")
app.dependency_overrides[get_llm_router] = lambda: router

if __name__ == "__main__":
    print(json.dumps({"demo": True, "port": 8100}))
    uvicorn.run(app, host="127.0.0.1", port=8100)
