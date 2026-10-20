"""Schémas de l'API d'Atelier Ciné (`http://127.0.0.1:4000/api`, Express).

Contrat lu dans le dépôt `atelier_cine` (backend/src/routes, services/scanner.js) puis
vérifié contre l'application lancée avec sa médiathèque d'exemple. Champs en camelCase,
exactement comme sur le fil. Réponses : champs inconnus ignorés.

Confidentialité : chaque titre porte le chemin absolu du fichier (`path`). Les outils ne
le transmettent jamais au modèle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Subtitle(_R):
    lang: str | None = None
    format: str


class MediaDirs(_R):
    movies: list[str] = Field(default_factory=list)
    shows: list[str] = Field(default_factory=list)


class Health(_R):
    ok: bool
    version: str
    runtime: str
    mediaDirs: MediaDirs
    #: Présent uniquement chez Atelier Ciné : sert à vérifier l'identité du service
    mediaDirsSource: Literal["settings", "env", "default"]


class Movie(_R):
    id: str
    type: Literal["movie"]
    title: str
    year: int | None = None
    quality: list[str] = Field(default_factory=list)
    durationMin: int | None = None
    genres: list[str] = Field(default_factory=list)
    synopsis: str | None = None
    addedAt: datetime
    sizeBytes: int = 0
    path: str
    subtitles: list[Subtitle] = Field(default_factory=list)
    tech: dict[str, Any] | None = None


class Episode(_R):
    id: str
    season: int = 1
    episode: int | None = None
    episodeEnd: int | None = None
    title: str | None = None
    quality: list[str] = Field(default_factory=list)
    sizeBytes: int = 0
    addedAt: datetime
    path: str
    subtitles: list[Subtitle] = Field(default_factory=list)


class ShowSummary(_R):
    id: str
    type: Literal["show"]
    title: str
    year: int | None = None
    quality: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    synopsis: str | None = None
    addedAt: datetime
    path: str
    seasons: int = 0
    episodes: int = 0


class Show(ShowSummary):
    episodeList: list[Episode] = Field(default_factory=list)


class ScanError(_R):
    path: str
    code: str | None = None
    message: str


class Library(_R):
    scannedAt: datetime | None = None
    featuredId: str | None = None
    movies: list[Movie] = Field(default_factory=list)
    shows: list[ShowSummary] = Field(default_factory=list)
    errors: list[ScanError] = Field(default_factory=list)
    scanning: bool = False


class ScanCounts(_R):
    movies: int
    shows: int
    episodes: int


class ScanResult(_R):
    durationMs: int
    counts: ScanCounts
    errors: list[ScanError] = Field(default_factory=list)


class AiStatus(_R):
    available: bool
    model: str | None = None
    modelInstalled: bool | None = None
    error: str | None = None


class AiSummary(_R):
    """Sortie d'Ollama relayée telle quelle par Ciné : on la tolère imparfaite."""

    synopsis: str | None = None
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("synopsis", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return value if value is None or isinstance(value, str) else str(value)

    @field_validator("genres", "tags", mode="before")
    @classmethod
    def _words(cls, value: object) -> list[str]:
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:12]
