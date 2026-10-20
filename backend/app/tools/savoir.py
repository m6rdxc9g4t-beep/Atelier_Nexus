"""Connecteur Atelier Savoir — cours, chapitres et cartes de révision (répétition espacée).

Règle d'Atelier Savoir : « 100 % local par défaut ». Les cours et notes de l'utilisateur
sont des données personnelles : tous ces outils sont `sensitive`, l'agent qui les utilise
est verrouillé sur le modèle local (Ollama), sans repli vers Claude.

On n'appelle jamais `POST /chapters/{id}/generate` (génération par le moteur IA de Savoir,
qui peut être Claude selon ses réglages) : l'agent rédige lui-même les cartes avec le modèle
local, puis les enregistre avec `savoir_add_flashcards`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import Settings
from app.schemas.savoir import (
    CARD_TYPE_LABELS,
    RATING_LABELS,
    STATUS_LABELS,
    CardsCreate,
    CardStatus,
    CardType,
    Chapter,
    ChapterCreate,
    Course,
    CourseCreate,
    CourseDetail,
    CreatedCards,
    Flashcard,
    NewCard,
    Rating,
    Review,
    Stats,
    StudySession,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import markdown_table
from app.tools.http import AppClient, AppError, AppRequestError, safe_id

MAX_CARD_TEXT = 400


class SavoirClient(AppClient):
    app = "savoir"
    label = "Atelier Savoir"
    error_keys = ("error",)

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> SavoirClient | None:
        if not settings.savoir_base_url:
            return None
        return cls(settings.savoir_base_url, timeout=settings.apps_timeout, transport=transport)

    def _unavailable_hint(self) -> str:
        return "lancez-le avec `ATELIER_PORT=5051 python app.py` (5050 est pris par Trésorerie)."

    async def stats(self) -> Stats:
        try:
            return self.parse(Stats, await self.request("GET", "stats"))
        except AppError as exc:
            if isinstance(exc, AppRequestError) or "introuvable" in str(exc).lower():
                raise AppRequestError(
                    f"Le service sur {self.base_url} n'est pas Atelier Savoir "
                    "(Trésorerie occupe peut-être son port).",
                    app=self.app,
                ) from exc
            raise

    async def courses(self) -> list[Course]:
        return self.parse_list(Course, await self.request("GET", "courses"))

    async def course(self, course_id: int) -> CourseDetail:
        return self.parse(CourseDetail, await self.request("GET", f"courses/{safe_id(course_id)}"))

    async def chapter(self, chapter_id: int) -> Chapter:
        return self.parse(Chapter, await self.request("GET", f"chapters/{safe_id(chapter_id)}"))

    async def flashcards(
        self, course_id: int | None = None, chapter_id: int | None = None
    ) -> list[Flashcard]:
        params = {}
        if course_id is not None:
            params["course_id"] = safe_id(course_id)
        if chapter_id is not None:
            params["chapter_id"] = safe_id(chapter_id)
        return self.parse_list(Flashcard, await self.request("GET", "flashcards", params=params))

    async def study_session(
        self, course_id: int | None, mode: Literal["dues", "toutes"], limit: int
    ) -> StudySession:
        params: dict[str, Any] = {"mode": mode, "limit": limit}
        if course_id is not None:
            params["course_id"] = safe_id(course_id)
        return self.parse(StudySession, await self.request("GET", "study/session", params=params))

    async def create_course(self, body: CourseCreate) -> Course:
        return self.parse(
            Course, await self.request("POST", "courses", json_body=body.model_dump())
        )

    async def add_chapter(self, course_id: int, body: ChapterCreate) -> Chapter:
        data = await self.request(
            "POST", f"courses/{safe_id(course_id)}/chapters", json_body=body.model_dump()
        )
        return self.parse(Chapter, data)

    async def add_cards(self, body: CardsCreate) -> CreatedCards:
        data = await self.request(
            "POST", "flashcards", json_body=body.model_dump(exclude_none=True)
        )
        return self.parse(CreatedCards, data)

    async def review(self, card_id: int, body: Review) -> Flashcard:
        data = await self.request(
            "POST", f"flashcards/{safe_id(card_id)}/review", json_body=body.model_dump()
        )
        return self.parse(Flashcard, data)


def clip(text: str, limit: int = MAX_CARD_TEXT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def card_line(card: Flashcard, *, with_answer: bool = True) -> str:
    where = card.chapter_title or card.course_title
    head = (
        f"- #{card.id} [{CARD_TYPE_LABELS[card.card_type]}, {STATUS_LABELS[card.status]}, "
        f"{where}, échéance {card.due_at:%Y-%m-%d %H:%M} UTC]"
    )
    line = f"{head}\n  Q : {clip(card.question)}"
    if with_answer:
        line += f"\n  R : {clip(card.answer)}"
    return line


# ─── Outils ───────────────────────────────────────────────────────


class _SavoirTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)
    sensitive = True

    def __init__(self, client: SavoirClient) -> None:
        self.client = client


class NoInput(ToolInput):
    pass


class OverviewTool(_SavoirTool[NoInput]):
    name = "savoir_overview"
    description = (
        "Vue d'ensemble d'Atelier Savoir : nombre de cours, chapitres et cartes, cartes "
        "maîtrisées, nouvelles, à réviser aujourd'hui, révisions faites aujourd'hui, et la "
        "liste des cours avec leurs compteurs."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        st = await self.client.stats()
        courses = await self.client.courses()
        lines = [
            f"{st.courses} cours, {st.chapters} chapitre(s), {st.cards} carte(s) dont "
            f"{st.mastered} maîtrisée(s) et {st.new_cards} nouvelle(s).",
            f"À réviser maintenant : {st.due} carte(s) (nouvelles comprises). "
            f"Révisions faites aujourd'hui : {st.reviewed_today}.",
        ]
        if courses:
            rows = [
                [c.id, c.title, c.subject or "∅", c.chapter_count, c.card_count, c.mastered_count,
                 c.due_count, f"{c.updated_at:%Y-%m-%d}"]
                for c in courses
            ]  # fmt: skip
            lines.append(
                markdown_table(
                    [
                        "id",
                        "cours",
                        "matière",
                        "chapitres",
                        "cartes",
                        "maîtrisées",
                        "à réviser",
                        "modifié le",
                    ],
                    rows,
                )
            )
        return ToolOutput(content="\n".join(lines))


class CourseInput(ToolInput):
    course_id: int = Field(gt=0)


class CourseTool(_SavoirTool[CourseInput]):
    name = "savoir_course"
    description = "Un cours et ses chapitres (source, taille du texte, nombre de cartes)."
    input_model = CourseInput

    async def run(self, params: CourseInput, ctx: ToolContext) -> ToolOutput:
        c = await self.client.course(params.course_id)
        rows = [
            [
                ch.id,
                ch.position + 1,
                ch.title,
                ch.source_filename or ch.source_type,
                ch.char_count,
                ch.card_count,
            ]
            for ch in c.chapters
        ]
        text = (
            f"Cours #{c.id} « {c.title} » ({c.subject or 'sans matière'}) : {c.card_count} carte(s), "
            f"{c.mastered_count} maîtrisée(s), {c.due_count} à réviser."
        )
        if c.description:
            text += f"\nDescription : {c.description}"
        if rows:
            text += "\n" + markdown_table(
                ["id", "n°", "chapitre", "source", "caractères", "cartes"], rows
            )
        else:
            text += "\nAucun chapitre."
        return ToolOutput(content=text)


class ChapterInput(ToolInput):
    chapter_id: int = Field(gt=0)
    offset: int = Field(default=0, ge=0, description="Début de l'extrait, en caractères.")
    max_chars: int = Field(default=8000, ge=500, le=20000)


class ChapterTool(_SavoirTool[ChapterInput]):
    name = "savoir_chapter"
    description = (
        "Texte d'un chapitre (extrait de `max_chars` caractères à partir de `offset`) : pour "
        "expliquer une notion ou rédiger des cartes. Le texte peut contenir du LaTeX ($…$)."
    )
    input_model = ChapterInput

    async def run(self, params: ChapterInput, ctx: ToolContext) -> ToolOutput:
        ch = await self.client.chapter(params.chapter_id)
        end = params.offset + params.max_chars
        part = ch.content[params.offset : end]
        more = (
            f"\n[… {len(ch.content) - end} caractère(s) restant(s) : rappeler avec offset={end}]"
            if end < len(ch.content)
            else ""
        )
        return ToolOutput(
            content=(
                f"Chapitre #{ch.id} « {ch.title} » (cours #{ch.course_id}, {ch.card_count} carte(s), "
                f"{len(ch.content)} caractères) :\n\n{part}{more}"
            )
        )


class FlashcardsInput(ToolInput):
    course_id: int | None = Field(default=None, gt=0)
    chapter_id: int | None = Field(default=None, gt=0)
    status: CardStatus | None = None
    card_type: CardType | None = None
    limit: int = Field(default=60, ge=1, le=200)


class FlashcardsTool(_SavoirTool[FlashcardsInput]):
    name = "savoir_flashcards"
    description = (
        "Cartes de révision (question, réponse, type, statut, échéance), filtrées par cours, "
        "chapitre, statut ou type. Utile pour éviter les doublons avant d'en ajouter."
    )
    input_model = FlashcardsInput

    async def run(self, params: FlashcardsInput, ctx: ToolContext) -> ToolOutput:
        cards = await self.client.flashcards(params.course_id, params.chapter_id)
        if params.status:
            cards = [c for c in cards if c.status == params.status]
        if params.card_type:
            cards = [c for c in cards if c.card_type == params.card_type]
        status = Counter(STATUS_LABELS[c.status] for c in cards)
        head = f"{len(cards)} carte(s)" + (
            " : " + ", ".join(f"{s.lower()} {n}" for s, n in status.most_common()) if cards else ""
        )
        shown = cards[: params.limit]
        lines = [head + ("." if len(shown) == len(cards) else f" ; {len(shown)} premières.")]
        lines += [card_line(c) for c in shown]
        return ToolOutput(content="\n".join(lines))


class DueInput(ToolInput):
    course_id: int | None = Field(default=None, gt=0)
    mode: Literal["dues", "toutes"] = Field(
        default="dues",
        description="dues : cartes à réviser maintenant ; toutes : tirage au hasard.",
    )
    limit: int = Field(default=10, ge=1, le=50)


class DueCardsTool(_SavoirTool[DueInput]):
    name = "savoir_due_cards"
    description = (
        "Cartes à réviser maintenant (déjà étudiées d'abord, puis nouvelles), comme une séance "
        "d'Atelier Savoir. Pour une interrogation : pose les questions une par une sans "
        "montrer les réponses."
    )
    input_model = DueInput

    async def run(self, params: DueInput, ctx: ToolContext) -> ToolOutput:
        session = await self.client.study_session(params.course_id, params.mode, params.limit)
        if not session.cards:
            return ToolOutput(content="Aucune carte à réviser pour le moment.")
        lines = [
            f"{len(session.cards)} carte(s) pour la séance ({session.mode}). "
            "Réponses réservées à ta correction : ne les montre qu'après la réponse de l'utilisateur."
        ]
        lines += [card_line(c) for c in session.cards]
        return ToolOutput(content="\n".join(lines))


# ─── Écritures (validation) ───────────────────────────────────────


class CreateCourseInput(ToolInput):
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)


class CreateCourseTool(_SavoirTool[CreateCourseInput]):
    name = "savoir_create_course"
    description = "Crée un cours dans Atelier Savoir. Action soumise à validation."
    input_model = CreateCourseInput
    requires_approval = True

    def approval_summary(self, params: CreateCourseInput) -> str:
        return f"Créer le cours « {params.title} »" + (
            f" ({params.subject})" if params.subject else ""
        )

    async def run(self, params: CreateCourseInput, ctx: ToolContext) -> ToolOutput:
        course = await self.client.create_course(CourseCreate(**params.model_dump()))
        return ToolOutput(content=f"Cours #{course.id} « {course.title} » créé.")


class AddChapterInput(ToolInput):
    course_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(
        min_length=1, max_length=200_000, description="Texte du chapitre (Markdown, LaTeX)."
    )


class AddChapterTool(_SavoirTool[AddChapterInput]):
    name = "savoir_add_chapter"
    description = (
        "Ajoute un chapitre (texte collé ou rédigé : fiche de synthèse, notes de cours) à un "
        "cours. Action soumise à validation."
    )
    input_model = AddChapterInput
    requires_approval = True

    def approval_summary(self, params: AddChapterInput) -> str:
        return (
            f"Ajouter le chapitre « {params.title} » ({len(params.content)} caractères) "
            f"au cours #{params.course_id}"
        )

    async def run(self, params: AddChapterInput, ctx: ToolContext) -> ToolOutput:
        ch = await self.client.add_chapter(
            params.course_id, ChapterCreate(title=params.title, content=params.content)
        )
        return ToolOutput(
            content=f"Chapitre #{ch.id} « {ch.title} » ajouté ({ch.char_count} caractères)."
        )


class AddCardsInput(ToolInput):
    chapter_id: int | None = Field(default=None, gt=0, description="Chapitre visé (prioritaire).")
    course_id: int | None = Field(
        default=None, gt=0, description="Cours, si la carte n'a pas de chapitre."
    )
    cards: list[NewCard] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _target(self) -> AddCardsInput:
        if self.chapter_id is None and self.course_id is None:
            raise ValueError("Indique chapter_id ou course_id.")
        return self


class AddCardsTool(_SavoirTool[AddCardsInput]):
    name = "savoir_add_flashcards"
    description = (
        "Enregistre des cartes de révision (question, réponse, type : notion, definition, "
        "formule, theoreme) dans un chapitre ou un cours, marquées « générées par IA ». "
        "Action soumise à validation."
    )
    input_model = AddCardsInput
    requires_approval = True

    def approval_summary(self, params: AddCardsInput) -> str:
        target = (
            f"le chapitre #{params.chapter_id}"
            if params.chapter_id
            else f"le cours #{params.course_id}"
        )
        kinds = Counter(CARD_TYPE_LABELS[c.type].lower() for c in params.cards)
        detail = ", ".join(f"{n} {k}" for k, n in kinds.most_common())
        first = clip(params.cards[0].question, 80)
        return (
            f"Enregistrer {len(params.cards)} carte(s) dans {target} ({detail}), dont « {first} »"
        )

    async def run(self, params: AddCardsInput, ctx: ToolContext) -> ToolOutput:
        created = await self.client.add_cards(
            CardsCreate(
                chapter_id=params.chapter_id,
                course_id=params.course_id,
                origin="ia",
                cards=params.cards,
            )
        )
        skipped = len(params.cards) - created.created
        text = (
            f"{created.created} carte(s) enregistrée(s) : "
            + ", ".join(f"#{c.id}" for c in created.cards)
            + "."
        )
        if skipped:
            text += f" {skipped} carte(s) écartée(s) par Savoir (question ou réponse vide)."
        return ToolOutput(content=text)


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: int = Field(gt=0)
    rating: Rating


class RecordReviewsInput(ToolInput):
    reviews: list[ReviewItem] = Field(min_length=1, max_length=50)


class RecordReviewsTool(_SavoirTool[RecordReviewsInput]):
    name = "savoir_record_reviews"
    description = (
        "Enregistre les résultats d'une interrogation dans Atelier Savoir (répétition espacée) : "
        "a_revoir, correct ou maitrise par carte. Une seule validation pour toute la séance."
    )
    input_model = RecordReviewsInput
    requires_approval = True

    def approval_summary(self, params: RecordReviewsInput) -> str:
        counts = Counter(RATING_LABELS[r.rating] for r in params.reviews)
        detail = ", ".join(f"{n} {label}" for label, n in counts.most_common())
        ids = ", ".join(f"#{r.card_id}" for r in params.reviews[:10])
        return f"Enregistrer {len(params.reviews)} révision(s) ({detail}) sur les cartes {ids}"

    async def run(self, params: RecordReviewsInput, ctx: ToolContext) -> ToolOutput:
        done: list[str] = []
        failed: list[str] = []
        for item in params.reviews:
            try:
                card = await self.client.review(item.card_id, Review(rating=item.rating))
            except AppError as exc:
                failed.append(f"#{item.card_id} ({exc})")
                continue
            done.append(
                f"#{card.id} → {STATUS_LABELS[card.status]}, prochaine révision le {card.due_at:%Y-%m-%d}"
            )
        lines = [f"{len(done)} révision(s) enregistrée(s) :"] + [f"- {d}" for d in done]
        if failed:
            lines.append(f"{len(failed)} échec(s) : " + "; ".join(failed))
        return ToolOutput(content="\n".join(lines), is_error=not done)


def savoir_read_tools(client: SavoirClient) -> list[BaseTool[Any]]:
    return [
        OverviewTool(client),
        CourseTool(client),
        ChapterTool(client),
        FlashcardsTool(client),
        DueCardsTool(client),
    ]


def savoir_write_tools(client: SavoirClient) -> list[BaseTool[Any]]:
    return [
        CreateCourseTool(client),
        AddChapterTool(client),
        AddCardsTool(client),
        RecordReviewsTool(client),
    ]
