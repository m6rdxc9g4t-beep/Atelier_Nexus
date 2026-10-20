"""Connecteur Atelier Ciné — médiathèque personnelle (films, séries, épisodes).

Toutes les interactions avec Atelier Ciné passent par ce module (CLAUDE.md, un module par
application). Lecture libre ; seule l'analyse des dossiers (`POST /scan`, qui réécrit
l'index) est une écriture soumise à validation. Les chemins de fichiers du NAS ou du PC
ne sont jamais transmis au modèle : seul le nom du dossier racine apparaît, au besoin.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import PurePath
from typing import Any, Literal

import httpx
from pydantic import Field

from app.core.config import Settings
from app.schemas.cine import (
    AiStatus,
    AiSummary,
    Episode,
    Health,
    Library,
    Movie,
    ScanResult,
    Show,
    ShowSummary,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import data_artifact, fmt, markdown_table, table_for_model
from app.tools.http import AppClient, AppError, AppRequestError

MEDIA_ID = r"^[ms]-[0-9a-f]{6,40}$"
SCAN_TIMEOUT = 600.0  # une analyse bloque jusqu'à la fin, longue sur un NAS
AI_TIMEOUT = 90.0  # Ciné laisse 60 s à Ollama


class CineClient(AppClient):
    app = "cine"
    label = "Atelier Ciné"
    error_keys = ("error", "detail")

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> CineClient | None:
        if not settings.cine_base_url:
            return None
        return cls(settings.cine_base_url, timeout=settings.apps_timeout, transport=transport)

    def _unavailable_hint(self) -> str:
        return "lancez-le (`npm run dev:api` dans atelier_cine) ou ouvrez l'app Mac (port 47321)."

    async def health(self) -> Health:
        try:
            return self.parse(Health, await self.request("GET", "health"))
        except AppRequestError as exc:
            raise AppRequestError(
                f"Le service sur {self.base_url} n'est pas Atelier Ciné.", app=self.app
            ) from exc

    async def library(self) -> Library:
        return self.parse(Library, await self.request("GET", "library"))

    async def show(self, show_id: str) -> Show:
        return self.parse(Show, await self.request("GET", f"library/{show_id}"))

    async def movie(self, movie_id: str) -> Movie:
        return self.parse(Movie, await self.request("GET", f"library/{movie_id}"))

    async def scan(self) -> ScanResult:
        return self.parse(ScanResult, await self.request("POST", "scan", timeout=SCAN_TIMEOUT))

    async def ai_status(self) -> AiStatus:
        return self.parse(AiStatus, await self.request("GET", "ai/status"))

    async def ai_summary(self, media_id: str) -> AiSummary:
        data = await self.request("POST", f"ai/summary/{media_id}", timeout=AI_TIMEOUT)
        return self.parse(AiSummary, data if isinstance(data, dict) else {})


# ─── Analyse (fonctions pures, testées) ───────────────────────────


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def best_quality(quality: list[str]) -> str:
    for q in ("4K Ultra HD", "1080p", "720p", "480p", "SD"):
        if q in quality:
            return q
    return "inconnue"


def missing_episodes(episodes: list[Episode]) -> dict[int, list[int]]:
    """Numéros manquants par saison, de 1 au plus grand numéro trouvé (doubles épisodes compris)."""
    seen: dict[int, set[int]] = defaultdict(set)
    for ep in episodes:
        if ep.episode is None:
            continue
        end = ep.episodeEnd if ep.episodeEnd and ep.episodeEnd >= ep.episode else ep.episode
        seen[ep.season].update(range(ep.episode, end + 1))
    gaps = {}
    for season, numbers in sorted(seen.items()):
        missing = [n for n in range(1, max(numbers) + 1) if n not in numbers]
        if missing:
            gaps[season] = missing
    return gaps


def ranges(numbers: list[int]) -> str:
    """[1, 2, 3, 5] → « 1-3, 5 »."""
    out: list[str] = []
    start = prev = numbers[0]
    for n in [*numbers[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(out)


def subtitle_langs(subs: list[Any]) -> str:
    langs = sorted({s.lang or "?" for s in subs})
    return ", ".join(langs) if langs else "aucun"


def gib(size: int) -> str:
    return f"{size / 1024**3:.1f} Go"


# ─── Outils ───────────────────────────────────────────────────────


class _CineTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)

    def __init__(self, client: CineClient) -> None:
        self.client = client


class LibraryInput(ToolInput):
    kind: Literal["all", "movie", "show"] = "all"
    search: str | None = Field(default=None, max_length=100, description="Mot du titre.")
    quality: Literal["4K", "1080p", "720p", "HDR"] | None = None
    year_from: int | None = Field(default=None, ge=1880, le=2100)
    year_to: int | None = Field(default=None, ge=1880, le=2100)
    sort: Literal["recent", "title", "year"] = "recent"


class LibraryTool(_CineTool[LibraryInput]):
    name = "cine_library"
    description = (
        "Catalogue de la médiathèque Atelier Ciné : films et séries, avec année, qualité "
        "(4K, HDR, 1080p…), durée, saisons / épisodes, sous-titres, date d'ajout. Filtres "
        "par type, titre, qualité et années."
    )
    input_model = LibraryInput

    async def run(self, params: LibraryInput, ctx: ToolContext) -> ToolOutput:
        lib = await self.client.library()
        wanted = normalize_title(params.search) if params.search else None
        quality = "4K Ultra HD" if params.quality == "4K" else params.quality
        items: list[Movie | ShowSummary] = []
        sources: list[Movie | ShowSummary] = []
        if params.kind in ("all", "movie"):
            sources += lib.movies
        if params.kind in ("all", "show"):
            sources += lib.shows
        for it in sources:
            if wanted and wanted not in normalize_title(it.title):
                continue
            if quality and quality not in it.quality:
                continue
            if params.year_from and (it.year is None or it.year < params.year_from):
                continue
            if params.year_to and (it.year is None or it.year > params.year_to):
                continue
            items.append(it)
        if params.sort == "recent":
            items.sort(key=lambda t: t.addedAt, reverse=True)
        elif params.sort == "title":
            items.sort(key=lambda t: normalize_title(t.title))
        else:
            items.sort(key=lambda t: t.year or 0, reverse=True)

        headers = [
            "id",
            "type",
            "titre",
            "année",
            "qualité",
            "durée / épisodes",
            "sous-titres",
            "ajouté le",
        ]
        rows = []
        for it in items:
            if isinstance(it, Movie):
                length = f"{it.durationMin} min" if it.durationMin else "∅"
                subs = subtitle_langs(it.subtitles)
            else:
                length = f"{it.seasons} saison(s), {it.episodes} épisode(s)"
                subs = "voir cine_title"
            rows.append([
                it.id, "film" if isinstance(it, Movie) else "série", it.title, it.year,
                ", ".join(it.quality) or "∅", length, subs, it.addedAt.date().isoformat(),
            ])  # fmt: skip
        table, truncated = table_for_model(headers, rows, noun="titre")
        head = (
            f"Médiathèque : {len(lib.movies)} film(s), {len(lib.shows)} série(s) ; "
            f"dernière analyse : {lib.scannedAt.isoformat(timespec='minutes') if lib.scannedAt else 'jamais'}"
            f"{' (analyse en cours)' if lib.scanning else ''}"
            f"{f' ; {len(lib.errors)} erreur(s) d’analyse (voir cine_library_report)' if lib.errors else ''}."
        )
        artifacts = [data_artifact("Médiathèque Atelier Ciné", headers, rows)] if truncated else []
        return ToolOutput(content=f"{head}\n{table}", artifacts=artifacts)


class TitleInput(ToolInput):
    media_id: str = Field(pattern=MEDIA_ID, description="Identifiant m-… (film) ou s-… (série).")


class TitleTool(_CineTool[TitleInput]):
    name = "cine_title"
    description = (
        "Fiche d'un film ou d'une série : qualités, sous-titres, informations techniques ; "
        "pour une série, la liste des épisodes par saison et les épisodes manquants."
    )
    input_model = TitleInput

    async def run(self, params: TitleInput, ctx: ToolContext) -> ToolOutput:
        if params.media_id.startswith("s-"):
            show = await self.client.show(params.media_id)
            lines = [
                f"Série « {show.title} »{f' ({show.year})' if show.year else ''} : "
                f"{show.seasons} saison(s), {show.episodes} épisode(s), qualité "
                f"{', '.join(show.quality) or 'inconnue'}.",
            ]
            by_season: dict[int, list[Episode]] = defaultdict(list)
            for ep in show.episodeList:
                by_season[ep.season].append(ep)
            for season, eps in sorted(by_season.items()):
                lines.append(f"\nSaison {season} :")
                for ep in eps:
                    num = "?" if ep.episode is None else f"{ep.episode:02d}"
                    if ep.episodeEnd:
                        num += f"-{ep.episodeEnd:02d}"
                    lines.append(
                        f"- E{num} {ep.title or ''} [{', '.join(ep.quality) or 'qualité ?'}] "
                        f"sous-titres : {subtitle_langs(ep.subtitles)} ({ep.id})".replace("  ", " ")
                    )
            gaps = missing_episodes(show.episodeList)
            if gaps:
                lines.append("\nÉpisodes manquants (d'après la numérotation) :")
                lines += [f"- Saison {s} : {ranges(n)}" for s, n in gaps.items()]
            if not show.synopsis:
                lines.append("\nPas de synopsis : `cine_ai_summary` peut en proposer un.")
            return ToolOutput(content="\n".join(lines))

        movie = await self.client.movie(params.media_id)
        tech = movie.tech or {}
        details = [
            f"Film « {movie.title} »{f' ({movie.year})' if movie.year else ''}.",
            f"- Qualité : {', '.join(movie.quality) or 'inconnue'}",
            f"- Durée : {f'{movie.durationMin} min' if movie.durationMin else 'inconnue (analyse ffprobe désactivée)'}",
            f"- Taille : {gib(movie.sizeBytes)}",
            f"- Sous-titres : {', '.join(f'{s.lang or "?"} ({s.format})' for s in movie.subtitles) or 'aucun'}",
            f"- Ajouté le : {movie.addedAt.date().isoformat()}",
            f"- Fichier : {PurePath(movie.path).name}",
        ]
        if tech:
            audio = ", ".join(
                f"{a.get('lang') or '?'} {a.get('codec') or ''} {a.get('channels') or ''}ch".strip()
                for a in tech.get("audio", [])
            )
            details.append(
                f"- Technique : {tech.get('container')}, vidéo {tech.get('videoCodec')} "
                f"{tech.get('width')}×{tech.get('height')}, audio {audio or '∅'}"
            )
        details.append(f"- Genres : {', '.join(movie.genres) or 'non renseignés'}")
        details.append(f"- Synopsis : {movie.synopsis or 'aucun (voir cine_ai_summary)'}")
        return ToolOutput(content="\n".join(details))


class ReportInput(ToolInput):
    pass


class ReportTool(_CineTool[ReportInput]):
    name = "cine_library_report"
    description = (
        "Bilan de santé de la médiathèque : erreurs d'analyse (NAS déconnecté…), épisodes "
        "manquants, doublons probables, titres sans année, répartition des qualités, "
        "sous-titres, volume total."
    )
    input_model = ReportInput

    async def run(self, params: ReportInput, ctx: ToolContext) -> ToolOutput:
        lib = await self.client.library()
        lines = [
            f"Médiathèque : {len(lib.movies)} film(s), {len(lib.shows)} série(s), "
            f"{sum(s.episodes for s in lib.shows)} épisode(s), "
            f"{gib(sum(m.sizeBytes for m in lib.movies))} de films.",
            f"Dernière analyse : {lib.scannedAt.isoformat(timespec='minutes') if lib.scannedAt else 'jamais'}.",
        ]
        if lib.errors:
            lines.append(f"\n{len(lib.errors)} erreur(s) d'analyse :")
            lines += [
                f"- {PurePath(e.path).name or e.path} : {e.code or ''} {e.message}".replace(
                    "  ", " "
                )
                for e in lib.errors[:20]
            ]

        quality = Counter(best_quality(m.quality) for m in lib.movies)
        lines.append(
            "\nQualité des films : " + ", ".join(f"{q} {n}" for q, n in quality.most_common())
            if lib.movies
            else "\nAucun film."
        )
        hdr = sum("HDR" in m.quality for m in lib.movies)
        if hdr:
            lines.append(f"Films HDR : {hdr}.")

        no_year = [m.title for m in lib.movies if m.year is None]
        if no_year:
            lines.append(f"\nFilms sans année (titre mal reconnu ?) : {', '.join(no_year)}.")
        no_subs = [m.title for m in lib.movies if not m.subtitles]
        if no_subs:
            lines.append(f"Films sans sous-titres : {len(no_subs)} ({', '.join(no_subs[:10])}).")

        groups: dict[tuple[str, int | None], list[str]] = defaultdict(list)
        for m in lib.movies:
            groups[(normalize_title(m.title), m.year)].append(
                f"{m.title} [{', '.join(m.quality) or '?'}]"
            )
        dupes = [v for v in groups.values() if len(v) > 1]
        if dupes:
            lines.append("\nDoublons probables :")
            lines += [f"- {' / '.join(v)}" for v in dupes]

        # Épisodes manquants : une requête par série (la liste n'a pas le détail des épisodes)
        gaps_rows = []
        for summary in lib.shows[:100]:
            show = await self.client.show(summary.id)
            for season, missing in missing_episodes(show.episodeList).items():
                gaps_rows.append([show.title, season, ranges(missing), len(missing)])
        if gaps_rows:
            lines.append("\nÉpisodes manquants (d'après la numérotation) :")
            lines.append(
                markdown_table(["série", "saison", "épisodes manquants", "nombre"], gaps_rows)
            )
        elif lib.shows:
            lines.append("\nAucun trou dans la numérotation des épisodes.")
        return ToolOutput(content="\n".join(lines))


class AiSummaryTool(_CineTool[TitleInput]):
    name = "cine_ai_summary"
    description = (
        "Demande à Atelier Ciné (via son Ollama local) un synopsis, des genres et des tags "
        "pour un film ou une série. Rien n'est enregistré dans Ciné. Peut prendre une minute."
    )
    input_model = TitleInput

    async def run(self, params: TitleInput, ctx: ToolContext) -> ToolOutput:
        summary = await self.client.ai_summary(params.media_id)
        return ToolOutput(
            content=(
                f"Synopsis proposé : {summary.synopsis or '∅'}\n"
                f"Genres : {', '.join(summary.genres) or '∅'}\n"
                f"Tags : {', '.join(summary.tags) or '∅'}\n"
                "(Généré par le modèle local de Ciné à partir du titre seul : à vérifier.)"
            )
        )


class ScanTool(_CineTool[ReportInput]):
    name = "cine_scan"
    description = (
        "Relance l'analyse des dossiers de films et séries et réécrit l'index de Ciné "
        "(nouveaux fichiers, fichiers supprimés). Action soumise à validation ; peut durer "
        "plusieurs minutes sur un NAS."
    )
    input_model = ReportInput
    requires_approval = True

    def approval_summary(self, params: ReportInput) -> str:
        return "Relancer l'analyse de la médiathèque Atelier Ciné (l'index sera réécrit)"

    async def run(self, params: ReportInput, ctx: ToolContext) -> ToolOutput:
        result = await self.client.scan()
        c = result.counts
        text = (
            f"Analyse terminée en {fmt(result.durationMs / 1000)} s : {c.movies} film(s), "
            f"{c.shows} série(s), {c.episodes} épisode(s)."
        )
        if result.errors:
            text += f" {len(result.errors)} erreur(s) : " + "; ".join(
                f"{PurePath(e.path).name} ({e.message})" for e in result.errors[:5]
            )
        return ToolOutput(content=text)


def cine_read_tools(client: CineClient) -> list[BaseTool[Any]]:
    return [LibraryTool(client), TitleTool(client), ReportTool(client), AiSummaryTool(client)]


def cine_write_tools(client: CineClient) -> list[BaseTool[Any]]:
    return [ScanTool(client)]
