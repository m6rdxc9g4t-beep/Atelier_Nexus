"""Outils système génériques, utilisables par tous les agents."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.clock import DEFAULT_TIMEZONE, local_now

# Noms français écrits en dur : `%A` / `%B` dépendent de la locale du processus (anglais par
# défaut, « Sunday »), et `setlocale` est global, non garanti sur la machine et pas thread-safe.
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def french_date(day: date) -> str:
    """« dimanche 25 octobre 2026 », « jeudi 1er janvier 2026 » (sans dépendre de la locale)."""
    number = "1er" if day.day == 1 else str(day.day)
    return f"{JOURS[day.weekday()]} {number} {MOIS[day.month - 1]} {day.year}"


def now_in(tz: ZoneInfo) -> datetime:
    """Heure courante dans un fuseau, par l'horloge commune des outils (`app/tools/clock.py`,
    remplacée dans les tests pour figer la date)."""
    return local_now(tz)


class CurrentDateTimeInput(ToolInput):
    timezone: str = Field(
        default="",
        max_length=64,
        description="Fuseau horaire IANA, par ex. America/New_York ; vide = fuseau de "
        "l'utilisateur (réglage TIMEZONE).",
    )


class CurrentDateTimeTool(BaseTool[CurrentDateTimeInput]):
    name = "current_datetime"
    description = (
        "Renvoie la date et l'heure actuelles dans le fuseau de l'utilisateur (ou un fuseau "
        "donné), avec le jour de la semaine et le mois en toutes lettres. "
        "À utiliser pour tout calcul relatif à aujourd'hui (périodes, échéances)."
    )
    input_model = CurrentDateTimeInput

    def __init__(self, timezone: str = DEFAULT_TIMEZONE) -> None:
        #: Fuseau de l'utilisateur (`TIMEZONE`), pris quand le modèle n'en donne pas : le même
        #: « aujourd'hui » que les contrôles d'échéance de Tab et de Projets
        self.timezone = timezone

    async def run(self, params: CurrentDateTimeInput, ctx: ToolContext) -> ToolOutput:
        name = params.timezone.strip() or self.timezone
        try:
            tz = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ToolOutput(content=f"Fuseau inconnu : {name}", is_error=True)
        now = now_in(tz)
        return ToolOutput(
            content=f"{now.isoformat(timespec='seconds')} ({french_date(now)}, {now:%H:%M}, {tz.key})"
        )
