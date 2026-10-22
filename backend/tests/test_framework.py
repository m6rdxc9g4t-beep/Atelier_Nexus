"""Étape 5 : validations humaines, verrou local, délégation, catalogue."""

from typing import Any

import pytest

from app.agents import (
    AgentCatalog,
    ApprovalRequiredEvent,
    BaseAgent,
    DoneEvent,
    ToolResultEvent,
    describe,
    list_agent_classes,
)
from app.agents.base import REFUSED
from app.api.deps import prepare_environment
from app.core.config import ApprovalMode, Settings
from app.core.llm import Message, ProviderNotAllowedError, ProviderUnavailableError
from app.tools import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.base import Artifact
from app.tools.environment import ToolEnvironment
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response


class NoteInput(ToolInput):
    text: str


class SaveNoteTool(BaseTool[NoteInput]):
    """Outil d'écriture factice : compte ses exécutions."""

    name = "save_note"
    description = "Enregistre une note."
    input_model = NoteInput
    requires_approval = True

    def __init__(self) -> None:
        self.saved: list[str] = []

    def approval_summary(self, params: NoteInput) -> str:
        return f"Enregistrer « {params.text} »"

    async def run(self, params: NoteInput, ctx: ToolContext) -> ToolOutput:
        self.saved.append(params.text)
        return ToolOutput(content="Note enregistrée.")


class SecretTool(BaseTool[NoteInput]):
    name = "read_secret"
    description = "Lit une donnée sensible."
    input_model = NoteInput
    sensitive = True

    async def run(self, params: NoteInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content="solde : 1234.56 €")


class NotesAgent(BaseAgent):
    name = "notes"
    display_name = "Notes"
    description = "Agent de test"
    system_prompt = "Tu prends des notes."


async def collect(agent: BaseAgent, messages: list[Message], **kw: Any) -> list[Any]:
    return [e async for e in agent.run_stream(messages, **kw)]


# ─── Validation humaine ───────────────────────────────────────────


async def test_write_tool_pauses_for_approval_then_runs_when_approved() -> None:
    tool = SaveNoteTool()
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("save_note", {"text": "acheter du café"}, call_id="c1"),
            text_response("C'est noté."),
        ],
    )
    agent = NotesAgent(make_router(provider), tools=[tool])

    first = await collect(agent, [Message.user("Note : acheter du café")])
    approval = next(e for e in first if isinstance(e, ApprovalRequiredEvent))
    assert approval.calls[0].summary == "Enregistrer « acheter du café »"
    done = first[-1]
    assert isinstance(done, DoneEvent) and done.result.stop_reason == "awaiting_approval"
    assert tool.saved == []  # rien n'est exécuté avant validation

    history = [Message.user("Note : acheter du café"), *done.result.new_messages]
    assert history[-1].role == "assistant"
    second = await collect(agent, history, approvals={"c1": True})
    assert tool.saved == ["acheter du café"]
    final = second[-1]
    assert isinstance(final, DoneEvent) and final.result.text == "C'est noté."
    assert [m.role for m in final.result.new_messages] == ["user", "assistant"]


async def test_refused_action_is_reported_to_the_model() -> None:
    tool = SaveNoteTool()
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("save_note", {"text": "x"}, call_id="c1"),
            text_response("D'accord, je n'enregistre rien."),
        ],
    )
    agent = NotesAgent(make_router(provider), tools=[tool])
    first = await collect(agent, [Message.user("?")])
    history = [Message.user("?"), *first[-1].result.new_messages]
    second = await collect(agent, history, approvals={"c1": False})
    result = next(e for e in second if isinstance(e, ToolResultEvent))
    assert result.is_error and result.content == REFUSED
    assert tool.saved == []


async def test_resume_without_decision_pauses_again() -> None:
    tool = SaveNoteTool()
    provider = ScriptedProvider(
        "anthropic", [tool_response("save_note", {"text": "x"}, call_id="c1")]
    )
    agent = NotesAgent(make_router(provider), tools=[tool])
    first = await collect(agent, [Message.user("?")])
    history = [Message.user("?"), *first[-1].result.new_messages]
    again = await collect(agent, history, approvals={"autre": True})
    assert isinstance(again[0], ApprovalRequiredEvent)
    assert tool.saved == []


async def test_assistant_message_without_approvals_is_rejected() -> None:
    agent = NotesAgent(make_router(), tools=[SaveNoteTool()])
    with pytest.raises(ValueError):
        await collect(agent, [Message.assistant("…")])


# ─── Verrou local (données sensibles) ─────────────────────────────


async def test_sensitive_tool_locks_agent_on_ollama() -> None:
    anthropic = ScriptedProvider("anthropic", [text_response("ne doit pas servir")])
    ollama = ScriptedProvider("ollama", [text_response("Réponse locale", "ollama")])
    agent = NotesAgent(make_router(anthropic, ollama), tools=[SecretTool()])
    assert agent.local_only
    result = await agent.run([Message.user("Mon solde ?")])
    assert result.provider == "ollama"
    assert anthropic.requests == []


async def test_local_agent_refuses_claude_explicitly() -> None:
    agent = NotesAgent(make_router(), tools=[SecretTool()])
    with pytest.raises(ProviderNotAllowedError):
        await agent.run([Message.user("?")], provider="anthropic")


async def test_local_agent_never_falls_back_to_claude() -> None:
    anthropic = ScriptedProvider("anthropic", [text_response("fuite !")])
    ollama = ScriptedProvider("ollama", [ProviderUnavailableError("Ollama arrêté")])
    agent = NotesAgent(
        make_router(anthropic, ollama, default="ollama", fallback="anthropic"), tools=[SecretTool()]
    )
    with pytest.raises(ProviderUnavailableError):
        await agent.run([Message.user("?")])
    assert anthropic.requests == []


def test_finance_experts_are_local_only() -> None:
    by_name = {cls.name: cls for cls in list_agent_classes()}
    for name in ("finance", "comptable"):
        assert describe(by_name[name](make_router())).local_only


# ─── Catalogue ────────────────────────────────────────────────────


def env_without_apps(approval_mode: ApprovalMode = "every_step") -> ToolEnvironment:
    return ToolEnvironment(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            github_repo=None,
            projets_base_url="http://projets.test/api",
            approval_mode=approval_mode,
        )
    )


async def test_catalog_lists_the_experts_with_categories() -> None:
    infos = await AgentCatalog().infos(make_router(), env_without_apps())
    names = [i.name for i in infos]
    for expected in (
        "assistant", "orchestrateur", "data_analyst", "chef_de_projet", "product_owner",
        "developpeur", "finance", "comptable", "marketing", "commercial", "juridique", "rh",
        "redacteur",
    ):  # fmt: skip
        assert expected in names
    assert names[0] == "assistant"
    assert all(i.category and i.icon and i.starters for i in infos)


async def test_unconfigured_toolset_is_reported_not_fatal() -> None:
    infos = {i.name: i for i in await AgentCatalog().infos(make_router(), env_without_apps())}
    dev = infos["developpeur"]
    assert "GitHub — lecture" in dev.unavailable_toolsets
    assert any(t.name.startswith("projets_") for t in dev.tools)  # les autres boîtes restent


# ─── Délégation ───────────────────────────────────────────────────


async def test_orchestrator_delegates_and_collects_artifacts() -> None:
    from app.agents import get_agent_class

    class Publisher(BaseTool[NoteInput]):
        name = "publish_artifact"
        description = "publie"
        input_model = NoteInput

        async def run(self, params: NoteInput, ctx: ToolContext) -> ToolOutput:
            art = Artifact(kind="markdown", title="Point d'étape", content=params.text)
            return ToolOutput(content="publié", artifacts=[art])

    provider = ScriptedProvider(
        "anthropic",
        [
            # orchestrateur → délégation au rédacteur
            tool_response(
                "delegate_to_agent",
                {"agent": "redacteur", "task": "Rédige un point d'étape court."},
            ),
            # rédacteur (sous-agent) : publie puis répond
            tool_response("publish_artifact", {"text": "Tout avance."}, call_id="w1"),
            text_response("Point d'étape publié."),
            # orchestrateur : synthèse
            text_response("Le rédacteur a publié le point d'étape."),
        ],
    )
    router = make_router(provider)
    # Seulement les écritures : le sous-agent garde ses lectures (every_step : test_approval_mode)
    env = env_without_apps("writes_only")
    catalog = AgentCatalog()
    await prepare_environment(env, router, catalog)

    # Le rédacteur de test publie avec l'outil factice
    writer_cls = get_agent_class("redacteur")
    original = writer_cls.default_tools
    writer_cls.default_tools = lambda self: [Publisher()]  # type: ignore[method-assign]
    try:
        orchestrator = await catalog.build("orchestrateur", router, env)
        result = await orchestrator.run([Message.user("Fais un point d'étape")])
    finally:
        writer_cls.default_tools = original  # type: ignore[method-assign]

    assert result.text == "Le rédacteur a publié le point d'étape."
    assert [a.title for a in result.artifacts] == ["Point d'étape"]
    assert {name for name, _, _ in env.delegation_roster} >= {"redacteur", "finance"}
    assert "orchestrateur" not in {name for name, _, _ in env.delegation_roster}


async def test_cloud_orchestrator_cannot_reach_local_finance_agent() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response(
                "delegate_to_agent", {"agent": "finance", "task": "Donne-moi mon solde détaillé."}
            ),
            text_response("Je ne peux pas, ouvrez l'agent Finance."),
        ],
    )
    router = make_router(provider)
    env = env_without_apps()
    catalog = AgentCatalog()
    await prepare_environment(env, router, catalog)
    orchestrator = await catalog.build("orchestrateur", router, env)
    question = [Message.user("Mon solde ?")]
    waiting = await orchestrator.run(question)  # la délégation attend « Autoriser »
    assert [p.kind for p in waiting.pending_approvals] == ["delegation"]
    events = [
        e
        async for e in orchestrator.run_stream(
            [*question, *waiting.new_messages], approvals={"call_1": True}
        )
    ]
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.is_error and "ne doivent pas quitter" in result.content


async def test_delegated_agents_have_no_write_or_delegate_tools() -> None:
    catalog = AgentCatalog()
    env = env_without_apps("writes_only")
    agent = await catalog.build("chef_de_projet", make_router(), env, delegated=True)
    assert agent.tools
    assert not any(t.requires_approval for t in agent.tools.values())
    orchestrator = await catalog.build("orchestrateur", make_router(), env, delegated=True)
    assert "delegate_to_agent" not in orchestrator.tools
