"""Connecteurs Atelier Wiki et Atelier Formulaire (contrat atelier-node/1), sans réseau."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.tools.base import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import build_tools, get_toolset, is_sensitive
from tests.fake_wiki_formulaire import FakeFormulaire, FakeWiki


class Apps:
    def __init__(self) -> None:
        self.wiki = FakeWiki()
        self.form = FakeFormulaire()

    def env(self) -> ToolEnvironment:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            wiki_base_url="http://127.0.0.1:3200/api",
            formulaire_base_url="http://127.0.0.1:3300/api",
        )
        return ToolEnvironment(
            settings,
            transports={
                "wiki": httpx.MockTransport(self.wiki),
                "formulaire": httpx.MockTransport(self.form),
            },
        )

    def tools(self, *toolsets: str) -> dict[str, Any]:
        tools, unavailable = build_tools(list(toolsets), self.env())
        assert unavailable == []
        return {t.name: t for t in tools}


@pytest.fixture
def apps() -> Apps:
    return Apps()


CTX = ToolContext(conversation_id="c")


async def test_toolsets_flags() -> None:
    assert not get_toolset("wiki").writes and get_toolset("wiki_write").writes
    assert get_toolset("formulaire_reponses").sensitive and is_sensitive(["formulaire_reponses"])
    assert not is_sensitive(["wiki", "wiki_write", "formulaire", "formulaire_write"])
    # Désactivés quand l'adresse est vide (cas des tests et d'une installation sans ces apps)
    bare = ToolEnvironment(Settings(_env_file=None, wiki_base_url=None))  # type: ignore[call-arg]
    tools, unavailable = build_tools(["wiki"], bare)
    assert tools == [] and [u.id for u in unavailable] == ["wiki"]


async def test_wiki_read_search_and_page_as_data(apps: Apps) -> None:
    t = apps.tools("wiki")
    out = await t["wiki_spaces"].invoke({}, CTX)
    assert "Général" in out.content and out.data["format"] == "atelier-table/1"
    out = await t["wiki_search"].invoke({"query": "bienvenue"}, CTX)
    assert "Accueil" in out.content and "url" not in out.content.split("\n")[1]
    out = await t["wiki_search"].invoke({"query": "introuvable"}, CTX)
    assert "Aucune page" in out.content and not out.is_error
    out = await t["wiki_read_page"].invoke({"page_id": "1"}, CTX)
    assert '<donnee type="page du wiki">' in out.content and "[[Procédures]]" in out.content
    out = await t["wiki_read_page"].invoke({"page_id": "99"}, CTX)
    assert out.is_error and "introuvable" in out.content
    out = await t["wiki_read_page"].invoke({"page_id": "../1"}, CTX)
    assert out.is_error and "Paramètres invalides" in out.content  # jamais de chemin forgé


async def test_wiki_writes_need_approval_and_are_idempotent(apps: Apps) -> None:
    t = apps.tools("wiki_write")
    assert all(tool.requires_approval for tool in t.values())
    create = t["wiki_create_page"]
    args = {"title": "Journal de l'équipe", "content": "Début."}
    assert "Créer dans Atelier Wiki la page « Journal de l'équipe »" in create.summarize(args)
    first = await create.invoke(args, CTX)
    again = await create.invoke(args, CTX)  # même écriture validée deux fois : rejouée
    assert first.data["id"] == again.data["id"] == "2" and len(apps.wiki.pages) == 2
    keys = {r.headers.get("idempotency-key") for r in apps.wiki.requests if r.method == "POST"}
    assert len(keys) == 1 and next(iter(keys)).startswith("nexus-")
    out = await t["wiki_append_page"].invoke(
        {"page_id": "2", "content": "Point du lundi.", "heading": "24/10"}, CTX
    )
    assert not out.is_error and "## 24/10" in apps.wiki.pages[2]["content"]
    replace = t["wiki_replace_page"]
    assert replace.summarize({"page_id": "2", "content": "x"}).startswith("RÉÉCRIRE")
    out = await t["wiki_create_space"].invoke({"name": "Équipe", "description": "Mémoire"}, CTX)
    assert "Espace « Équipe » créé" in out.content
    out = await t["wiki_create_space"].invoke({"name": "Équipe"}, CTX)
    assert out.is_error and "déjà" in out.content


async def test_formulaire_summary_never_leaks_free_text(apps: Apps) -> None:
    t = apps.tools("formulaire")
    out = await t["formulaire_forms"].invoke({}, CTX)
    assert "Satisfaction atelier" in out.content
    out = await t["formulaire_form"].invoke({"form_id": "1"}, CTX)
    assert "Note globale" in out.content and "Oui, Peut-être, Non" in out.content
    out = await t["formulaire_summary"].invoke({"form_id": "1"}, CTX)
    assert "moyenne 4.0" in out.content and "| Oui | 1 | 50 % |" in out.content
    assert "alice@exemple.fr" not in out.content + json.dumps(out.data)
    assert "réponses libres, non reprises" in out.content


async def test_formulaire_responses_are_sensitive(apps: Apps) -> None:
    (tool,) = apps.tools("formulaire_reponses").values()
    assert tool.sensitive and not tool.requires_approval
    out = await tool.invoke({"form_id": "1"}, CTX)
    assert "Alice" in out.content and "2 réponse(s)" in out.content


async def test_formulaire_create_open_and_share(apps: Apps) -> None:
    t = apps.tools("formulaire_write")
    args = {
        "title": "Inscription atelier vélo",
        "questions": [
            {"type": "short_text", "label": "Nom", "required": True},
            {"type": "dropdown", "label": "Taille de t-shirt", "options": ["S", "M", "L"]},
            {"type": "scale", "label": "Niveau", "min": 1, "max": 5, "min_label": "Débutant"},
        ],
    }
    assert "3 question(s)" in t["formulaire_create_form"].summarize(args)
    out = await t["formulaire_create_form"].invoke(args, CTX)
    assert not out.is_error, out.content
    form = apps.form.forms[2]
    assert form["status"] == "draft"
    assert [q["id"] for q in form["questions"]] == ["q1", "q2", "q3"]
    assert form["questions"][2]["minLabel"] == "Débutant" and form["questions"][0]["required"]
    out = await t["formulaire_set_status"].invoke({"form_id": "2", "status": "open"}, CTX)
    assert "ouvert" in out.content and apps.form.forms[2]["status"] == "open"
    summary = t["formulaire_set_access"].summarize({"form_id": "2", "access": "public"})
    assert "TOUTE personne" in summary
    out = await t["formulaire_set_access"].invoke({"form_id": "2", "access": "public"}, CTX)
    assert "/r/jeton-public" in out.content


async def test_node_guard_refuses_non_loopback() -> None:
    settings = Settings(_env_file=None, wiki_base_url="https://wiki.example.org/api")  # type: ignore[call-arg]
    tools, _ = build_tools(["wiki"], ToolEnvironment(settings))
    out = await next(t for t in tools if t.name == "wiki_spaces").invoke({}, CTX)
    assert out.is_error and "bouclage" in out.content
