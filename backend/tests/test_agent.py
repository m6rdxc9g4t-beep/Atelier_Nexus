from typing import Any, ClassVar, Literal

import pytest

from app.agents import (
    ArtifactEvent,
    BaseAgent,
    DoneEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.core.llm import Message, ProviderUnavailableError, ToolResultBlock
from app.tools import BaseTool, PublishArtifactTool, ToolContext, ToolInput, ToolOutput
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response

#: Ces tests portent sur la boucle d'outils : lectures exécutées seules (validations :
#: test_approval_mode.py)
WRITES_ONLY: Literal["writes_only"] = "writes_only"


class AddInput(ToolInput):
    a: int
    b: int


class AddTool(BaseTool[AddInput]):
    name = "add"
    description = "Additionne deux entiers."
    input_model = AddInput

    async def run(self, params: AddInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=str(params.a + params.b))


class CalcAgent(BaseAgent):
    name = "calc"
    display_name = "Calc"
    description = "Agent de test"
    system_prompt = "Tu calcules."
    max_iterations: ClassVar[int] = 3

    def default_tools(self) -> list[BaseTool[Any]]:
        return [AddTool(), PublishArtifactTool()]


async def test_plain_answer_without_tools() -> None:
    provider = ScriptedProvider("anthropic", [text_response("Bonjour à vous")])
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    result = await agent.run([Message.user("Salut")])
    assert result.text == "Bonjour à vous"
    assert result.iterations == 1
    assert result.stop_reason == "end_turn"
    # prompt système et outils transmis au routeur
    request = provider.requests[0]
    assert request.system == "Tu calcules."
    assert {t.name for t in request.tools} == {"add", "publish_artifact"}


async def test_tool_loop_executes_tool_and_returns_result() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [tool_response("add", {"a": 2, "b": 3}), text_response("Le total est 5")],
    )
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    events = [e async for e in agent.run_stream([Message.user("2+3 ?")])]

    kinds = [e.type for e in events]
    assert kinds[:2] == ["tool_call", "tool_result"]
    assert isinstance(events[1], ToolResultEvent) and events[1].content == "5"
    assert any(isinstance(e, TextDeltaEvent) for e in events)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.result.text == "Le total est 5"
    assert done.result.iterations == 2
    assert done.result.usage.input_tokens == 20
    # transcript : assistant(tool_use) → user(tool_result) → assistant(texte)
    roles = [m.role for m in done.result.new_messages]
    assert roles == ["assistant", "user", "assistant"]
    second_request = provider.requests[1]
    block = second_request.messages[-1].content[0]
    assert isinstance(block, ToolResultBlock) and block.tool_name == "add"


async def test_artifacts_are_emitted_and_collected() -> None:
    sql = "SELECT 1"
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("publish_artifact", {"kind": "sql", "title": "Requête", "content": sql}),
            text_response("Requête publiée."),
        ],
    )
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    events = [e async for e in agent.run_stream([Message.user("Une requête")])]
    artifact_events = [e for e in events if isinstance(e, ArtifactEvent)]
    assert len(artifact_events) == 1
    assert artifact_events[0].artifact.content == sql
    done = events[-1]
    assert isinstance(done, DoneEvent) and done.result.artifacts[0].kind == "sql"


async def test_invalid_tool_input_is_reported_to_model() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [tool_response("add", {"a": "deux"}), text_response("Désolé")],
    )
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    events = [e async for e in agent.run_stream([Message.user("?")])]
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.is_error
    assert "a:" in result.content and "b:" in result.content


async def test_unknown_tool_is_reported_to_model() -> None:
    provider = ScriptedProvider("anthropic", [tool_response("delete_all", {}), text_response("ok")])
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    events = [e async for e in agent.run_stream([Message.user("?")])]
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.is_error and "Outil inconnu" in result.content


async def test_stops_after_max_iterations() -> None:
    script = [tool_response("add", {"a": 1, "b": 1}, call_id=f"c{i}") for i in range(3)]
    provider = ScriptedProvider("anthropic", list(script))
    agent = CalcAgent(make_router(provider), approval_mode=WRITES_ONLY)
    result = await agent.run([Message.user("boucle")])
    assert result.stop_reason == "max_iterations"
    assert result.iterations == 3


async def test_sticks_to_fallback_provider_for_whole_run() -> None:
    anthropic = ScriptedProvider("anthropic", [ProviderUnavailableError("down")])
    ollama = ScriptedProvider(
        "ollama",
        [tool_response("add", {"a": 1, "b": 2}, provider="ollama"), text_response("3", "ollama")],
    )
    agent = CalcAgent(make_router(anthropic, ollama, fallback="ollama"), approval_mode=WRITES_ONLY)
    result = await agent.run([Message.user("1+2")], model="claude-x")
    assert result.provider == "ollama"
    # 2e itération envoyée directement à Ollama, sans le modèle Claude
    assert len(anthropic.requests) == 1
    assert [r.model for r in ollama.requests] == [None, None]


async def test_rejects_conversation_not_ending_with_user() -> None:
    agent = CalcAgent(make_router())
    with pytest.raises(ValueError):
        await agent.run([Message.assistant("…")])


def test_duplicate_tool_names_rejected() -> None:
    with pytest.raises(ValueError):
        CalcAgent(make_router(), tools=[AddTool(), AddTool()])


def test_tool_call_event_shape() -> None:
    event = ToolCallEvent(id="x", name="add", input={"a": 1})
    assert event.model_dump()["type"] == "tool_call"
