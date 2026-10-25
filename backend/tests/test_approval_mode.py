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
    AgentResult,
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
from app.core.llm import Message, ProviderNotAllowedError, ProviderUnavailableError
from app.core.llm.router import LLMRouter, get_llm_router
from app.core.llm.types import (
    LLMRequest,
    LLMResponse,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from app.core.settings_editor import FIELDS
from app.schemas.workflows import WorkflowParam
from app.tools import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.workflows import run_workflow
from app.workflows_v2.engine import approval_token
from main import app
from tests.fake_data_via import DATASET_ID, FakeDataVia
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


async def test_iterations_count_the_whole_turn_across_resumes() -> None:
    """Chaque validation relance l'agent : le plafond d'étapes porte sur tout le tour."""
    script: list[LLMResponse | Exception] = [
        tool_response("weather", {"city": f"Ville {i}"}, call_id=f"w{i}") for i in range(4)
    ]
    provider = ScriptedProvider("anthropic", [*script, text_response("Bilan des 4 villes.")])
    agent, weather, _ = helper(provider)  # max_iterations = 4
    history = [Message.user("Météo de 4 villes, une par une")]
    seen = []
    approvals: dict[str, bool] | None = None
    for _ in range(5):
        result = await agent.run(history, approvals=approvals)
        seen.append((result.stop_reason, result.iterations))
        history = [*history, *result.new_messages]
        approvals = {p.id: True for p in result.pending_approvals}
        if not approvals:
            break
    assert seen == [
        ("awaiting_approval", 1),
        ("awaiting_approval", 2),
        ("awaiting_approval", 3),
        ("awaiting_approval", 4),
        ("max_iterations", 4),  # plafond : synthèse sans outil, plus de nouvelle validation
    ]
    assert len(weather.asked) == 4 and result.text == "Bilan des 4 villes."
    assert "Nombre d'étapes maximal atteint" in (provider.requests[-1].system or "")


# ─── Contexte des outils d'une requête à l'autre ──────────────────


class VizAgent(BaseAgent):
    name = "viz_test"
    display_name = "Viz"
    description = "Agent de test"
    system_prompt = "Tu analyses les ventes."
    toolsets = ("core", "data_via")


QUERY = {
    "dataset_id": DATASET_ID,
    "dimensions": [{"field": "region"}],
    "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
}


async def viz_request(
    router: LLMRouter, viz: FakeDataVia, history: list[Message], approvals: dict[str, bool] | None
) -> list[Any]:
    """Une requête de l'interface : environnement, agent et contexte neufs (comme l'API)."""
    settings = Settings(_env_file=None, data_via_base_url="http://viz.test/api")  # type: ignore[call-arg]
    env = ToolEnvironment(settings, transports={"data_via": viz.transport})
    try:
        agent = VizAgent(router, env)
        return await collect(agent, history, context=ToolContext(), approvals=approvals)
    finally:
        await env.aclose()


async def test_query_approved_in_a_later_request_finds_the_schema_described_before() -> None:
    """G-01 : describe autorisé à la requête N, query autorisée à la requête N+1."""
    viz = FakeDataVia()
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("data_via_describe_dataset", {"dataset_id": DATASET_ID}, call_id="d1"),
            tool_response("data_via_query", QUERY, call_id="q1"),
            text_response("La Bretagne est en tête."),
        ],
    )
    router = make_router(provider)
    history = [Message.user("CA par région ?")]
    for approvals in (None, {"d1": True}, {"q1": True}):
        events = await viz_request(router, viz, history, approvals)
        history += events[-1].result.new_messages
    results = {e.id: e for e in events if isinstance(e, ToolResultEvent)}
    assert results["q1"].is_error is False, results["q1"].content
    assert events[-1].result.text == "La Bretagne est en tête."
    paths = [(r.method, r.url.path) for r in viz.requests]
    # Schéma relu sans bruit à la requête de la query (aucune carte, rien pour le modèle)
    assert paths == [
        ("GET", f"/api/datasets/{DATASET_ID}"),
        ("GET", f"/api/datasets/{DATASET_ID}"),
        ("POST", "/api/query"),
    ]
    assert not any(isinstance(e, ToolCallEvent) and e.name.endswith("describe_dataset") for e in events)  # fmt: skip


async def test_refused_describe_is_not_replayed_and_the_rule_stays() -> None:
    viz = FakeDataVia()
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("data_via_describe_dataset", {"dataset_id": DATASET_ID}, call_id="d1"),
            tool_response("data_via_query", QUERY, call_id="q1"),
            text_response("Il me faut d'abord le schéma."),
        ],
    )
    router = make_router(provider)
    history = [Message.user("CA par région ?")]
    for approvals in (None, {"d1": False}, {"q1": True}):
        events = await viz_request(router, viz, history, approvals)
        history += events[-1].result.new_messages
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.is_error and "Schéma non consulté" in result.content
    assert viz.requests == []  # describe refusé : rien n'a été lu, ni relu


async def test_restore_hook_runs_only_before_an_executed_tool() -> None:
    """Une requête qui ne fait que demander une validation ne touche à aucune application."""
    viz = FakeDataVia()
    provider = ScriptedProvider(
        "anthropic",
        [
            tool_response("data_via_describe_dataset", {"dataset_id": DATASET_ID}, call_id="d1"),
            tool_response("data_via_query", QUERY, call_id="q1"),
        ],
    )
    router = make_router(provider)
    history = [Message.user("CA ?")]
    for approvals in (None, {"d1": True}):
        events = await viz_request(router, viz, history, approvals)
        history += events[-1].result.new_messages
    partial = await viz_request(router, viz, history, {"autre": True})  # sans décision pour q1
    assert isinstance(partial[0], ApprovalRequiredEvent)
    assert len(viz.requests) == 1  # le describe autorisé, et rien d'autre


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


async def orchestrate(
    router: LLMRouter, mode: ApprovalMode, history: list[Message], **kw: Any
) -> AgentResult:
    """Une requête de l'interface à l'orchestrateur : environnement, agent et contexte neufs."""
    env = delegation_env(mode)
    catalog = AgentCatalog()
    try:
        await prepare_environment(env, router, catalog)
        orchestrator = await catalog.build("orchestrateur", router, env)
        return await orchestrator.run(history, context=ToolContext(), **kw)
    finally:
        await env.aclose()


def delegation_enum(request: LLMRequest) -> list[str]:
    spec = next(t for t in request.tools if t.name == "delegate_to_agent")
    enum: list[str] = spec.input_schema["properties"]["agent"]["enum"]
    return enum


def tool_results(result: AgentResult) -> dict[str, ToolResultBlock]:
    return {
        b.tool_use_id: b
        for m in result.new_messages
        for b in m.content
        if isinstance(b, ToolResultBlock)
    }


async def test_ollama_orchestrator_delegates_on_ollama_and_reaches_finance() -> None:
    """F-02 : en every_step, la délégation s'exécute à la reprise ; le moteur y est connu."""
    anthropic = ScriptedProvider("anthropic")  # moteur par défaut : ne doit jamais servir
    ollama = ScriptedProvider(
        "ollama",
        [
            tool_response(
                "delegate_to_agent",
                {"agent": "redacteur", "task": "Rédige un point d'étape court."},
                call_id="call_r1",
                provider="ollama",
            ),
            text_response("# Point d'étape\nTout avance.", "ollama"),  # rédacteur
            tool_response(
                "delegate_to_agent",
                {"agent": "finance", "task": "Résume mes dépenses du mois."},
                call_id="call_f1",
                provider="ollama",
            ),
            text_response("Dépenses du mois : 1 234 €.", "ollama"),  # finance
            text_response("Point d'étape publié ; dépenses : 1 234 €.", "ollama"),
        ],
    )
    router = make_router(anthropic, ollama)
    history = [Message.user("Point d'étape et dépenses du mois")]
    kw: dict[str, Any] = {"provider": "ollama", "model": "qwen-test"}
    first = await orchestrate(router, "every_step", history, **kw)
    assert [p.kind for p in first.pending_approvals] == ["delegation"]
    assert "finance" in delegation_enum(ollama.requests[0])  # joignable : on tourne en local
    assert "assistant" not in delegation_enum(ollama.requests[0])

    history += first.new_messages
    second = await orchestrate(router, "every_step", history, approvals={"call_r1": True}, **kw)
    writer = ollama.requests[1]
    assert writer.model == "qwen-test" and writer.tools == []  # même moteur, même modèle
    assert "Rends le livrable COMPLET" in (writer.system or "")
    reply = tool_results(second)["call_r1"]
    assert not reply.is_error and "publie-le avec `publish_artifact`" in reply.content
    assert second.usage.input_tokens == 20  # orchestrateur + rédacteur

    history += second.new_messages
    third = await orchestrate(router, "every_step", history, approvals={"call_f1": True}, **kw)
    finance = tool_results(third)["call_f1"]
    assert not finance.is_error and "1 234 €" in finance.content
    assert third.text == "Point d'étape publié ; dépenses : 1 234 €."
    assert anthropic.requests == []

    # F-04 : la réponse de Finance est dans l'historique → plus jamais Claude dans ce fil
    history += [*third.new_messages, Message.user("Envoie ça à mon comptable.")]
    with pytest.raises(ProviderNotAllowedError, match="Finance"):
        await orchestrate(router, "every_step", history, provider="anthropic")


async def test_after_a_fallback_to_claude_local_delegation_is_refused() -> None:
    """F-01 : Ollama tombe, le routeur se replie sur Claude ; la délégation le voit."""
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response(
                "delegate_to_agent", {"agent": "finance", "task": "Donne-moi mon solde détaillé."}
            ),
            text_response("Ouvrez directement l'agent Finance."),
        ],
    )
    ollama = ScriptedProvider("ollama", [ProviderUnavailableError("Ollama charge le modèle")])
    router = make_router(anthropic, ollama, default="ollama", fallback="anthropic")
    result = await orchestrate(router, "writes_only", [Message.user("Mon solde ?")], provider="ollama")  # fmt: skip
    refused = tool_results(result)["call_1"]
    assert refused.is_error and "ne doivent pas quitter" in refused.content
    assert len(ollama.requests) == 1  # Finance n'a jamais tourné
    assert "finance" in delegation_enum(ollama.requests[0])
    # Requête reçue telle quelle par Claude au repli : elle annonce le repli possible, et rien de
    # local n'y figure (aucune réponse d'agent local dans l'historique : sinon, pas de repli)
    first = next(t for t in ollama.requests[0].tools if t.name == "delegate_to_agent")
    assert "repli possible sur un modèle en ligne" in first.description
    assert anthropic.requests[0].messages == ollama.requests[0].messages
    # Le repli renvoie la même requête ; l'appel suivant, lui, suit le moteur réellement utilisé
    online = anthropic.requests[1]
    assert "finance" not in delegation_enum(online)
    spec = next(t for t in online.tools if t.name == "delegate_to_agent")
    assert "Tu tournes sur un modèle en ligne" in spec.description and "Finance" in spec.description
    assert result.provider == "anthropic"


async def test_a_fallback_never_sends_a_local_answer_to_claude() -> None:
    """Repli Ollama → Claude, qui demande Finance (every_step) : la reprise validée tourne sur le
    moteur que demande l'interface (Ollama), Finance aussi ; ensuite, plus aucun repli."""
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response(
                "delegate_to_agent",
                {"agent": "finance", "task": "Résume mes dépenses du mois."},
                call_id="call_f1",
            )
        ],
    )
    ollama = ScriptedProvider(
        "ollama",
        [
            ProviderUnavailableError("Ollama charge le modèle"),  # orchestrateur : repli
            text_response("Dépenses : 1 234 €.", "ollama"),  # Finance, à la reprise
            ProviderUnavailableError("Ollama retombe"),  # orchestrateur : verrouillé, pas de repli
        ],
    )
    router = make_router(anthropic, ollama, default="ollama", fallback="anthropic")
    history = [Message.user("Mes dépenses du mois ?")]
    first = await orchestrate(router, "every_step", history, provider="ollama")
    assert first.provider == "anthropic"
    assert [p.kind for p in first.pending_approvals] == ["delegation"]

    history += first.new_messages
    with pytest.raises(ProviderUnavailableError, match="retombe"):
        await orchestrate(router, "every_step", history, provider="ollama", approvals={"call_f1": True})  # fmt: skip
    finance = ollama.requests[1]
    assert finance.tools == [] and "1 234" not in str(finance.messages)  # Finance, en local
    assert len(anthropic.requests) == 1  # le seul repli, avant toute réponse locale
    assert "1 234" not in str(anthropic.requests[0].messages)


async def test_a_locked_conversation_keeps_its_sub_agents_local_without_fallback() -> None:
    """F-04 : après une réponse de Finance, même le rédacteur reste sur Ollama, sans repli."""
    anthropic = ScriptedProvider("anthropic")
    ollama = ScriptedProvider(
        "ollama",
        [
            tool_response(
                "delegate_to_agent",
                {"agent": "redacteur", "task": "Rédige un courriel avec ces dépenses."},
                call_id="call_r2",
                provider="ollama",
            ),
            ProviderUnavailableError("Ollama arrêté"),  # le rédacteur : pas de repli vers Claude
            text_response("Le rédacteur n'a pas pu répondre.", "ollama"),
        ],
    )
    router = make_router(anthropic, ollama, default="ollama", fallback="anthropic")
    finance_call = ToolUseBlock(
        id="call_f1",
        name="delegate_to_agent",
        input={"agent": "finance", "task": "Dépenses du mois"},
    )
    history = [
        Message.user("Mes dépenses ?"),
        Message(role="assistant", content=[finance_call]),
        Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="call_f1",
                    tool_name="delegate_to_agent",
                    content="Réponse de Finance :\nDépenses : 1 234 €.",
                )
            ],
        ),
        Message.assistant("Vos dépenses : 1 234 €."),
        Message.user("Fais-en un courriel."),
    ]
    result = await orchestrate(router, "writes_only", history)
    failed = tool_results(result)["call_r2"]
    assert failed.is_error and "n'a pas pu répondre" in failed.content
    assert anthropic.requests == [] and result.provider == "ollama"
    # Conversation verrouillée : aucun repli, la description ne l'évoque donc pas
    spec = next(t for t in ollama.requests[0].tools if t.name == "delegate_to_agent")
    assert "Tu tournes sur le modèle local" in spec.description
    assert "repli possible" not in spec.description


async def test_delegation_is_refused_when_the_engine_is_unknown() -> None:
    env = delegation_env("writes_only")
    router = make_router()
    catalog = AgentCatalog()
    await prepare_environment(env, router, catalog)
    delegate = (await catalog.build("orchestrateur", router, env)).tools["delegate_to_agent"]
    out = await delegate.invoke(
        {"agent": "redacteur", "task": "Rédige un point d'étape."}, ToolContext()
    )
    assert out.is_error and "moteur" in out.content
    unknown = await delegate.invoke(
        {"agent": "assistant", "task": "Réponds à ma question."}, ToolContext(state={"provider": "anthropic"})
    )  # fmt: skip
    assert unknown.is_error and "indisponible" in unknown.content


async def test_an_unfinished_sub_agent_is_reported_with_its_usage() -> None:
    """G-12 : arrêt avant la fin → erreur explicite (réponse partielle jointe), jetons comptés."""
    cut = LLMResponse(
        provider="anthropic",
        model="anthropic-model",
        content=[TextBlock(text="Compte rendu : 1. Déc")],
        stop_reason="max_tokens",
        usage=Usage(input_tokens=7, output_tokens=3),
    )
    router = make_router(ScriptedProvider("anthropic", [cut]))
    env = delegation_env("every_step")
    catalog = AgentCatalog()
    await prepare_environment(env, router, catalog)
    delegate = (await catalog.build("orchestrateur", router, env)).tools["delegate_to_agent"]
    ctx = ToolContext(state={"provider": "anthropic"})
    out = await delegate.invoke({"agent": "redacteur", "task": "Rédige le compte rendu."}, ctx)
    assert out.is_error and "avant la fin (réponse coupée" in out.content
    assert "Compte rendu : 1. Déc" in out.content
    assert ctx.state["usage"] == Usage(input_tokens=7, output_tokens=3)


def delegation_history(content: str, *, is_error: bool, agent: str = "finance") -> list[Message]:
    """Fil où l'orchestrateur a délégué à un agent (Finance), avec le résultat donné."""
    call = ToolUseBlock(
        id="call_f1", name="delegate_to_agent", input={"agent": agent, "task": "Mon solde"}
    )
    result = ToolResultBlock(
        tool_use_id="call_f1", tool_name="delegate_to_agent", content=content, is_error=is_error
    )
    return [
        Message.user("Mon solde ?"),
        Message(role="assistant", content=[call]),
        Message(role="user", content=[result]),
        Message.assistant("Voici ce que j'ai."),
        Message.user("Rédige un courriel avec."),
    ]


async def test_a_partial_answer_of_a_local_agent_locks_the_conversation_too() -> None:
    """Finance coupée en route : sa réponse partielle (résultat en erreur) contient ses données,
    elle verrouille le fil comme une réponse complète ; un refus avant exécution, non."""
    cut = LLMResponse(
        provider="ollama",
        model="ollama-model",
        content=[TextBlock(text="Solde : 1 234 €, dont")],
        stop_reason="max_tokens",
    )
    anthropic = ScriptedProvider("anthropic")
    ollama = ScriptedProvider(
        "ollama",
        [
            tool_response(
                "delegate_to_agent",
                {"agent": "finance", "task": "Donne-moi mon solde détaillé."},
                call_id="call_f1",
                provider="ollama",
            ),
            cut,  # Finance
            ProviderUnavailableError("Ollama arrêté"),  # orchestrateur : aucun repli vers Claude
        ],
    )
    router = make_router(anthropic, ollama, default="ollama", fallback="anthropic")
    with pytest.raises(ProviderUnavailableError):
        await orchestrate(router, "writes_only", [Message.user("Mon solde ?")], provider="ollama")
    assert anthropic.requests == []

    partial = delegation_history(
        "Finance s'est arrêté avant la fin (réponse coupée, trop longue) : reformule la consigne "
        "ou découpe la sous-tâche.\nRéponse partielle :\nSolde : 1 234 €, dont",
        is_error=True,
    )
    with pytest.raises(ProviderNotAllowedError, match="Finance"):
        await orchestrate(make_router(), "writes_only", partial, provider="anthropic")

    refused = delegation_history(
        "Refusé : « Finance » manipule des données qui ne doivent pas quitter la machine, et tu "
        "tournes sur un modèle en ligne.",
        is_error=True,
    )
    online = ScriptedProvider("anthropic", [text_response("Ouvrez l'agent Finance.")])
    result = await orchestrate(make_router(online), "writes_only", refused, provider="anthropic")
    assert result.provider == "anthropic" and len(online.requests) == 1


async def test_an_answer_of_a_vanished_agent_keeps_the_conversation_local() -> None:
    """Agent délégué supprimé depuis (ou extension retirée) : on ne sait plus s'il était local,
    le fil reste donc sur le modèle local ; un agent connu en ligne ne verrouille rien."""
    gone = delegation_history("Réponse de Mes impôts :\nReste dû : 312 €.", is_error=False, agent="mes_impots")  # fmt: skip
    with pytest.raises(ProviderNotAllowedError, match="mes_impots"):
        await orchestrate(make_router(), "writes_only", gone, provider="anthropic")

    known = delegation_history("Réponse de Rédacteur :\nBrouillon.", is_error=False, agent="redacteur")  # fmt: skip
    online = ScriptedProvider("anthropic", [text_response("Voici le courriel.")])
    result = await orchestrate(make_router(online), "writes_only", known, provider="anthropic")
    assert result.provider == "anthropic"


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
