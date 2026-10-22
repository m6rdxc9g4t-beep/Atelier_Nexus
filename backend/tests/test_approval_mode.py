"""Validation de chaque action (`APPROVAL_MODE`, défaut `every_step`, choix de l'utilisateur).

Agents (lectures, refus, plusieurs appels, Ollama), résumé par défaut des outils, délégation sans
outil, workflows v1 et v2 (lecture, écriture, `when`), réglage lu et écrit. Les déclencheurs sont
dans test_triggers.py (arrêt à l'étape 1). Aucun réseau ni modèle réel.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from app.agents import (
    AgentCatalog,
    ApprovalRequiredEvent,
    BaseAgent,
    DoneEvent,
    ToolCallEvent,
    ToolResultEvent,
    get_agent_class,
)
from app.agents.base import REFUSED
from app.api.deps import prepare_environment
from app.core.config import ApprovalMode, Settings, get_settings
from app.core.llm import Message
from app.core.llm.router import get_llm_router
from app.core.llm.types import LLMResponse, ToolUseBlock, Usage
from app.core.settings_editor import FIELDS
from app.schemas.workflows import WorkflowParam
from app.tools import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.workflows import run_workflow
from app.workflows_v2.engine import approval_token
from main import app
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response
from tests.test_suite_nodes import Suite
from tests.test_workflows import WRITE_STEPS, Apps
from tests.test_workflows_v2 import MULTI, create, decide, s

# ─── Agents ───────────────────────────────────────────────────────


class CityInput(ToolInput):
    city: str
    days: int = 1


class WeatherTool(BaseTool[CityInput]):
    """Lecture sans résumé propre : le résumé par défaut s'applique."""

    name = "weather"
    description = "Prévisions météo d'une ville. Renvoie la température."
    input_model = CityInput

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def run(self, params: CityInput, ctx: ToolContext) -> ToolOutput:
        self.asked.append(params.city)
        return ToolOutput(content=f"{params.city} : 18 °C")


class NoteInput(ToolInput):
    text: str


class SaveTool(BaseTool[NoteInput]):
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
        return ToolOutput(content="ok")


class HelperAgent(BaseAgent):
    name = "helper"
    display_name = "Aide"
    description = "Agent de test"
    system_prompt = "Tu aides."
    max_iterations: ClassVar[int] = 4


def calls(*items: tuple[str, str, dict[str, Any]], provider: str = "anthropic") -> LLMResponse:
    """Plusieurs appels d'outils dans une même réponse du modèle : (id, nom, entrée)."""
    return LLMResponse(
        provider=provider,  # type: ignore[arg-type]
        model=f"{provider}-model",
        content=[ToolUseBlock(id=i, name=n, input=a) for i, n, a in items],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


async def collect(agent: BaseAgent, messages: list[Message], **kw: Any) -> list[Any]:
    return [e async for e in agent.run_stream(messages, **kw)]


def helper(provider: ScriptedProvider, mode: ApprovalMode | None = None) -> tuple[BaseAgent, WeatherTool, SaveTool]:  # fmt: skip
    weather, save = WeatherTool(), SaveTool()
    router = (
        make_router(None, provider, default="ollama")
        if provider.name == "ollama"
        else make_router(provider)
    )
    agent = HelperAgent(router, tools=[weather, save], approval_mode=mode)
    return agent, weather, save


async def test_without_environment_the_safest_mode_applies() -> None:
    agent, _, _ = helper(ScriptedProvider("anthropic"))
    assert agent.approval_mode == "every_step"
    env = ToolEnvironment(Settings(_env_file=None))  # type: ignore[call-arg]
    assert HelperAgent(make_router(), env).approval_mode == "every_step"
    relaxed = ToolEnvironment(Settings(_env_file=None, approval_mode="writes_only"))  # type: ignore[call-arg]
    assert HelperAgent(make_router(), relaxed).approval_mode == "writes_only"


async def test_a_read_waits_then_runs_after_approval() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [tool_response("weather", {"city": "Lyon"}, call_id="w1"), text_response("18 °C à Lyon.")],
    )
    agent, weather, _ = helper(provider)
    question = [Message.user("Météo à Lyon ?")]
    first = await collect(agent, question)
    approval = first[0]
    assert isinstance(approval, ApprovalRequiredEvent)
    (call,) = approval.calls
    assert call.kind == "read" and call.summary == "Prévisions météo d'une ville : city = « Lyon », days = 1"  # fmt: skip
    assert not any(isinstance(e, ToolCallEvent) for e in first) and weather.asked == []
    done = first[-1]
    assert isinstance(done, DoneEvent) and done.result.stop_reason == "awaiting_approval"
    assert "Chaque appel d'outil, lecture comprise" in provider.requests[0].system

    second = await collect(agent, [*question, *done.result.new_messages], approvals={"w1": True})
    assert [type(e) for e in second[:2]] == [ToolCallEvent, ToolResultEvent]
    assert weather.asked == ["Lyon"]
    final = second[-1]
    assert isinstance(final, DoneEvent) and final.result.text == "18 °C à Lyon."


async def test_a_refused_read_is_never_run_and_the_model_is_told() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [tool_response("weather", {"city": "Lyon"}, call_id="w1"), text_response("Bien reçu.")],
    )
    agent, weather, _ = helper(provider)
    question = [Message.user("Météo ?")]
    first = await collect(agent, question)
    second = await collect(
        agent, [*question, *first[-1].result.new_messages], approvals={"w1": False}
    )
    result = next(e for e in second if isinstance(e, ToolResultEvent))
    assert result.is_error and result.content == REFUSED and weather.asked == []


async def test_several_calls_one_card_each_decided_one_by_one_with_ollama_ids() -> None:
    """Ollama : identifiants `call_…` générés par le hub, conservés d'un tour à l'autre."""
    ollama = ScriptedProvider(
        "ollama",
        [
            calls(
                ("call_a1", "weather", {"city": "Lyon"}),
                ("call_b2", "weather", {"city": "Brest"}),
                ("call_c3", "save_note", {"text": "parapluie"}),
                provider="ollama",
            ),
            text_response("Fait.", "ollama"),
        ],
    )
    agent, weather, save = helper(ollama)
    question = [Message.user("Météo et note")]
    first = await collect(agent, question, provider="ollama")
    (approval,) = [e for e in first if isinstance(e, ApprovalRequiredEvent)]
    assert [(c.id, c.kind) for c in approval.calls] == [
        ("call_a1", "read"),
        ("call_b2", "read"),
        ("call_c3", "write"),
    ]
    history = [*question, *first[-1].result.new_messages]

    # Décision partielle : rien n'est exécuté, seuls les appels sans décision sont redemandés
    partial = await collect(agent, history, provider="ollama", approvals={"call_a1": True})
    (again,) = [e for e in partial if isinstance(e, ApprovalRequiredEvent)]
    assert [c.id for c in again.calls] == ["call_b2", "call_c3"]
    assert weather.asked == [] and save.saved == []

    decisions = {"call_a1": True, "call_b2": False, "call_c3": True}
    done = await collect(agent, history, provider="ollama", approvals=decisions)
    results = {e.id: e for e in done if isinstance(e, ToolResultEvent)}
    assert weather.asked == ["Lyon"] and save.saved == ["parapluie"]
    assert results["call_b2"].is_error and results["call_b2"].content == REFUSED
    assert done[-1].result.text == "Fait."


async def test_writes_only_lets_reads_run_but_still_stops_writes() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("weather", {"city": "Lyon"}, call_id="w1"),
            tool_response("save_note", {"text": "x"}, call_id="s1"),
        ],
    )
    agent, weather, save = helper(provider, "writes_only")
    events = await collect(agent, [Message.user("?")])
    assert weather.asked == ["Lyon"] and save.saved == []
    approval = next(e for e in events if isinstance(e, ApprovalRequiredEvent))
    assert [c.kind for c in approval.calls] == ["write"]
    assert "lecture comprise" not in provider.requests[0].system


def test_default_summary_is_readable() -> None:
    tool = WeatherTool()
    long = "très " * 30
    assert tool.summarize({"city": long, "days": 3}).startswith("Prévisions météo d'une ville : city = « très très")  # fmt: skip
    assert "…" in tool.summarize({"city": long})
    assert tool.summarize({"city": 3}) == "Prévisions météo d'une ville (paramètres invalides)"


async def test_every_read_tool_has_a_readable_label() -> None:
    """Les lectures n'ont pas de résumé propre : leur libellé ouvre la carte de validation."""
    from app.tools.labels import TOOL_LABELS
    from app.tools.toolsets import blank_tools, toolset_ids

    reads = [t for _, t in await blank_tools(toolset_ids()) if not t.requires_approval]
    assert reads and all(t.name in TOOL_LABELS for t in reads), [
        t.name for t in reads if t.name not in TOOL_LABELS
    ]


# ─── Délégation ───────────────────────────────────────────────────


def delegation_env(mode: ApprovalMode) -> ToolEnvironment:
    return ToolEnvironment(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            github_repo=None,
            projets_base_url="http://projets.test/api",
            approval_mode=mode,
        )
    )


async def test_delegation_waits_and_the_sub_agent_answers_without_any_tool() -> None:
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response(
                "delegate_to_agent",
                {"agent": "chef_de_projet", "task": "Fais le point sur le projet 1."},
                call_id="d1",
            ),
            text_response("Il me manque les éléments du projet 1."),  # sous-agent
            text_response("Le chef de projet a besoin des éléments."),  # orchestrateur
        ],
    )
    router = make_router(provider)
    env = delegation_env("every_step")
    catalog = AgentCatalog()
    await prepare_environment(env, router, catalog)
    orchestrator = await catalog.build("orchestrateur", router, env)
    delegate = orchestrator.tools["delegate_to_agent"]
    assert "AUCUN outil" in (delegate.spec().description or "")

    question = [Message.user("Où en est le projet 1 ?")]
    first = await orchestrator.run(question)
    (pending,) = first.pending_approvals
    assert pending.kind == "delegation"
    assert pending.summary == (
        "Confier à « Chef de projet » : « Fais le point sur le projet 1. » — il répondra sans "
        "outil, à partir de cette consigne seulement"
    )
    assert len(provider.requests) == 1  # le sous-agent n'a pas encore été lancé

    done = await orchestrator.run([*question, *first.new_messages], approvals={"d1": True})
    assert done.text == "Le chef de projet a besoin des éléments."
    sub_request = provider.requests[1]
    assert sub_request.tools == []  # aucun outil : rien ne s'exécute sans validation
    assert "sans aucun outil" in sub_request.system
    assert sub_request.messages[-1].content[0].text == "Fais le point sur le projet 1."  # type: ignore[union-attr]


async def test_delegated_agents_have_no_tool_in_every_step() -> None:
    catalog = AgentCatalog()
    env = delegation_env("every_step")
    for name in ("chef_de_projet", "data_analyst", "redacteur"):
        agent = await catalog.build(name, make_router(), env, delegated=True)
        assert agent.tools == {}, name
    alone = await catalog.build("chef_de_projet", make_router(), env)
    assert alone.tools  # utilisé directement, il garde ses outils (chacun validé)


async def test_delegation_writes_only_keeps_the_former_behaviour() -> None:
    env = delegation_env("writes_only")
    agent = await AgentCatalog().build("chef_de_projet", make_router(), env, delegated=True)
    assert agent.tools and not any(t.requires_approval for t in agent.tools.values())


# ─── Workflows v1 ─────────────────────────────────────────────────


async def test_v1_every_step_asks_for_each_step_then_runs() -> None:
    apps = Apps()
    agent = get_agent_class("chef_de_projet")(make_router(), apps.env("every_step"))
    titre = [WorkflowParam(name="titre")]
    shown = await run_workflow(agent, WRITE_STEPS, titre, {"titre": "Relire"}, None, binding="wf:1")
    assert shown.status == "awaiting_approval" and not shown.steps
    assert [(p.index, p.kind) for p in shown.pending] == [(1, "read"), (2, "write"), (3, "read")]
    assert shown.message.startswith("Chaque étape attend votre validation")
    assert not apps.projets.requests

    tokens = [p.token for p in shown.pending]
    partial = await run_workflow(
        agent, WRITE_STEPS, titre, {"titre": "Relire"}, {tokens[1]: True}, binding="wf:1"
    )
    assert [p.index for p in partial.pending] == [1, 3] and not apps.projets.requests

    refused = await run_workflow(
        agent, WRITE_STEPS, titre, {"titre": "Relire"},
        {tokens[0]: False, tokens[1]: True, tokens[2]: True}, binding="wf:1",
    )  # fmt: skip
    assert refused.status == "stopped"
    assert [x.status for x in refused.steps] == ["refused", "skipped", "skipped"]
    assert not apps.projets.requests

    done = await run_workflow(
        agent, WRITE_STEPS, titre, {"titre": "Relire"}, dict.fromkeys(tokens, True), binding="wf:1"
    )
    assert done.status == "completed" and [x.status for x in done.steps] == ["ok", "ok", "ok"]


# ─── Workflows v2 ─────────────────────────────────────────────────


def test_v2_every_step_read_then_write_each_with_its_resolved_input(
    client: TestClient, suite: Suite
) -> None:
    wf = create(client, MULTI)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    (pending,) = run["pending"]
    assert (pending["step_id"], pending["kind"]) == ("lire", "read")
    assert pending["token"] == approval_token(run["id"], "lire", "node:tab/tables.query", pending["input"])  # fmt: skip
    assert [x["status"] for x in run["steps"]] == ["awaiting_approval", "pending", "pending"]
    assert not suite.mcp_calls()

    # Lecture autorisée : son résultat est là, l'écriture suivante attend avec l'entrée résolue
    run = decide(client, run)
    assert run["steps"][0]["status"] == "ok" and run["steps"][0]["data"]["total"] == 2
    assert run["pending"][0]["kind"] == "write" and run["pending"][0]["input"]["title"] == "Gros œuvre"  # fmt: skip
    run = decide(client, run)
    assert run["pending"][0]["step_id"] == "publier" and suite.projets.created
    run = decide(client, run)
    assert run["status"] == "completed"


def test_v2_every_step_refused_read_stops_without_running_anything(
    client: TestClient, suite: Suite
) -> None:
    wf = create(client, MULTI)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    run = decide(client, run, allow=False)
    assert run["status"] == "stopped"
    assert [x["status"] for x in run["steps"]] == ["refused", "skipped", "skipped"]
    assert not suite.mcp_calls() and not suite.projets.created


def test_v2_every_step_false_condition_is_skipped_without_approval(
    client: TestClient, suite: Suite
) -> None:
    lire = s("lire", "node:tab/tables.query", {"table_id": "{{params.table}}"})
    gros = s(
        "gros", "node:viz/datasets.query", {"dataset_id": "ds_ventes"}, ["lire"],
        when={"left": "{{steps.lire.data.total}}", "op": "gt", "right": 10},
    )  # fmt: skip
    autre = s("autre", "tool:tab_list_tables", {}, ["gros"])
    wf = create(client, [lire, gros, autre])
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    run = decide(client, run)  # seule validation : la lecture ; le reste ne s'exécute pas
    assert run["status"] == "completed", run["message"]
    assert [x["status"] for x in run["steps"]] == ["ok", "skipped", "skipped"]
    assert not [r for r in suite.viz.requests if r.url.path == "/api/atelier/query"]


def test_v2_writes_only_runs_reads_alone(client: TestClient, suite: Suite) -> None:
    suite.approval_mode = "writes_only"
    wf = create(client, MULTI)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert [x["status"] for x in run["steps"]] == ["ok", "awaiting_approval", "pending"]
    assert run["pending"][0]["kind"] == "write"


def test_v2_switching_to_every_step_mid_run_applies_to_the_next_steps(
    client: TestClient, suite: Suite
) -> None:
    suite.approval_mode = "writes_only"
    reads = [
        s("creer", "node:projets/work_items.create", {"story_id": 2, "type": "TASK", "title": "x"}),
        s("lire", "node:tab/tables.query", {"table_id": "tbl_planning_lots"}, ["creer"]),
    ]
    wf = create(client, reads)
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert run["pending"][0]["step_id"] == "creer"
    suite.approval_mode = "every_step"  # réglage changé pendant la validation
    run = decide(client, run)
    assert run["status"] == "awaiting_approval" and run["pending"][0]["kind"] == "read"


# ─── Réglage ──────────────────────────────────────────────────────


def test_default_is_every_step() -> None:
    assert Settings(_env_file=None).approval_mode == "every_step"  # type: ignore[call-arg]
    field = next(f for f in FIELDS if f.key == "APPROVAL_MODE")
    assert field.group == "Validation des actions" and field.choices == ("every_step", "writes_only")  # fmt: skip


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APPROVAL_MODE", raising=False)
    (tmp_path / ".env").write_text("OLLAMA_MODEL=qwen2.5:7b\n")  # installation existante
    get_settings.cache_clear()
    get_llm_router.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()
    get_llm_router.cache_clear()


def test_setting_is_read_and_written(settings_client: TestClient, tmp_path: Path) -> None:
    def mode() -> dict[str, Any]:
        body = settings_client.get("/api/settings").json()
        return next(f for f in body["fields"] if f["key"] == "APPROVAL_MODE")

    current = mode()
    assert current["value"] == "every_step" and current["source"] == "défaut"
    assert current["choices"] == ["every_step", "writes_only"]

    saved = settings_client.put("/api/settings", json={"values": {"APPROVAL_MODE": "writes_only"}})
    assert saved.status_code == 200, saved.text
    assert "APPROVAL_MODE=writes_only" in (tmp_path / ".env").read_text()
    assert get_settings().approval_mode == "writes_only" and mode()["source"] == "fichier"

    refused = settings_client.put("/api/settings", json={"values": {"APPROVAL_MODE": "jamais"}})
    assert refused.status_code == 422 and "APPROVAL_MODE" in refused.json()["error"]["fields"]

    back = settings_client.put("/api/settings", json={"values": {"APPROVAL_MODE": ""}})
    assert back.status_code == 200 and get_settings().approval_mode == "every_step"
    assert "APPROVAL_MODE" not in (tmp_path / ".env").read_text()
