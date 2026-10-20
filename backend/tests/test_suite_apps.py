"""Connecteurs Atelier Tab, Ciné et Savoir (Étape 7).

Ciné / Savoir : réponses RÉELLES capturées le 2026-10-20 (médiathèque d'exemple de Ciné,
cours de démonstration saisis dans Savoir) et rejouées par httpx.MockTransport.
Tab : enveloppes DataFlow v2.1.0 produites par le code d'export d'Atelier Tab (fixtures
partagées avec Atelier Viz), dans un vrai dossier temporaire.
"""

import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agents import AgentCatalog
from app.agents.registry import get_agent_class
from app.core.config import Settings
from app.tools import ToolContext
from app.tools.cine import CineClient, cine_read_tools, cine_write_tools, missing_episodes, ranges
from app.tools.environment import ToolEnvironment
from app.tools.http import AppRequestError, AppUnavailableError
from app.tools.savoir import SavoirClient, savoir_read_tools, savoir_write_tools
from app.tools.tab import TabSnapshots, tab_tools
from app.tools.toolsets import get_toolset
from tests.fakes import ScriptedProvider, make_router

FIX = Path(__file__).parent / "fixtures"


def fixture(app: str, name: str) -> Any:
    return json.loads((FIX / app / f"{name}.json").read_text())


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


# ═══ Atelier Ciné ═════════════════════════════════════════════════


class FakeCine:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        lib = fixture("cine", "library")
        self.veilleurs = next(s["id"] for s in lib["shows"] if s["title"] == "Les Veilleurs")
        self.routes = {
            "/api/health": fixture("cine", "health"),
            "/api/library": lib,
            "/api/library/m-ed346e643c76": fixture("cine", "movie_orbit"),
            "/api/library/s-10b5b786ad08": fixture("cine", "show_station_kepler"),
            f"/api/library/{self.veilleurs}": fixture("cine", "show_les_veilleurs"),
            "/api/ai/status": fixture("cine", "ai_status"),
        }
        # Les autres séries : fiche sans trou
        for show in lib["shows"]:
            self.routes.setdefault(f"/api/library/{show['id']}", show | {"episodeList": []})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path in self.routes:
            return httpx.Response(200, json=self.routes[path])
        if request.method == "POST" and path == "/api/scan":
            return httpx.Response(
                200,
                json={
                    "durationMs": 1240,
                    "counts": {"movies": 4, "shows": 3, "episodes": 6},
                    "errors": [
                        {
                            "path": "/Volumes/NAS/Films",
                            "code": "ENOENT",
                            "message": "Dossier introuvable",
                        }
                    ],
                },
            )
        if request.method == "POST" and path.startswith("/api/ai/summary/"):
            return httpx.Response(
                200, json={"synopsis": "Une station isolée.", "genres": "SF, Drame", "tags": None}
            )
        return httpx.Response(404, json={"error": "Média introuvable"})


@pytest.fixture
def cine() -> tuple[CineClient, FakeCine]:
    fake = FakeCine()
    return CineClient("http://cine.test/api", transport=httpx.MockTransport(fake)), fake


async def test_cine_library_filters_and_never_leaks_paths(
    cine: tuple[CineClient, FakeCine],
) -> None:
    client, _ = cine
    tools = by_name(cine_read_tools(client))
    out = await tools["cine_library"].invoke({}, ToolContext())
    assert not out.is_error
    assert "4 film(s), 3 série(s)" in out.content
    assert "Orbit" in out.content and "Station Kepler" in out.content
    assert "/home/claude" not in out.content and "sample-media" not in out.content

    four_k = await tools["cine_library"].invoke({"quality": "4K", "kind": "movie"}, ToolContext())
    assert "Orbit" in four_k.content and "Le Dernier Phare" not in four_k.content


async def test_cine_title_shows_seasons_and_missing_episodes(
    cine: tuple[CineClient, FakeCine],
) -> None:
    client, fake = cine
    tools = by_name(cine_read_tools(client))
    kepler = await tools["cine_title"].invoke({"media_id": "s-10b5b786ad08"}, ToolContext())
    assert "Saison 2" in kepler.content and "Retour" in kepler.content
    assert "manquants" not in kepler.content

    veilleurs = await tools["cine_title"].invoke({"media_id": fake.veilleurs}, ToolContext())
    assert "Saison 2 : 1-4" in veilleurs.content

    movie = await tools["cine_title"].invoke({"media_id": "m-ed346e643c76"}, ToolContext())
    assert "4K Ultra HD" in movie.content and "fr (srt)" in movie.content
    assert "Orbit.2024.2160p.HDR.WEB-DL.mkv" in movie.content  # nom du fichier seul
    assert "/home/" not in movie.content

    bad = await tools["cine_title"].invoke({"media_id": "../etc"}, ToolContext())
    assert bad.is_error and not [r for r in fake.requests if ".." in r.url.path]


async def test_cine_report_finds_gaps_and_untitled_years(cine: tuple[CineClient, FakeCine]) -> None:
    client, _ = cine
    out = await by_name(cine_read_tools(client))["cine_library_report"].invoke({}, ToolContext())
    assert "Les Veilleurs | 2 | 1-4 | 4" in out.content
    assert "Films sans sous-titres" in out.content


async def test_cine_scan_needs_approval_and_hides_nas_path(
    cine: tuple[CineClient, FakeCine],
) -> None:
    client, _ = cine
    scan = cine_write_tools(client)[0]
    assert scan.requires_approval and not scan.sensitive
    assert "Relancer l'analyse" in scan.approval_summary(scan.input_model())
    out = await scan.invoke({}, ToolContext())
    assert "4 film(s), 3 série(s), 6 épisode(s)" in out.content
    assert "Films (Dossier introuvable)" in out.content and "/Volumes" not in out.content


async def test_cine_ai_summary_tolerates_loose_llm_output(
    cine: tuple[CineClient, FakeCine],
) -> None:
    client, _ = cine
    out = await by_name(cine_read_tools(client))["cine_ai_summary"].invoke(
        {"media_id": "s-10b5b786ad08"}, ToolContext()
    )
    assert "Genres : SF, Drame" in out.content and "Tags : ∅" in out.content


async def test_cine_health_checks_identity() -> None:
    def other(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = CineClient("http://x.test/api", transport=httpx.MockTransport(other))
    with pytest.raises(AppRequestError, match="pas Atelier Ciné"):
        await client.health()


def test_episode_gaps_and_ranges() -> None:
    from app.schemas.cine import Episode

    def ep(season: int, n: int | None, end: int | None = None) -> Episode:
        return Episode.model_validate(
            {"id": "e", "season": season, "episode": n, "episodeEnd": end,
             "addedAt": "2026-10-20T10:00:00Z", "path": "x"}
        )  # fmt: skip

    assert missing_episodes([ep(1, 1), ep(1, 2, 3), ep(1, 6), ep(2, None)]) == {1: [4, 5]}
    assert ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"


# ═══ Atelier Savoir ═══════════════════════════════════════════════


class FakeSavoir:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        if body is not None:
            self.bodies.append(body)
        routes = {
            "/api/stats": "stats",
            "/api/courses": "courses",
            "/api/courses/1": "course_1",
            "/api/chapters/1": "chapter_1",
            "/api/study/session": "study_session",
        }
        if method == "GET" and path in routes:
            return httpx.Response(200, json=fixture("savoir", routes[path]))
        if method == "GET" and path == "/api/flashcards":
            return httpx.Response(200, json=fixture("savoir", "flashcards_course_1"))
        if method == "POST" and path == "/api/flashcards":
            card = fixture("savoir", "flashcards_course_1")[0]
            created = [
                card | {"id": 100 + i, "question": c["question"], "answer": c["answer"],
                        "card_type": c["type"], "status": "nouvelle"}
                for i, c in enumerate(body["cards"])
            ]  # fmt: skip
            return httpx.Response(201, json={"created": len(created), "cards": created})
        if method == "POST" and path.endswith("/review"):
            card_id = int(path.split("/")[3])
            if card_id == 999:
                return httpx.Response(404, json={"error": "Carte introuvable."})
            card = fixture("savoir", "flashcards_course_1")[0]
            return httpx.Response(
                200,
                json=card | {"id": card_id, "status": "en_cours", "due_at": "2026-10-24 10:24:59"},
            )
        if method == "POST" and path == "/api/courses":
            return httpx.Response(
                201, json=fixture("savoir", "courses")[0] | {"id": 3, "title": body["title"]}
            )
        # Savoir renvoie une page HTML pour une méthode non autorisée (405)
        return httpx.Response(405, text="<!doctype html><title>405 Method Not Allowed</title>")


@pytest.fixture
def savoir() -> tuple[SavoirClient, FakeSavoir]:
    fake = FakeSavoir()
    return SavoirClient("http://savoir.test/api", transport=httpx.MockTransport(fake)), fake


async def test_savoir_tools_are_sensitive_and_parse_real_payloads(
    savoir: tuple[SavoirClient, FakeSavoir],
) -> None:
    client, _ = savoir
    tools = by_name(savoir_read_tools(client) + savoir_write_tools(client))
    assert all(t.sensitive for t in tools.values())
    assert {n for n, t in tools.items() if t.requires_approval} == {
        "savoir_create_course", "savoir_add_chapter", "savoir_add_flashcards", "savoir_record_reviews",
    }  # fmt: skip

    overview = await tools["savoir_overview"].invoke({}, ToolContext())
    assert "2 cours, 3 chapitre(s), 6 carte(s)" in overview.content
    assert "| 1 | Physique | Sciences | 2 | 5 |" in overview.content

    course = await tools["savoir_course"].invoke({"course_id": 1}, ToolContext())
    assert "Relativité restreinte" in course.content and "Thermodynamique" in course.content

    chapter = await tools["savoir_chapter"].invoke(
        {"chapter_id": 1, "max_chars": 500}, ToolContext()
    )
    assert "$E = mc^2$" in chapter.content

    cards = await tools["savoir_flashcards"].invoke(
        {"course_id": 1, "status": "nouvelle"}, ToolContext()
    )
    assert "Expression du facteur de Lorentz" in cards.content
    assert (
        cards.content.startswith("2 carte(s) : 2 nouvelle.")
        or "nouvelle" in cards.content.split("\n")[0]
    )
    assert "Que relie la formule" not in cards.content  # carte notée « maîtrisé » : filtrée


async def test_savoir_due_cards_and_dates_are_utc(savoir: tuple[SavoirClient, FakeSavoir]) -> None:
    client, fake = savoir
    session = await client.study_session(None, "dues", 30)
    assert session.cards[0].due_at.tzinfo is not None
    out = await by_name(savoir_read_tools(client))["savoir_due_cards"].invoke(
        {"limit": 5}, ToolContext()
    )
    assert "ne les montre qu'après" in out.content
    assert fake.requests[-1].url.params["limit"] == "5"


async def test_savoir_add_flashcards_sends_type_key_and_ia_origin(
    savoir: tuple[SavoirClient, FakeSavoir],
) -> None:
    client, fake = savoir
    tool = by_name(savoir_write_tools(client))["savoir_add_flashcards"]
    params = {
        "chapter_id": 2,
        "cards": [
            {
                "question": "Énoncer le second principe",
                "answer": "L'entropie d'un système isolé croît.",
                "type": "theoreme",
            },
            {"question": "Unité de l'énergie", "answer": "Le joule (J)", "type": "notion"},
        ],
    }
    summary = tool.approval_summary(tool.input_model.model_validate(params))
    assert "2 carte(s) dans le chapitre #2" in summary and "1 théorème" in summary
    out = await tool.invoke(params, ToolContext())
    assert "2 carte(s) enregistrée(s) : #100, #101" in out.content
    assert fake.bodies[-1] == {"chapter_id": 2, "origin": "ia", "cards": params["cards"]}

    missing = await tool.invoke({"cards": params["cards"]}, ToolContext())
    assert missing.is_error


async def test_savoir_record_reviews_in_one_approval(
    savoir: tuple[SavoirClient, FakeSavoir],
) -> None:
    client, _ = savoir
    tool = by_name(savoir_write_tools(client))["savoir_record_reviews"]
    params = {
        "reviews": [{"card_id": 3, "rating": "correct"}, {"card_id": 999, "rating": "maitrise"}]
    }
    assert "2 révision(s) (1 Correct, 1 Maîtrisé)" in tool.approval_summary(
        tool.input_model.model_validate(params)
    )
    out = await tool.invoke(params, ToolContext())
    assert "1 révision(s) enregistrée(s)" in out.content and "#3 → En cours" in out.content
    assert "1 échec(s) : #999 (Carte introuvable.)" in out.content and not out.is_error


async def test_savoir_identity_and_html_errors() -> None:
    def treso(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Ressource introuvable"})

    client = SavoirClient("http://x.test/api", transport=httpx.MockTransport(treso))
    with pytest.raises(AppRequestError, match="pas Atelier Savoir"):
        await client.stats()

    fake = FakeSavoir()
    client = SavoirClient("http://s.test/api", transport=httpx.MockTransport(fake))
    with pytest.raises(AppRequestError, match="erreur 405"):
        await client.request("PUT", "stats")


# ═══ Atelier Tab ══════════════════════════════════════════════════


@pytest.fixture
def exports(tmp_path: Path) -> Path:
    folder = tmp_path / "exports"
    folder.mkdir()
    for name in ("tbl_planning_lots", "tbl_materiaux"):
        shutil.copy(FIX / "tab" / f"{name}.json", folder / f"{name}.json")
    # Export manuel plus ancien de la même table : l'instantané doit l'emporter
    old = fixture("tab", "tbl_planning_lots")
    old["exported_at"] = "2026-09-01T08:00:00Z"
    old["project"]["records"] = old["project"]["records"][:1]
    (folder / "atelier_projets_renovation-urbaine-2026_2026-09-01.json").write_text(json.dumps(old))
    # Export manuel d'une table sans instantané : listé comme tel
    lone = fixture("tab", "tbl_materiaux")
    lone["project"]["source_table"] = {"id": "tbl_budget_global", "name": "Budget global"}
    (folder / "atelier_projets_budget_2026-10-01.json").write_text(json.dumps(lone))
    # Distracteurs
    (folder / "notes.json").write_text('{"hello": "world"}')
    (folder / "tbl_tmp.json").write_text('{"target_system": "atelier_projets", "schema_')
    (folder / "lisez-moi.txt").write_text("rien")
    (folder / ".tbl_planning_lots.json.123.tmp").write_text("{}")
    v3 = fixture("tab", "tbl_materiaux") | {"schema_version": "3.0.0"}
    (folder / "tbl_futur.json").write_text(json.dumps(v3))
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps(fixture("tab", "tbl_materiaux")))
    if hasattr(os, "symlink"):
        (folder / "lien.json").symlink_to(outside)
    return folder


async def test_tab_lists_snapshots_dedupes_exports_and_ignores_junk(exports: Path) -> None:
    snapshots = TabSnapshots(str(exports))
    tables, too_big = await snapshots.tables()
    assert [(t.id, t.source) for t in tables] == [
        ("tbl_planning_lots", "instantané"),
        ("tbl_budget_global", "export manuel"),
        ("tbl_materiaux", "instantané"),
    ]
    assert tables[0].rows == 3 and too_big == []
    out = await by_name(tab_tools(snapshots))["tab_list_tables"].invoke({}, ToolContext())
    assert "3 table(s)" in out.content and "Planning & Lots" in out.content


async def test_tab_read_table_values_percent_and_totals(exports: Path) -> None:
    tools = by_name(tab_tools(TabSnapshots(str(exports))))
    planning = await tools["tab_read_table"].invoke(
        {"table_id": "tbl_planning_lots"}, ToolContext()
    )
    assert "C « Coût HT » : montant, rôle montant HT" in planning.content
    assert (
        "| 1 | Gros œuvre | En cours | 45000 | 54000 | Marie Dubois | 2026-11-30 |"
        in planning.content
    )
    assert "Lignes de total" in planning.content and "106200" in planning.content

    mat = await tools["tab_read_table"].invoke(
        {"table_id": "tbl_materiaux", "columns": ["A", "tva", "Commandé", "Référence"]},
        ToolContext(),
    )
    assert "| 1 | Béton C25/30 (m³) | 20 % | oui | 00123 |" in mat.content

    page = await tools["tab_read_table"].invoke(
        {"table_id": "tbl_planning_lots", "limit": 1, "offset": 1}, ToolContext()
    )
    assert (
        "Charpente bois" in page.content and "Gros œuvre" not in page.content.split("Lignes 2")[1]
    )
    assert page.artifacts and page.artifacts[0].kind == "data_preview"

    unknown = await tools["tab_read_table"].invoke({"table_id": "tbl_inconnue"}, ToolContext())
    assert unknown.is_error and "introuvable" in unknown.content
    bad_col = await tools["tab_read_table"].invoke(
        {"table_id": "tbl_planning_lots", "columns": ["Prix"]}, ToolContext()
    )
    assert bad_col.is_error and "« Lot / Tâche »" in bad_col.content


async def test_tab_aggregate_groups_filters_and_skips_totals(exports: Path) -> None:
    tool = by_name(tab_tools(TabSnapshots(str(exports))))["tab_aggregate"]
    out = await tool.invoke(
        {"table_id": "tbl_planning_lots", "group_by": "Statut",
         "measures": [{"column": "Coût HT", "agg": "sum"}, {"column": "cost_ttc", "agg": "max"}]},
        ToolContext(),
    )  # fmt: skip
    assert "| En cours | 1 | 45000 | 54000 |" in out.content
    assert "| Terminé | 1 | 28500 | 34200 |" in out.content
    total = await tool.invoke(
        {"table_id": "tbl_planning_lots", "measures": [{"column": "C"}]}, ToolContext()
    )
    assert "| 3 | 88500 |" in total.content  # la ligne TOTAL n'est pas comptée deux fois
    filtered = await tool.invoke(
        {"table_id": "tbl_planning_lots", "measures": [{"column": "C", "agg": "count"}],
         "filters": {"Responsable": "marie dubois"}},
        ToolContext(),
    )  # fmt: skip
    assert "1 ligne(s) retenue(s) sur 3" in filtered.content


async def test_tab_check_table_reports_late_items_and_errors(exports: Path, tmp_path: Path) -> None:
    tool = by_name(tab_tools(TabSnapshots(str(exports))))["tab_check_table"]
    late = await tool.invoke(
        {"table_id": "tbl_planning_lots", "as_of": date(2026, 12, 20).isoformat()}, ToolContext()
    )
    assert "Gros œuvre : échéance 2026-11-30, statut En cours" in late.content
    assert "Charpente bois" not in late.content  # terminé : pas en retard
    assert "Prête pour l'import dans Atelier Projets" in late.content

    broken = fixture("tab", "tbl_planning_lots")
    rec = broken["project"]["records"][1]["values"]
    rec["D"] = {"raw": "=C2/0", "computed": "#DIV/0!"}
    rec["A"] = {"raw": "", "computed": None}
    (exports / "tbl_planning_lots.json").write_text(json.dumps(broken))
    out = await tool.invoke({"table_id": "tbl_planning_lots", "as_of": "2026-10-20"}, ToolContext())
    assert "Coût TTC : #DIV/0! (1 cellule(s), lignes 2)" in out.content
    assert "Titre vide (colonne « Lot / Tâche ») : lignes 2" in out.content
    assert "Pas encore importable" in out.content


async def test_tab_missing_folder_is_a_clear_error(tmp_path: Path) -> None:
    out = await by_name(tab_tools(TabSnapshots(str(tmp_path / "absent"))))[
        "tab_list_tables"
    ].invoke({}, ToolContext())
    assert out.is_error and "Ouvrez l'app de bureau Atelier Tab" in out.content
    with pytest.raises(AppUnavailableError):
        await TabSnapshots(str(tmp_path / "absent")).tables()


async def test_tab_size_cap(exports: Path) -> None:
    tables, too_big = await TabSnapshots(str(exports), max_mb=1).tables()
    assert len(tables) == 3 and too_big == []
    big = exports / "tbl_enorme.json"
    big.write_text(" " * (1024 * 1024 + 10))
    _, too_big = await TabSnapshots(str(exports), max_mb=1).tables()
    assert too_big == ["tbl_enorme.json"]


# ═══ Agents et boîtes à outils ════════════════════════════════════


def test_new_toolsets_and_agents() -> None:
    assert get_toolset("savoir_read").sensitive and get_toolset("savoir_write").sensitive
    assert not get_toolset("tab").sensitive and not get_toolset("cine").sensitive
    assert get_toolset("cine_write").writes and get_toolset("savoir_write").writes

    router = make_router(ScriptedProvider("anthropic"))
    env = ToolEnvironment(Settings())
    tutor = get_agent_class("tuteur")(router, env)
    assert tutor.local_only
    assert {"savoir_due_cards", "savoir_record_reviews"} <= set(tutor.tools)
    assert not get_agent_class("cineclub")(router, env).local_only
    assert "tab_aggregate" in get_agent_class("chef_de_projet")(router, env).tools
    assert "tab_check_table" in get_agent_class("data_analyst")(router, env).tools


async def test_catalog_lists_new_agents() -> None:
    router = make_router(ScriptedProvider("anthropic"))
    infos = {i.name: i for i in await AgentCatalog().infos(router, ToolEnvironment(Settings()))}
    assert {"tableur", "cineclub", "tuteur"} <= set(infos)
    assert infos["tuteur"].local_only and infos["tuteur"].category == "Apprentissage"
