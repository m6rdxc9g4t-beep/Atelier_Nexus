"""Serveur de démonstration SANS LLM : vérifier l'interface de bout en bout.

Remplace les moteurs par un moteur scripté qui joue le parcours des agents experts avec
leurs VRAIS outils, contre les applications lancées sur la machine :
- Chef de projet / Product Owner (Atelier Projets) : tableau de bord → arborescence →
  création d'un élément, soumise à validation ;
- Data Analyst / Marketing (Atelier Viz) : jeux → schéma → requête → mesures DAX ;
- Finance / Comptable (Atelier Trésorerie, moteur local) : synthèse → budgets ;
- Tableur (Atelier Tab) : tables → contrôle du planning ; ou ajout d'un lot par le serveur MCP
  de Tab (TAB_MCP_COMMAND), soumis à validation ;
- agent personnalisé avec la boîte `cine` (Atelier Ciné) : bilan de la médiathèque → titres en 4K ;
- agent personnalisé avec les boîtes `savoir_*` (Atelier Savoir, moteur local) : séance du jour →
  question → notes enregistrées après validation.

    cd backend && DATABASE_URL=sqlite+aiosqlite:///./data/demo.db python -m scripts.demo_server
Usage réservé au développement : jamais en production.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import uvicorn

from app.core.llm.providers.base import LLMProvider
from app.core.llm.router import LLMRouter, get_llm_router
from app.core.llm.types import (
    ImageBlock,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    ProviderName,
    ResponseComplete,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
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


def _results(request: LLMRequest) -> dict[str, ToolResultBlock]:
    """Derniers résultats par outil, sur toute la conversation."""
    out: dict[str, ToolResultBlock] = {}
    for message in request.messages:
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                out[block.tool_name] = block
    return out


def _attachments_received(request: LLMRequest) -> list[str]:
    """Pièces jointes du dernier message utilisateur, telles que le modèle les reçoit."""
    last = next((m for m in reversed(request.messages) if m.role == "user"), None)
    lines: list[str] = []
    for block in last.content if last else []:
        if isinstance(block, ImageBlock):
            lines.append(
                f"une image {block.media_type} ({len(block.data) * 3 // 4:,} octets)".replace(
                    ",", " "
                )
            )
        elif isinstance(block, TextBlock) and block.text.startswith("<piece_jointe"):
            head = block.text.split("\n", 1)[0]
            name = re.search(r'nom="([^"]*)"', head)
            chars = len(block.text) - len(head)
            lines.append(
                f"**{name.group(1) if name else '?'}** : {chars:,} caractères de texte".replace(
                    ",", " "
                )
            )
    return lines


class DemoProvider(LLMProvider):
    def __init__(self, name: ProviderName) -> None:
        super().__init__("demo-scripte")
        self.name = name  # type: ignore[misc]
        self.calls = 0

    @property
    def is_configured(self) -> bool:
        return True

    def _call(self, name: str, args: dict[str, Any], text: str = "") -> LLMResponse:
        self.calls += 1
        content: list[TextBlock | ToolUseBlock] = [TextBlock(text=text)] if text else []
        content.append(ToolUseBlock(id=f"demo_{self.calls}", name=name, input=args))
        return LLMResponse(
            provider=self.name, model="demo-scripte", content=list(content),
            stop_reason="tool_use", usage=Usage(input_tokens=420, output_tokens=60),
        )  # fmt: skip

    def _say(self, text: str) -> LLMResponse:
        return LLMResponse(
            provider=self.name, model="demo-scripte", content=[TextBlock(text=text)],
            stop_reason="end_turn", usage=Usage(input_tokens=900, output_tokens=180),
        )  # fmt: skip

    def _step(self, request: LLMRequest) -> LLMResponse:
        tools = {t.name for t in request.tools}
        done = _results(request)
        if "projets_dashboard" in tools:
            return self._projets(done)
        if "data_via_list_datasets" in tools:
            return self._data_via(done)
        if "tresorerie_dashboard" in tools:
            return self._tresorerie(done)
        if "savoir_due_cards" in tools:
            return self._savoir(done, request)
        if "cine_library_report" in tools:
            return self._cine(done)
        if "tab_list_tables" in tools:
            return self._tab(done, request)
        received = _attachments_received(request)
        if received and not done:
            return self._say(
                "Voici ce que j'ai reçu (contenu réellement transmis au modèle) :\n\n"
                + "\n".join(f"- {line}" for line in received)
            )
        if "publish_artifact" in tools and "publish_artifact" not in done:
            return self._call(
                "publish_artifact",
                {
                    "kind": "markdown",
                    "title": "Note de démonstration",
                    "content": "# Note\n\nUn artefact pour vérifier l'historique.",
                },
                "Je publie une note dans le panneau Artefacts.",
            )
        return self._say(
            "Bonjour ! Ce serveur de démonstration joue un scénario avec le **Chef de projet**, "
            "le **Data Analyst** et l'agent **Finance**."
        )

    def _projets(self, done: dict[str, ToolResultBlock]) -> LLMResponse:
        if "projets_dashboard" not in done:
            return self._call(
                "projets_dashboard", {"project_id": 1}, "Je regarde le tableau de bord du projet."
            )
        if "projets_structure" not in done:
            return self._call("projets_structure", {"project_id": 1})
        if "projets_create_work_item" not in done:
            story = re.search(r"story_id (\d+)", done["projets_structure"].content)
            return self._call(
                "projets_create_work_item",
                {"story_id": int(story.group(1)) if story else 1, "type": "TASK",
                 "title": "Préparer la recette de l'authentification", "estimated_hours": 6,
                 "description": "Scénarios de recette OAuth2 + critères d'acceptation."},
                "Le projet est **en avance** (avancement 70,7 % pour 63,3 % du budget consommé), "
                "mais la recette n'est pas planifiée. Je propose d'ajouter une tâche :",
            )  # fmt: skip
        created = done["projets_create_work_item"]
        if created.is_error:
            return self._say("Entendu, je ne crée rien. Voulez-vous une autre estimation ?")
        return self._say(
            f"{created.content}\n\n**Point d'étape** : 8 éléments sur 17 terminés, un élément "
            "bloqué à débloquer en priorité, jalon « API Prête » atteint."
        )

    def _data_via(self, done: dict[str, ToolResultBlock]) -> LLMResponse:
        if "data_via_list_datasets" not in done:
            return self._call(
                "data_via_list_datasets", {}, "Je regarde les jeux disponibles dans Data Via."
            )
        if "data_via_describe_dataset" not in done:
            ids = re.findall(r"\| ([0-9a-f]{12}) \| ventes", done["data_via_list_datasets"].content)
            return self._call("data_via_describe_dataset", {"dataset_id": ids[0] if ids else "x"})
        if "data_via_query" not in done:
            ds = re.search(r"\(id ([0-9a-f]{12})\)", done["data_via_describe_dataset"].content)
            return self._call(
                "data_via_query",
                {"dataset_id": ds.group(1) if ds else "x", "dimensions": [{"field": "produit"}],
                 "measures": [{"field": "chiffre_affaires", "agg": "sum"}, {"agg": "count"}],
                 "sort": [{"key": "sum(chiffre_affaires)", "desc": True}]},
                "Le schéma est clair : je calcule le chiffre d'affaires par produit.",
            )  # fmt: skip
        if "publish_artifact" not in done:
            return self._call(
                "publish_artifact",
                {
                    "kind": "dax",
                    "title": "Mesures CA et part du CA",
                    "content": DAX,
                    "language": "dax",
                    "notes": NOTES,
                },
                "Je prépare les mesures DAX correspondantes.",
            )
        return self._say(
            "**Le logiciel porte l'activité** : premier produit en chiffre d'affaires, devant le "
            "matériel, la formation puis le support. Détail et mesures DAX dans le panneau Artefacts."
        )

    def _tresorerie(self, done: dict[str, ToolResultBlock]) -> LLMResponse:
        if "tresorerie_dashboard" not in done:
            return self._call("tresorerie_dashboard", {}, "Je fais le point sur le mois en cours.")
        if "tresorerie_budgets" not in done:
            return self._call("tresorerie_budgets", {})
        return self._say(
            "Vos dépenses du mois restent **dans les budgets** (51 % consommés au 20 du mois). "
            "Analyse faite **entièrement en local** : aucune donnée financière n'a quitté la machine."
        )

    def _tab(self, done: dict[str, ToolResultBlock], request: LLMRequest) -> LLMResponse:
        asked = next(
            (b.text for m in reversed(request.messages) if m.role == "user"
             for b in m.content if isinstance(b, TextBlock) and b.text),
            "",
        )  # fmt: skip
        if asked.lower().startswith("envoie") and "projets_import_tab_table" in {
            t.name for t in request.tools
        }:
            if "projets_preview_tab_import" not in done:
                return self._call(
                    "projets_preview_tab_import",
                    {"table_id": "tbl_planning_lots"},
                    "Voici ce que l'import ferait dans Atelier Projets :",
                )
            if "projets_import_tab_table" not in done:
                return self._call(
                    "projets_import_tab_table",
                    {"table_id": "tbl_planning_lots"},
                    "Aperçu vérifié (détail ci-dessus) : une ligne a changé depuis le dernier "
                    "import. Je l'envoie :",
                )
            result = done["projets_import_tab_table"]
            if result.is_error:
                return self._say("Entendu, rien n'est envoyé à Atelier Projets.")
            return self._say(result.content)
        if asked.lower().startswith("ajoute") and "tab_add_rows" in {t.name for t in request.tools}:
            if "tab_add_rows" not in done:
                return self._call(
                    "tab_add_rows",
                    {"table_id": "tbl_planning_lots",
                     "rows": [{"Lot / Tâche": "Plomberie", "Statut": "À faire", "Coût HT": "12 000",
                               "Échéance": "15/01/2027"}]},
                    "J'ajoute le lot au-dessus de la ligne de total du planning :",
                )  # fmt: skip
            added = done["tab_add_rows"]
            if added.is_error:
                return self._say("D'accord, je n'ajoute rien.")
            return self._say(f"{added.content}\n\nLe total du planning inclut maintenant ce lot.")
        if "tab_list_tables" not in done:
            return self._call("tab_list_tables", {}, "Je regarde les tables d'Atelier Tab.")
        if "tab_check_table" not in done:
            ids = re.findall(r"^\| (tbl_[A-Za-z0-9_-]+) \|", done["tab_list_tables"].content, re.M)
            return self._call(
                "tab_check_table", {"table_id": ids[0] if ids else "tbl_planning_lots"}
            )
        return self._say(
            "Contrôle terminé. " + done["tab_check_table"].content.split("\n", 1)[-1][:600]
        )

    def _cine(self, done: dict[str, ToolResultBlock]) -> LLMResponse:
        if "cine_library_report" not in done:
            return self._call("cine_library_report", {}, "Je fais le bilan de la médiathèque.")
        if "cine_library" not in done:
            return self._call("cine_library", {"kind": "movie", "quality": "4K"})
        return self._say(
            "Bilan : la série **Les Veilleurs** n'a que l'épisode 5 de la saison 2 (épisodes 1 à 4 "
            "manquants). Pour ce soir en 4K : **Orbit** (2024, HDR, sous-titres français)."
        )

    def _savoir(self, done: dict[str, ToolResultBlock], request: LLMRequest) -> LLMResponse:
        if "savoir_due_cards" not in done:
            return self._call("savoir_due_cards", {"limit": 3}, "Je prépare la séance du jour.")
        due = done["savoir_due_cards"].content
        card = re.search(r"- #(\d+) .*?\n  Q : (.+)", due)
        answers = sum(
            1
            for m in request.messages
            if m.role == "user" and any(isinstance(b, TextBlock) and b.text for b in m.content)
        )
        if not card:
            return self._say("Aucune carte à réviser aujourd'hui : bravo !")
        if answers < 2:
            return self._say(f"Première question : **{card.group(2)}**")
        if "savoir_record_reviews" not in done:
            return self._call(
                "savoir_record_reviews",
                {"reviews": [{"card_id": int(card.group(1)), "rating": "correct"}]},
                "Bonne réponse, avec une petite hésitation : je note **Correct**. J'enregistre la séance :",
            )
        result = done["savoir_record_reviews"]
        if result.is_error:
            return self._say("D'accord, rien n'est enregistré.")
        return self._say(f"{result.content}\n\nSéance terminée.")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return self._step(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        response = self._step(request)
        for chunk in re.findall(r"\S+\s*", response.text):
            await asyncio.sleep(0.015)
            yield TextDelta(text=chunk)
        yield ResponseComplete(response=response)

    async def list_models(self) -> list[str]:
        return ["demo-scripte"]


router = LLMRouter(
    {"anthropic": DemoProvider("anthropic"), "ollama": DemoProvider("ollama")}, default="anthropic"
)
app.dependency_overrides[get_llm_router] = lambda: router

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100)
