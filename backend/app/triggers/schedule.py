"""Horaires des déclencheurs : prochaine occurrence et rattrapage (fonctions pures).

- `interval` : toutes les N minutes, cadence ancrée sur la première occurrence.
- `daily` : à `HH:MM` dans le fuseau `settings.timezone`, les jours choisis. Les changements
  d'heure sont gérés par `zoneinfo` : une heure qui n'existe pas (passage à l'heure d'été) est
  lue avec le décalage d'avant le changement (02:30 → 03:30 heure d'été) ; une heure qui existe
  deux fois (passage à l'heure d'hiver) ne donne qu'une occurrence, la première.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas.triggers import WEEKDAYS, DailySchedule, IntervalSchedule

#: Au-delà, le rattrapage ne compte plus une à une les occurrences manquées
CATCH_UP_CAP = 10_000


def next_occurrence(
    schedule: IntervalSchedule | DailySchedule, after: datetime, tz: ZoneInfo
) -> datetime:
    """Première occurrence strictement postérieure à `after` (UTC)."""
    if isinstance(schedule, IntervalSchedule):
        return (after + timedelta(minutes=schedule.every_minutes)).astimezone(UTC)
    hour, minute = (int(x) for x in schedule.at.split(":"))
    start = after.astimezone(tz).date()
    # 7 jours suffisent ; marge pour un jour sauté par un changement d'heure
    for offset in range(9):
        day = start + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] not in schedule.days:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(UTC)
        if candidate > after:
            return candidate
    raise ValueError("Horaire sans jour : aucune occurrence possible.")  # exclu par le schéma


def catch_up(
    schedule: IntervalSchedule | DailySchedule,
    due: datetime,
    now: datetime,
    tz: ZoneInfo,
) -> tuple[int, datetime]:
    """À partir d'une occurrence échue `due` (≤ `now`) : nombre d'occurrences échues jusqu'à
    `now` (`due` comprise) et prochaine occurrence postérieure à `now`.

    Le déclencheur n'en lance qu'une : les autres sont comptées `missed` (rien en rafale)."""
    if due > now:
        return 0, due
    if isinstance(schedule, IntervalSchedule):
        step = timedelta(minutes=schedule.every_minutes)
        count = (now - due) // step + 1
        return count, (due + count * step).astimezone(UTC)
    count = 0
    current = due
    while current <= now:
        count += 1
        if count >= CATCH_UP_CAP:
            return count, next_occurrence(schedule, now, tz)
        current = next_occurrence(schedule, current, tz)
    return count, current
