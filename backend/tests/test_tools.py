from pydantic import BaseModel, Field

from app.tools import (
    CurrentDateTimeTool,
    PublishArtifactTool,
    ToolContext,
    ToolInput,
    portable_schema,
)


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
