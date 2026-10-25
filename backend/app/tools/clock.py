"""« Aujourd'hui » pour les outils : une seule définition, dans le fuseau `TIMEZONE` des réglages.

Les échéances (`tab_check_table`, jalons et retards d'Atelier Projets) et l'heure donnée par
`current_datetime` se jugent sur le jour de l'utilisateur, ni sur celui d'UTC ni sur l'horloge de
la machine (un conteneur Docker tourne souvent en UTC) : entre minuit et 2 h à Paris, la date UTC
est encore celle de la veille.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Fuseau par défaut, le même que `Settings.timezone`
DEFAULT_TIMEZONE = "Europe/Paris"


def now_utc() -> datetime:
    """Instant présent (remplacé dans les tests pour figer l'horloge)."""
    return datetime.now(UTC)


def zone(timezone: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    """Fuseau IANA ; un nom inconnu donne Europe/Paris (le réglage `TIMEZONE` est déjà validé au
    chargement : ce repli ne sert qu'à un client construit à la main)."""
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_now(
    timezone: str | ZoneInfo = DEFAULT_TIMEZONE, *, now: datetime | None = None
) -> datetime:
    """Heure dans `timezone` (nom IANA ou fuseau). `now` : instant de référence, une date naïve
    étant lue comme UTC (dates relues de SQLite)."""
    tz = timezone if isinstance(timezone, ZoneInfo) else zone(timezone)
    instant = now or now_utc()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(tz)


def local_today(timezone: str = DEFAULT_TIMEZONE, *, now: datetime | None = None) -> date:
    """Date du jour dans `timezone` (nom IANA ; inconnu → Europe/Paris)."""
    return local_now(timezone, now=now).date()
