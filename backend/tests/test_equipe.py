"""Mémoire d'équipe (Wiki) et rapports déterministes (Projets, Formulaire), sans réseau."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.tools import equipe
from app.tools.base import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import build_tools, get_toolset
from tests.fake_wiki_formulaire import FakeFormulaire, FakeWiki
from tests.test_connectors import FakeProjets

CTX = ToolContext(conversation_id="c")
NOW = datetime(2026, 10, 24, 9, 12, tzinfo=ZoneInfo("Europe/Paris"))


class Team:
    def __init__(self) -> None:
        self.wiki = FakeWiki()
        self.form = FakeFormulaire()
        self.projets = FakeProjets()

    def tools(self, *ids: str) -> dict[str, Any]:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            wiki_base_url="http://127.0.0.1:3200/api",
            formulaire_base_url="http://127.0.0.1:3300/api",
            projets_base_url="http://127.0.0.1:3000/api",
        )
        env = ToolEnvironment(
            settings,
            transports={
                "wiki": httpx.MockTransport(self.wiki),
                "formulaire": httpx.MockTransport(self.form),
                "projets": httpx.MockTransport(self.projets),
            },
        )
        tools, unavailable = build_tools(list(ids), env)
        assert unavailable == []
        return {t.name: t for t in tools}


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch) -> Team:
    monkeypatch.setattr(equipe, "now", lambda env: NOW)
    return Team()


def test_toolsets() -> None:
    assert get_toolset("equipe_write").writes and not get_toolset("equipe").writes
    assert not any(get_toolset(i).sensitive for i in ("equipe", "equipe_write", "equipe_rapports"))


async def test_memory_is_created_on_first_note_then_read_back(team: Team) -> None:
    t = team.tools("equipe", "equipe_write")
    out = await t["equipe_memoire"].invoke({}, CTX)
    assert (
        "n'existe pas encore" in out.content and len(team.wiki.spaces) == 1
    )  # lecture : rien créé
    note = t["equipe_noter"]
    args = {
        "texte": "Lot 3 livré ; reste la recette.",
        "auteur": "Chef de projet",
        "titre": "Avancement",
    }
    assert "crée l'espace « Équipe Atelier »" in note.summarize(args)
    out = await note.invoke(args, CTX)
    assert not out.is_error, out.content
    space = team.wiki.spaces[-1]
    assert space["name"] == "Équipe Atelier"
    journal = next(p for p in team.wiki.pages.values() if p["title"] == "Journal de l'équipe")
    assert "## 2026-10-24 09:12 · Chef de projet — Avancement" in journal["content"]
    await note.invoke({"texte": "Recette planifiée.", "auteur": "Product Owner"}, CTX)
    assert (
        len(team.wiki.spaces) == 2
        and sum(p["title"] == "Journal de l'équipe" for p in team.wiki.pages.values()) == 1
    )

    await t["equipe_decision"].invoke(
        {"titre": "Recette le 30/10", "decision": "Recette avec 3 utilisateurs.", "contexte": "Retard du lot 2.",
         "auteur": "Chef de projet"}, CTX)  # fmt: skip
    await t["equipe_compte_rendu"].invoke(
        {"sujet": "Lancement", "contenu": "Présents : …\n\nActions : …"}, CTX
    )
    cr = next(p for p in team.wiki.pages.values() if p["title"] == "CR 2026-10-24 — Lancement")
    parent = next(p for p in team.wiki.pages.values() if p["title"] == "Comptes rendus")
    assert cr["parent_id"] == parent["id"]

    out = await t["equipe_memoire"].invoke({"entrees": 5}, CTX)
    assert "Lot 3 livré" in out.content and "Recette planifiée" in out.content
    assert '<donnee type="journal de l\'équipe">' in out.content
    assert (
        "2026-10-24 : Recette le 30/10" in out.content
        and "CR 2026-10-24 — Lancement" in out.content
    )
    out = await t["equipe_memoire"].invoke({"recherche": "recette"}, CTX)
    assert "Journal de l'équipe" in out.content


async def test_progress_report_is_deterministic(team: Team) -> None:
    (tool,) = [
        v for k, v in team.tools("equipe_rapports").items() if k == "equipe_point_avancement"
    ]
    out = await tool.invoke({"horizon_jours": 14}, CTX)
    assert not out.is_error, out.content
    text = out.content
    assert text.startswith("# Point d'avancement du 24/10/2026")
    assert "tendance : en avance" in text and "28.5 j passés sur 45 j" in text
    assert "**En retard (" in text and "#12345" in text and "3 j de retard" in text
    assert "Bloqués ou en attente (2)" in text and "Jalons à venir" in text and "Beta UI" in text
    assert text.count("#205") == 1  # bloqué : une seule liste
    assert out.artifacts[0].kind == "markdown" and out.data["late"] >= 1
    out = await tool.invoke({"projet": "inexistant"}, CTX)
    assert out.is_error


async def test_forms_digest_has_no_personal_data(team: Team) -> None:
    tools = team.tools("equipe_rapports")
    out = await tools["equipe_synthese_formulaires"].invoke({}, CTX)
    assert "Satisfaction atelier" in out.content and "moyenne 4.0" in out.content
    assert "alice@exemple.fr" not in out.content and "Alice" not in str(out.data)


async def test_ritual_chain_report_then_note(team: Team) -> None:
    """Ce que fait le rituel du lundi : le rapport devient une note du journal (sans modèle)."""
    t = team.tools("equipe_rapports", "equipe_write")
    report = await t["equipe_point_avancement"].invoke({}, CTX)
    out = await t["equipe_noter"].invoke(
        {"texte": report.content, "auteur": "Rituel du lundi", "titre": "Point d'avancement"}, CTX
    )
    assert not out.is_error
    journal = next(p for p in team.wiki.pages.values() if p["title"] == "Journal de l'équipe")
    assert (
        "Rituel du lundi — Point d'avancement" in journal["content"]
        and "#12345" in journal["content"]
    )
