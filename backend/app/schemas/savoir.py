"""Schémas de l'API d'Atelier Savoir (`http://127.0.0.1:5051/api`, Flask + SQLite).

Contrat lu dans le dépôt `atelier-savoir` (routes/api.py, models.py) puis vérifié contre
l'application lancée sur des données de démonstration. Clés en snake_case anglais,
valeurs d'énumération en français, dates « AAAA-MM-JJ HH:MM:SS » en UTC sans fuseau.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

CardType = Literal["notion", "definition", "formule", "theoreme"]
CardStatus = Literal["nouvelle", "a_revoir", "en_cours", "maitrisee"]
Rating = Literal["a_revoir", "correct", "maitrise"]
SourceType = Literal["texte", "md", "txt", "pdf"]

CARD_TYPE_LABELS: dict[str, str] = {
    "notion": "Notion clé",
    "definition": "Définition",
    "formule": "Formule",
    "theoreme": "Théorème",
}
STATUS_LABELS: dict[str, str] = {
    "nouvelle": "Nouvelle",
    "a_revoir": "À revoir",
    "en_cours": "En cours",
    "maitrisee": "Maîtrisée",
}
RATING_LABELS: dict[str, str] = {
    "a_revoir": "À revoir",
    "correct": "Correct",
    "maitrise": "Maîtrisé",
}


def _savoir_datetime(value: object) -> object:
    """« 2026-10-20 10:05:43 » (UTC implicite) → datetime avec fuseau."""
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return value  # laissé à Pydantic (format ISO éventuel)
    return value


SavoirDateTime = Annotated[datetime, BeforeValidator(_savoir_datetime)]


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Stats(_R):
    """`/api/stats` : sert aussi de contrôle d'identité (clés propres à Savoir)."""

    courses: int
    chapters: int
    cards: int
    mastered: int
    new_cards: int
    due: int
    reviewed_today: int


class Course(_R):
    id: int
    title: str
    subject: str = ""
    description: str = ""
    created_at: SavoirDateTime
    updated_at: SavoirDateTime
    chapter_count: int = 0
    card_count: int = 0
    mastered_count: int = 0
    #: Cartes à revoir, nouvelles comprises
    due_count: int = 0


class ChapterSummary(_R):
    id: int
    course_id: int
    title: str
    source_type: SourceType
    source_filename: str | None = None
    position: int = 0
    created_at: SavoirDateTime
    char_count: int = 0
    card_count: int = 0


class CourseDetail(Course):
    chapters: list[ChapterSummary] = Field(default_factory=list)


class Chapter(ChapterSummary):
    content: str = ""


class Flashcard(_R):
    id: int
    course_id: int
    chapter_id: int | None = None
    question: str
    answer: str
    card_type: CardType
    origin: Literal["ia", "manuel"]
    ease: float
    interval_days: float
    repetitions: int
    status: CardStatus
    due_at: SavoirDateTime
    last_reviewed_at: SavoirDateTime | None = None
    created_at: SavoirDateTime
    course_title: str = ""
    chapter_title: str | None = None


class StudySession(_R):
    mode: str
    cards: list[Flashcard]


class CreatedCards(_R):
    created: int
    cards: list[Flashcard]


# ─── Corps de requête (stricts) ──────────────────────────────────


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseCreate(_Body):
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)


class ChapterCreate(_Body):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)


class NewCard(_Body):
    """Carte proposée : la clé est `type` (et non `card_type` comme une carte enregistrée)."""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=4000)
    type: CardType = "notion"


class CardsCreate(_Body):
    chapter_id: int | None = None
    course_id: int | None = None
    origin: Literal["ia", "manuel"] = "ia"
    cards: list[NewCard] = Field(min_length=1, max_length=60)


class Review(_Body):
    rating: Rating
