from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.tools import (
    CurrentDateTimeTool,
    PublishArtifactTool,
    ToolContext,
    ToolInput,
    portable_schema,
    system,
)
from app.tools.environment import ToolEnvironment
from app.tools.system import french_date
from app.tools.toolsets import build_tools


class Period(BaseModel):
    start: str
    end: str


class QueryInput(ToolInput):
    title: str = Field(description="Une propriété nommée title doit survivre.")
    period: Period
    periods: list[Period] = []


def test_portable_schema_inlines_refs_and_keeps_title_property() -> None:
    schema = portable_schema(QueryInput)
    text = repr(schema)
    assert "$ref" not in text and "$defs" not in text
    assert "title" in schema["properties"]
    assert schema["properties"]["period"]["properties"]["start"]["type"] == "string"
    assert schema["properties"]["periods"]["items"]["required"] == ["start", "end"]
    assert schema["additionalProperties"] is False


def test_tool_spec_is_valid() -> None:
    spec = PublishArtifactTool().spec()
    assert spec.name == "publish_artifact"
    assert set(spec.input_schema["required"]) == {"kind", "title", "content"}


async def test_invoke_rejects_unknown_fields() -> None:
    out = await CurrentDateTimeTool().invoke({"timezone": "UTC", "pirate": 1}, ToolContext())
    assert out.is_error and "pirate" in out.content


async def test_current_datetime() -> None:
    out = await CurrentDateTimeTool().invoke({"timezone": "Europe/Paris"}, ToolContext())
    assert not out.is_error and "Europe/Paris" in out.content


async def test_current_datetime_unknown_zone() -> None:
    out = await CurrentDateTimeTool().invoke({"timezone": "Mars/Olympus"}, ToolContext())
    assert out.is_error


def test_french_date_does_not_depend_on_the_locale() -> None:
    assert french_date(date(2026, 10, 25)) == "dimanche 25 octobre 2026"
    assert french_date(date(2026, 1, 1)) == "jeudi 1er janvier 2026"
    assert french_date(date(2027, 8, 16)) == "lundi 16 août 2027"
    # Toute la semaine (du lundi 19 octobre 2026) et toute l'année, dans l'ordre
    monday = date(2026, 10, 19)
    week = [french_date(monday + timedelta(days=i)).split()[0] for i in range(7)]
    assert week == ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = [french_date(date(2026, m, 2)).split()[2] for m in range(1, 13)]
    assert months[0] == "janvier" and months[7] == "août" and months[11] == "décembre"
    assert len(set(months)) == 12


async def test_current_datetime_gives_weekday_and_month_in_french(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paris = ZoneInfo("Europe/Paris")
    monkeypatch.setattr(system, "now_in", lambda tz: datetime(2026, 10, 25, 14, 5, tzinfo=tz))
    out = await CurrentDateTimeTool().invoke({"timezone": "Europe/Paris"}, ToolContext())
    assert out.content == (
        f"{datetime(2026, 10, 25, 14, 5, tzinfo=paris).isoformat()} "
        "(dimanche 25 octobre 2026, 14:05, Europe/Paris)"
    )
    assert "Sunday" not in out.content and "October" not in out.content


async def test_current_datetime_defaults_to_the_user_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Même horloge que les échéances de Tab et de Projets (app/tools/clock.py) : 22 h 30 UTC le
    # 24 octobre = 0 h 30 le 25 à Paris, 18 h 30 le 24 à New York
    instant = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)
    monkeypatch.setattr("app.tools.clock.now_utc", lambda: instant)
    paris = await CurrentDateTimeTool().invoke({}, ToolContext())
    assert paris.content.endswith("(dimanche 25 octobre 2026, 00:30, Europe/Paris)")
    new_york = CurrentDateTimeTool("America/New_York")
    local = await new_york.invoke({}, ToolContext())
    assert local.content.endswith("(samedi 24 octobre 2026, 18:30, America/New_York)")
    asked = await new_york.invoke({"timezone": "UTC"}, ToolContext())  # fuseau demandé : gardé
    assert asked.content.endswith("(samedi 24 octobre 2026, 22:30, UTC)")


def test_core_toolset_gives_the_timezone_setting_to_current_datetime() -> None:
    settings = Settings(_env_file=None, timezone="America/New_York")  # type: ignore[call-arg]
    tools, _ = build_tools(["core"], ToolEnvironment(settings))
    clock = next(t for t in tools if isinstance(t, CurrentDateTimeTool))
    assert clock.timezone == "America/New_York"
