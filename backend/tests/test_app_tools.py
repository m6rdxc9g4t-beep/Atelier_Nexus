"""Outils Trésorerie, Savoir et Ciné pour les petits modèles locaux (audit F-05 à F-21).

Totaux par catégorie sur toutes les pages, convention de signe, indications de lancement,
artefacts seulement quand la réponse est partielle, sorties bornées, écritures Savoir par
lots avec un résumé de validation complet, import d'un chapitre depuis un fichier joint, genres
de Ciné. Applications simulées par httpx.MockTransport (fixtures réelles quand elles existent).
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.schemas.attachments import AttachmentInfo
from app.tools import ToolContext
from app.tools.cine import CineClient, cine_read_tools
from app.tools.environment import ToolEnvironment
from app.tools.files import ConversationFiles
from app.tools.formatting import euros
from app.tools.savoir import SavoirClient, savoir_read_tools, savoir_write_tools
from app.tools.toolsets import get_toolset
from app.tools.tresorerie import (
    TresorerieClient,
    months_between,
    signed,
    trend,
    tresorerie_tools,
)

FIX = Path(__file__).parent / "fixtures"


def fixture(app: str, name: str) -> Any:
    return json.loads((FIX / app / f"{name}.json").read_text())


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


# ═══ Atelier Trésorerie ═══════════════════════════════════════════

CATEGORIES = ["Courses", "Logement", "Transport", None]


def operation(i: int, day: str, amount: int, category: str | None, **extra: Any) -> dict:
    kind = None if category is None else "revenu" if amount > 0 else "depense"
    return {
        "id": i, "account_id": 1, "account_name": "Compte courant",
        "category_id": None if category is None else 100 + len(category),
        "category_name": category, "category_kind": kind, "date": day, "label": f"Opération {i}",
        "amount_cents": amount, "status": "valide", "transfer_group": None,
    } | extra  # fmt: skip


def operations() -> list[dict]:
    """Trimestre fictif : 450 dépenses (4 catégories, dont « sans »), 3 salaires, 3 virements
    internes, et une dépense hors période (octobre)."""
    ops = []
    for i in range(450):
        month = ("07", "08", "09")[i % 3]
        ops.append(
            operation(i + 1, f"2026-{month}-{1 + i % 28:02d}", -(1000 + i), CATEGORIES[i % 4])
        )
    for n, month in enumerate(("07", "08", "09")):
        ops.append(operation(1000 + n, f"2026-{month}-25", 285000, "Salaire"))
        ops.append(
            operation(2000 + n, f"2026-{month}-26", -50000, "Virement interne",
                      category_kind="transfert", transfer_group=f"g{n}")
        )  # fmt: skip
    ops.append(operation(3000, "2026-10-02", -999, "Courses"))
    return ops


def is_transfer(op: dict) -> bool:
    return op["transfer_group"] is not None or op["category_kind"] == "transfert"


class FakeTresorerie:
    """Trésorerie simulée : filtres et pagination de `GET /transactions` appliqués comme
    services/transactions.py (totaux sur tout le filtre, virements exclus des revenus et
    dépenses) ; autres routes : réponses réelles enregistrées."""

    def __init__(self, *, ignore_page: bool = False) -> None:
        self.ops = operations()
        self.ignore_page = ignore_page
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = request.url.path.removeprefix("/api/")
        if name == "transactions":
            return httpx.Response(200, json=self.transactions(request.url.params))
        try:
            return httpx.Response(200, json=fixture("tresorerie", name))
        except FileNotFoundError:
            return httpx.Response(404, json={"error": "Ressource introuvable"})

    def transactions(self, params: httpx.QueryParams) -> dict:
        ops = self.ops
        kind = params.get("type")
        if kind == "expense":
            ops = [o for o in ops if o["amount_cents"] < 0 and not is_transfer(o)]
        elif kind == "income":
            ops = [o for o in ops if o["amount_cents"] > 0 and not is_transfer(o)]
        if month := params.get("month"):
            ops = [o for o in ops if o["date"][:7] == month]
        if start := params.get("start"):
            ops = [o for o in ops if o["date"] >= start]
        if end := params.get("end"):
            ops = [o for o in ops if o["date"] <= end]
        if params.get("category_id") == "none":
            ops = [o for o in ops if o["category_id"] is None]
        ops = sorted(ops, key=lambda o: (o["date"], o["id"]))
        per_page = min(200, int(params.get("per_page", 50)))
        page = 1 if self.ignore_page else int(params.get("page", 1))
        clean = [o for o in ops if not is_transfer(o)]
        return {
            "items": ops[(page - 1) * per_page : page * per_page],
            "total": len(ops),
            "page": page,
            "per_page": per_page,
            "pages": max(1, -(-len(ops) // per_page)),
            "income_cents": sum(o["amount_cents"] for o in clean if o["amount_cents"] > 0),
            "expense_cents": sum(o["amount_cents"] for o in clean if o["amount_cents"] < 0),
            "net_cents": sum(o["amount_cents"] for o in ops),
        }


def treso(fake: Any) -> dict[str, Any]:
    client = TresorerieClient("http://treso.test/api", transport=httpx.MockTransport(fake))
    return by_name(tresorerie_tools(client))


def pages_asked(fake: FakeTresorerie) -> list[str]:
    return [
        r.url.params.get("page", "") for r in fake.requests if r.url.path.endswith("/transactions")
    ]


async def test_category_totals_read_every_page_and_match_tresorerie() -> None:
    fake = FakeTresorerie()
    tool = treso(fake)["tresorerie_category_totals"]
    assert tool.sensitive and not tool.requires_approval
    assert tool.label == "Trésorerie · totaux par catégorie"

    out = await tool.invoke({"start": "2026-07-01", "end": "2026-09-30"}, ToolContext())
    assert not out.is_error, out.content
    assert pages_asked(fake) == ["1", "2", "3"]  # 450 dépenses, 200 par page
    expected: dict[str, int] = defaultdict(int)
    for op in fake.ops[:450]:
        expected[op["category_name"] or "Sans catégorie"] += -op["amount_cents"]
    total = sum(expected.values())
    assert out.content.startswith(
        f"Dépenses par catégorie (du 2026-07-01 au 2026-09-30) : 450 opération(s), total {euros(total)}"
    )
    assert f"| Logement | 113 | {expected['Logement'] / 100:g} |" in out.content
    assert "| -" not in out.content  # dépenses en valeur positive
    assert "112 opération(s) sans catégorie" in out.content
    assert "Contrôle : total identique" in out.content
    # Virements internes et opération d'octobre exclus
    assert "Virement interne" not in out.content and "Salaire" not in out.content

    assert [a.title for a in out.artifacts] == [
        "Dépenses par catégorie — du 2026-07-01 au 2026-09-30"
    ]
    assert out.data is not None and out.data["format"] == "atelier-table/1"
    assert [c["key"] for c in out.data["columns"]] == ["categorie", "operations", "total", "part"]
    assert sum(r["total"] for r in out.data["rows"]) * 100 == pytest.approx(total)
    assert out.data["truncated"] is False


async def test_category_totals_month_by_month_with_a_french_type() -> None:
    fake = FakeTresorerie()
    out = await treso(fake)["tresorerie_category_totals"].invoke(
        {"start": "2026-07-01", "end": "2026-09-30", "type": "revenus", "by_month": True},
        ToolContext(),
    )
    assert not out.is_error, out.content
    assert fake.requests[-1].url.params["type"] == "income"
    assert (
        "| catégorie | 2026-07 | 2026-08 | 2026-09 | opérations | revenus € | part % |"
        in out.content
    )
    assert "| Salaire | 2850 | 2850 | 2850 | 3 | 8550 | 100 |" in out.content
    assert "Mois par mois : 2026-07 2850.00 €, 2026-08 2850.00 €, 2026-09 2850.00 €." in out.content
    assert [c["key"] for c in out.data["columns"]][1:4] == ["c_2026_07", "c_2026_08", "c_2026_09"]


async def test_category_totals_keep_a_column_for_a_month_without_operations() -> None:
    out = await treso(FakeTresorerie())["tresorerie_category_totals"].invoke(
        {"start": "2026-07-01", "end": "2026-10-31", "type": "INCOME", "by_month": True},
        ToolContext(),
    )
    assert not out.is_error, out.content
    assert "| Salaire | 2850 | 2850 | 2850 | 0 | 3 | 8550 | 100 |" in out.content
    assert "2026-09 2850.00 €, 2026-10 0.00 €." in out.content


def test_months_between_spans_years_and_is_capped() -> None:
    assert months_between("2025-11-15", "2026-02-01") == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]
    assert len(months_between("2024-01-01", "2026-12-31")) == 13  # au-delà : pas de colonnes


async def test_category_totals_never_count_a_page_twice() -> None:
    """Service qui ignore `page` (ou pagination qui bouge) : arrêt dès qu'une page n'apporte
    rien de neuf, et totaux annoncés comme partiels au lieu d'être doublés."""
    fake = FakeTresorerie(ignore_page=True)
    out = await treso(fake)["tresorerie_category_totals"].invoke(
        {"start": "2026-07-01", "end": "2026-09-30"}, ToolContext()
    )
    assert pages_asked(fake) == ["1", "2"]
    assert "200 opération(s)" in out.content and "Attention : Trésorerie annonce 450" in out.content
    assert "Contrôle" not in out.content
    assert out.data["truncated"] is True
    # Tableau relu hors de la conversation (panneau, workflow) : partiel, et il le dit
    assert [a.title for a in out.artifacts] == [
        "Dépenses par catégorie — du 2026-07-01 au 2026-09-30 (partiel)"
    ]
    assert out.data["label"].endswith("(partiel)")


async def test_category_totals_on_an_empty_period_say_so_without_a_table() -> None:
    out = await treso(FakeTresorerie())["tresorerie_category_totals"].invoke(
        {"month": "2026-01"}, ToolContext()
    )
    assert not out.is_error, out.content
    assert "0 opération(s), total 0.00 €" in out.content
    assert "Aucune opération sur ce filtre." in out.content
    assert "Contrôle" not in out.content and "Attention" not in out.content
    assert out.artifacts == [] and out.data["rows"] == []


async def test_blank_fields_from_a_small_model_count_as_unset() -> None:
    """Un petit modèle remplit souvent tous les champs, les facultatifs avec « "" » : ils valent
    « non renseigné » (valeur par défaut) au lieu d'un refus sur le motif AAAA-MM."""
    fake = FakeTresorerie()
    tools = treso(fake)
    blanks = {"month": "", "type": " ", "account_id": "", "by_month": False}
    out = await tools["tresorerie_category_totals"].invoke(
        blanks | {"start": "2026-07-01", "end": "2026-09-30"}, ToolContext()
    )
    assert not out.is_error, out.content
    sent = fake.requests[-1].url.params
    assert sent["type"] == "expense" and "month" not in sent and "account_id" not in sent

    tx = await tools["tresorerie_transactions"].invoke(
        {"month": "2026-10", "start": "", "end": "", "type": "", "status": "", "query": ""},
        ToolContext(),
    )
    assert not tx.is_error, tx.content
    assert set(fake.requests[-1].url.params) == {"per_page", "sort", "order", "month"}


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"month": "2026-07", "start": "2026-07-01"}, "pas les deux"),
        ({"start": "2026-09-30", "end": "2026-07-01"}, "start doit précéder end"),
        ({"type": "transfer"}, "type"),
    ],
)
async def test_category_totals_reject_ambiguous_periods(params: dict, message: str) -> None:
    fake = FakeTresorerie()
    out = await treso(fake)["tresorerie_category_totals"].invoke(params, ToolContext())
    assert out.is_error and message in out.content and not fake.requests


async def test_transactions_accept_french_types_and_publish_only_partial_lists() -> None:
    fake = FakeTresorerie()
    tool = treso(fake)["tresorerie_transactions"]
    schema = tool.spec().input_schema["properties"]
    assert all(schema[k].get("description") for k in ("account_id", "type", "month", "limit"))

    full = await tool.invoke({"type": "dépense", "month": "2026-07", "limit": 200}, ToolContext())
    assert fake.requests[-1].url.params["type"] == "expense"
    assert "150 opération(s) sur ce filtre (150 renvoyées)" in full.content
    # 150 lignes, 50 montrées au modèle : liste complète dans le panneau
    assert [a.title for a in full.artifacts] == ["Opérations — 2026-07, dépenses"]

    page = await tool.invoke({"type": "expense", "month": "2026-07", "limit": 5}, ToolContext())
    assert [a.title for a in page.artifacts] == ["Opérations — 2026-07, dépenses (5 sur 150)"]

    small = await tool.invoke({"month": "2026-10"}, ToolContext())
    assert small.artifacts == []  # tout est dans la réponse : rien à publier
    assert "dépenses 9.99 €" in small.content and "| -9.99 |" in small.content

    both = await tool.invoke({"month": "2026-07", "end": "2026-07-15"}, ToolContext())
    assert both.is_error and "pas les deux" in both.content


async def test_dashboard_and_budgets_use_one_sign_convention() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.removeprefix("/api/")
        if name == "budgets":
            body = fixture("tresorerie", "budgets")
            body["items"][0] |= {"spent_cents": 3500, "remaining_cents": -500, "status": "depasse"}
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=fixture("tresorerie", name))

    tools = treso(handler)
    dash = (await tools["tresorerie_dashboard"].invoke({}, ToolContext())).content
    assert "- Dépenses du mois : 1522.35 € (en baisse de 5.3 %)." in dash
    assert "- Patrimoine net : 21821.33 € (en hausse de 7.5 %, soit +1531.67 €)" in dash
    assert "- Revenus du mois : 2850.00 € (stable)." in dash
    assert "-1522.35" not in dash and "dépenses 1834.05 €" in dash  # historique en positif

    budgets = (await tools["tresorerie_budgets"].invoke({}, ToolContext())).content
    assert "- Abonnements : 35.00 € dépensés sur 30.00 €, dépassement de 5.00 €" in budgets
    assert "reste 104.84 €" in budgets and "Dépenses hors budget" in budgets


def test_trend_and_signed_are_plain_french() -> None:
    assert trend(7.46) == "en hausse de 7.5 %" and trend(-5.3) == "en baisse de 5.3 %"
    assert trend(0.0) == "stable" and trend(None) == "sans comparaison possible"
    assert signed(153167) == "+1531.67 €" and signed(-500) == "-5.00 €"


async def test_tresorerie_stopped_or_replaced_says_how_to_fix_it() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    out = await treso(down)["tresorerie_dashboard"].invoke({}, ToolContext())
    assert out.is_error and "python app.py" in out.content and "port 5050" in out.content

    # Atelier Savoir lancé sans ATELIER_PORT=5051 : il répond 404 à tout, ping compris
    def savoir(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Ressource introuvable."})

    out = await treso(savoir)["tresorerie_budgets"].invoke({}, ToolContext())
    assert out.is_error and "ne répond pas comme Atelier Trésorerie" in out.content
    assert "ATELIER_PORT=5051" in out.content

    # Autre application qui répond à /ping sans être Trésorerie : même message
    def other(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ping"):
            return httpx.Response(200, json={"app": "atelier-savoir"})
        return httpx.Response(404, json={"error": "Ressource introuvable."})

    out = await treso(other)["tresorerie_transactions"].invoke({}, ToolContext())
    assert out.is_error and "ne répond pas comme Atelier Trésorerie" in out.content

    # Trésorerie bien là : le 404 d'origine est rendu tel quel
    def real(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ping"):
            return httpx.Response(200, json={"app": "atelier-tresorerie"})
        return httpx.Response(404, json={"error": "Mois inconnu."})

    out = await treso(real)["tresorerie_budgets"].invoke({}, ToolContext())
    assert out.is_error and out.content == "Mois inconnu."


# ═══ Atelier Savoir ═══════════════════════════════════════════════


class FakeSavoir:
    def __init__(self, chapter_text: str | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.chapter = fixture("savoir", "chapter_1")
        if chapter_text is not None:
            self.chapter |= {"content": chapter_text, "char_count": len(chapter_text)}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if method == "GET" and path == "/api/chapters/1":
            return httpx.Response(200, json=self.chapter)
        if method == "GET" and path == "/api/flashcards":
            return httpx.Response(200, json=fixture("savoir", "flashcards_course_1"))
        if method == "POST" and path == "/api/courses/1/chapters":
            chapter = fixture("savoir", "chapter_1") | {
                "id": 9,
                "title": "Notes",
                "char_count": 1234,
            }
            return httpx.Response(201, json=chapter)
        return httpx.Response(404, json={"error": "Introuvable."})


class FakeStore:
    def __init__(self, files: dict[str, tuple[str, str, bytes]]) -> None:
        self.files = files

    async def get(self, attachment_id: str) -> tuple[AttachmentInfo, bytes] | None:
        if attachment_id not in self.files:
            return None
        name, media_type, data = self.files[attachment_id]
        info = AttachmentInfo(
            id=attachment_id, name=name, media_type=media_type, kind="document", size=len(data),
            meta={}, created_at=datetime(2026, 10, 25, tzinfo=UTC),
        )  # fmt: skip
        return info, data


COURS_MD = "a" * 32
DEVIS_DOCX = "b" * 32
STORE = FakeStore(
    {
        COURS_MD: ("cours.md", "text/markdown", "# Entropie\nLe second principe…".encode()),
        DEVIS_DOCX: ("devis.docx", "application/octet-stream", b"PK\x03\x04"),
    }
)


def savoir(fake: FakeSavoir, files: ConversationFiles | None = None) -> dict[str, Any]:
    client = SavoirClient("http://savoir.test/api", transport=httpx.MockTransport(fake))
    return by_name(savoir_read_tools(client) + savoir_write_tools(client, files))


async def test_savoir_reads_are_bounded_for_a_local_model() -> None:
    tools = savoir(FakeSavoir(chapter_text="x" * 10_000))
    chapter = await tools["savoir_chapter"].invoke({"chapter_id": 1}, ToolContext())
    assert "[… 6000 caractère(s) restant(s) : rappeler avec offset=4000]" in chapter.content
    too_big = await tools["savoir_chapter"].invoke(
        {"chapter_id": 1, "max_chars": 20_000}, ToolContext()
    )
    assert too_big.is_error

    cards = await tools["savoir_flashcards"].invoke({"course_id": 1}, ToolContext())
    assert "Q : Expression du facteur de Lorentz" in cards.content
    assert "\n  R :" not in cards.content and "with_answers=true" in cards.content
    answers = await tools["savoir_flashcards"].invoke(
        {"course_id": 1, "with_answers": True}, ToolContext()
    )
    assert "R : N'échange ni énergie ni matière." in answers.content

    # Séance : questions ET réponses (pour corriger), donc 30 cartes au plus
    due = await tools["savoir_due_cards"].invoke({"limit": 31}, ToolContext())
    assert due.is_error


async def test_savoir_flashcards_go_by_batches_with_every_card_in_the_summary() -> None:
    tool = savoir(FakeSavoir())["savoir_add_flashcards"]
    card = {"question": "Q", "answer": "R", "type": "notion"}
    too_many = await tool.invoke({"chapter_id": 2, "cards": [card] * 16}, ToolContext())
    assert too_many.is_error

    params = tool.input_model.model_validate(
        {
            "chapter_id": 2,
            "cards": [
                {"question": "Énoncer le second principe", "answer": "L'entropie d'un système "
                 "isolé ne peut que croître.", "type": "theoreme"},
                {"question": "Unité de l'énergie", "answer": "Le joule (J)"},
            ],
        }
    )  # fmt: skip
    summary = tool.approval_summary(params)
    assert summary.startswith(
        "Enregistrer 2 carte(s) dans le chapitre #2 (1 théorème, 1 notion clé)"
    )
    assert (
        "1. « Énoncer le second principe » → « L'entropie d'un système isolé ne peut que" in summary
    )
    assert "2. « Unité de l'énergie » → « Le joule (J) »" in summary


async def test_savoir_review_summary_pairs_each_card_with_its_rating() -> None:
    tool = savoir(FakeSavoir())["savoir_record_reviews"]
    params = tool.input_model.model_validate(
        {"reviews": [{"card_id": 3, "rating": "correct"}, {"card_id": 5, "rating": "a_revoir"}]}
    )
    assert tool.approval_summary(params) == (
        "Enregistrer 2 révision(s) (1 Correct, 1 À revoir) : #3 → Correct, #5 → À revoir"
    )


async def test_savoir_chapter_from_text_shows_its_beginning() -> None:
    tool = savoir(FakeSavoir())["savoir_add_chapter"]
    text = "La thermodynamique étudie les échanges d'énergie. " * 20
    params = tool.input_model.model_validate({"course_id": 1, "title": "Bases", "content": text})
    summary = tool.approval_summary(params)
    assert summary.startswith(
        f"Ajouter le chapitre « Bases » au cours #1 ({len(text)} caractères) : "
    )
    assert (
        "« La thermodynamique étudie les échanges d'énergie. La" in summary and len(summary) < 300
    )

    for wrong in (
        {"course_id": 1, "title": "T"},
        {"course_id": 1, "title": "T", "content": "x", "file": "cours.md"},
        {"course_id": 1, "title": "T", "content": " ", "file": ""},  # deux sources vides
    ):
        out = await tool.invoke(wrong, ToolContext())
        assert out.is_error and "un seul des deux" in out.content


async def test_savoir_chapter_imported_from_an_attached_file() -> None:
    fake = FakeSavoir()
    tool = savoir(fake, ConversationFiles(STORE, [COURS_MD, DEVIS_DOCX]))["savoir_add_chapter"]
    params = {"course_id": 1, "title": "Notes", "file": "cours.md"}
    assert tool.approval_summary(tool.input_model.model_validate(params)) == (
        "Ajouter le chapitre « Notes » au cours #1, importé du fichier joint « cours.md » "
        "(texte extrait par Savoir)"
    )
    out = await tool.invoke(params | {"content": ""}, ToolContext())  # autre source laissée vide
    assert not out.is_error, out.content
    assert (
        out.content == "Chapitre #9 « Notes » importé de « cours.md » (1234 caractères extraits)."
    )
    sent = fake.requests[-1]
    assert sent.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="cours.md"' in sent.content and b"# Entropie" in sent.content
    assert b'name="title"\r\n\r\nNotes' in sent.content

    posts = len(fake.requests)
    docx = await tool.invoke(params | {"file": "devis.docx"}, ToolContext())
    assert docx.is_error and "ne convient pas" in docx.content and len(fake.requests) == posts
    # Extension visible : refus dès les paramètres, avant la carte de validation
    with pytest.raises(ValueError, match="ne convient pas"):
        tool.input_model.model_validate(params | {"file": "devis.docx"})
    tool.input_model.model_validate(
        params | {"file": "Chapitre 3. Intégrales"}
    )  # pas une extension
    # Nom sans extension : contrôlé une fois le fichier retrouvé, toujours sans rien envoyer
    stem = await tool.invoke(params | {"file": "devis"}, ToolContext())
    assert stem.is_error and "« devis.docx » ne convient pas" in stem.content
    assert len(fake.requests) == posts

    alone = savoir(FakeSavoir())["savoir_add_chapter"]  # hors conversation (workflow…)
    out = await alone.invoke(params, ToolContext())
    assert out.is_error and "Aucun fichier n'est joint" in out.content


async def test_savoir_write_toolset_sees_the_conversation_files() -> None:
    settings = Settings(_env_file=None, savoir_base_url="http://savoir.test/api")  # type: ignore[call-arg]
    fake = FakeSavoir()
    env = ToolEnvironment(settings, transports={"savoir": httpx.MockTransport(fake)})
    env.files = ConversationFiles(STORE, [COURS_MD])
    tool = by_name(get_toolset("savoir_write").build(env))["savoir_add_chapter"]
    out = await tool.invoke({"course_id": 1, "title": "Notes", "file": "cours"}, ToolContext())
    assert not out.is_error and "importé de « cours.md »" in out.content
    await env.aclose()


# ═══ Atelier Ciné ═════════════════════════════════════════════════


def cine(library: dict) -> dict[str, Any]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=library)

    client = CineClient("http://cine.test/api", transport=httpx.MockTransport(handler))
    return by_name(cine_read_tools(client))


async def test_cine_library_shows_and_filters_known_genres() -> None:
    lib = fixture("cine", "library")
    lib["movies"][0]["genres"] = ["Science-fiction", "Drame"]  # Orbit
    lib["shows"][0]["genres"] = ["Science-fiction"]  # Station Kepler
    tool = cine(lib)["cine_library"]
    out = await tool.invoke({}, ToolContext())
    assert "| genres |" in out.content and "Science-fiction, Drame" in out.content

    sf = await tool.invoke({"genre": "science fiction"}, ToolContext())
    assert "Orbit" in sf.content and "Station Kepler" in sf.content
    assert "Le Dernier Phare" not in sf.content and "2 titre(s)" in sf.content
    # Les titres sans genre ne sont pas « hors genre » : le modèle sait qu'il en manque
    assert "5 titre(s) sans genre renseigné écarté(s) par le filtre genre" in sf.content
    films = await tool.invoke({"genre": "drame", "kind": "movie"}, ToolContext())
    assert "1 titre(s)" in films.content and "3 titre(s) sans genre renseigné" in films.content


async def test_cine_genre_filter_is_ignored_and_said_when_cine_knows_none() -> None:
    out = await cine(fixture("cine", "library"))["cine_library"].invoke(
        {"genre": "Comédie", "kind": "movie"}, ToolContext()
    )
    assert "Filtre genre « Comédie » ignoré" in out.content and "4 titre(s)" in out.content
