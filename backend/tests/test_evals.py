"""Évaluations des agents : cas bien formés, simulation exacte, contrôles, juge, rapport.

Tout tourne avec un moteur scripté : aucun appel réseau, aucun modèle réel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agents import AgentCatalog, get_agent_class
from app.core.config import Settings
from app.core.llm.types import LLMResponse, ToolUseBlock, Usage
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import build_tools
from evals.cases import CaseFileError, EvalCase, load_cases, load_file, select
from evals.checks import Transcript, numbers_in, ungrounded_numbers
from evals.report import EvalReport, compare, load, save, to_markdown
from evals.runner import (
    Attempt,
    CaseOutcome,
    CheckOut,
    EvalDeps,
    RunOptions,
    parse_verdict,
    run_case,
)
from evals.simulation import (
    DATASET_ID,
    SIMULATED_APPS,
    SimulatedDataVia,
    SimulatedProjets,
    run_query,
    sales_rows,
    simulated_environment,
    simulated_settings,
)
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response

CASES = {c.id: c for c in load_cases()}


def calls_response(*calls: tuple[str, dict[str, Any]], provider: str = "anthropic") -> LLMResponse:
    """Plusieurs appels d'outils dans une même réponse."""
    return LLMResponse(
        provider=provider,  # type: ignore[arg-type]
        model=f"{provider}-model",
        content=[ToolUseBlock(id=f"c{i}", name=n, input=a) for i, (n, a) in enumerate(calls)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def deps_for(
    anthropic: ScriptedProvider, ollama: ScriptedProvider | None = None, **kw: Any
) -> EvalDeps:
    return EvalDeps(
        router=make_router(anthropic, ollama or ScriptedProvider("ollama")),
        catalog=AgentCatalog(),
        env_factory=kw.pop("env_factory", simulated_environment),
        available_apps=set(SIMULATED_APPS),
        **kw,
    )


# ─── Cas ──────────────────────────────────────────────────────────


def test_cases_load_with_unique_ids() -> None:
    assert len(CASES) >= 20
    assert all(c.source.endswith(".toml") for c in CASES.values())


def full_environment() -> ToolEnvironment:
    """Toutes les boîtes configurées, pour connaître tous les noms d'outils (sans réseau)."""
    settings = Settings(
        _env_file=None,
        github_repo="atelier/exemple",
        github_token="x",
        tab_mcp_command="atelier-mcp",
        cuisine_supabase_url="https://exemple.supabase.co",
        cuisine_supabase_anon_key="cle",
        cuisine_refresh_token="jeton",
    )
    return ToolEnvironment(settings)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_case_references_existing_agent_and_tools(case_id: str) -> None:
    case = CASES[case_id]
    cls = get_agent_class(case.agent)  # agent fourni (un agent personnalisé n'a pas de cas)
    tools, unavailable = build_tools(list(cls.toolsets), full_environment())
    assert not unavailable, unavailable
    names = {t.name for t in tools}
    exp = case.expect
    referenced = {
        *exp.tools_called,
        *exp.tools_in_order,
        *exp.tools_forbidden,
        *exp.approval_requested,
        *(a.tool for a in exp.tool_args),
    }
    assert referenced <= names, f"outils inconnus de {case.agent} : {referenced - names}"
    assert set(exp.approval_requested) <= {t.name for t in tools if t.requires_approval}


def test_case_file_errors_are_explicit(tmp_path: Path) -> None:
    bad = tmp_path / "x.toml"
    bad.write_text('[[case]]\nid = "ok-id"\nagent = "assistant"\nprompt = "abc"\noups = 1\n')
    with pytest.raises(CaseFileError, match="x.toml"):
        load_file(bad)
    (tmp_path / "y.toml").write_text('[[cas]]\nid = "z"\n')
    with pytest.raises(CaseFileError, match="clés inattendues"):
        load_file(tmp_path / "y.toml")


def test_select_by_agent_prefix_and_tag() -> None:
    cases = list(CASES.values())
    assert {c.agent for c in select(cases, agents=["finance"])} == {"finance"}
    assert all(c.id.startswith("data-") for c in select(cases, ids=["data-"]))
    assert all("validation" in c.tags for c in select(cases, tags=["validation"]))


# ─── Simulation ───────────────────────────────────────────────────


def test_sales_dataset_is_reproducible() -> None:
    assert sales_rows() == sales_rows()
    rows = sales_rows()
    assert len(rows) == 240
    assert rows[0]["date"] >= "2026-01-01" and rows[-1]["date"] <= "2026-09-30"


def test_simulated_query_is_exact() -> None:
    rows = sales_rows()
    out = run_query(
        {
            "dimensions": [{"field": "region"}],
            "measures": [{"field": "chiffre_affaires", "agg": "sum"}, {"agg": "count"}],
            "sort": [{"key": "sum(chiffre_affaires)", "desc": True}],
        },
        rows,
    )
    by_region = {r[0]: r[1] for r in out["rows"]}
    expected = sum(r["chiffre_affaires"] for r in rows if r["region"] == "Bretagne")
    assert by_region["Bretagne"] == pytest.approx(expected, abs=0.01)
    assert sum(r[2] for r in out["rows"]) == 240
    totals = [r[1] for r in out["rows"]]
    assert totals == sorted(totals, reverse=True)
    months = run_query(
        {"dimensions": [{"field": "date", "bin": "month"}], "measures": [{"field": "quantite"}]},
        rows,
    )
    assert [r[0] for r in months["rows"]] == [f"2026-{m:02d}" for m in range(1, 10)]


async def test_simulated_data_via_through_the_real_connector() -> None:
    env = simulated_environment()
    try:
        tools, unavailable = build_tools(["data_via", "projets_read", "tresorerie"], env)
        assert not unavailable
        by_name = {t.name: t for t in tools}
        from app.tools.base import ToolContext

        ctx = ToolContext()
        described = await by_name["data_via_describe_dataset"].invoke(
            {"dataset_id": DATASET_ID}, ctx
        )
        assert not described.is_error and "chiffre_affaires" in described.content
        query = await by_name["data_via_query"].invoke(
            {
                "dataset_id": DATASET_ID,
                "dimensions": [{"field": "region"}],
                "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
            },
            ctx,
        )
        assert not query.is_error and "Bretagne" in query.content
        check = await by_name["data_via_check_expression"].invoke(
            {
                "dataset_id": DATASET_ID,
                "expression": "DIVIDE(SUM(chiffre_affaires) - SUM(cout), SUM(chiffre_affaires))",
            },
            ctx,
        )
        assert not check.is_error and "0." in check.content
        dash = await by_name["tresorerie_dashboard"].invoke({}, ctx)
        assert not dash.is_error
        projets = await by_name["projets_dashboard"].invoke({"project_id": 1}, ctx)
        assert "App E-Commerce v2" in projets.content
    finally:
        await env.aclose()


def test_simulated_settings_only_enable_simulated_apps() -> None:
    settings = simulated_settings()
    assert settings.data_via_base_url and settings.projets_base_url and settings.tresorerie_base_url
    assert not (settings.cine_base_url or settings.savoir_base_url or settings.github_repo_list)


def test_unknown_expression_is_refused_without_eval() -> None:
    fake = SimulatedDataVia()
    request = httpx.Request(
        "POST",
        f"http://viz.simule/api/datasets/{DATASET_ID}/model/check",
        json={"kind": "measure", "expression": "__import__('os').getcwd()"},
    )
    assert fake(request).json()["ok"] is False


# ─── Nombres sourcés ──────────────────────────────────────────────


def test_numbers_in_french_and_english_formats() -> None:
    assert numbers_in("143 307,52 € et 53,4 % ; 1,234,567 ; 2.5") == [
        143307.52,
        53.4,
        1234567.0,
        2.5,
    ]


def test_ungrounded_numbers_tolerate_rounding_scaling_and_percentages() -> None:
    transcript = Transcript(prompt="Combien en 2026 ?")
    from evals.checks import ToolCallRecord

    transcript.calls.append(
        ToolCallRecord(
            id="1", name="q", input={}, result="| Bretagne | 143307.52 |\n| ratio | 0.5345 |"
        )
    )
    from app.agents.base import AgentResult

    def with_text(text: str) -> Transcript:
        transcript.result = AgentResult(
            agent="a", provider="anthropic", model="m", text=text, stop_reason="end_turn",
            iterations=1, usage=Usage(), artifacts=[], new_messages=[],
        )  # fmt: skip
        return transcript

    assert (
        ungrounded_numbers(
            with_text("Bretagne : 143 308 € (143,3 k€), marge 53,45 %, en 2026, 3 régions")
        )
        == []
    )
    assert ungrounded_numbers(with_text("Bretagne : 250 000 €")) == [250000.0]


# ─── Exécution d'un cas ───────────────────────────────────────────


def region_totals() -> dict[str, float]:
    out = run_query(
        {
            "dimensions": [{"field": "region"}],
            "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
        },
        sales_rows(),
    )
    return {r[0]: r[1] for r in out["rows"]}


def explore_then_answer(text: str) -> list[LLMResponse | Exception]:
    return [
        tool_response("data_via_describe_dataset", {"dataset_id": DATASET_ID}, call_id="d"),
        tool_response(
            "data_via_query",
            {
                "dataset_id": DATASET_ID,
                "dimensions": [{"field": "region"}],
                "measures": [{"field": "chiffre_affaires", "agg": "sum"}],
            },
            call_id="q",
        ),
        text_response(text),
    ]


async def test_good_run_passes_all_checks() -> None:
    totals = region_totals()
    best = max(totals, key=lambda k: totals[k])
    amount = f"{totals[best]:,.2f}".replace(",", " ").replace(".", ",")
    anthropic = ScriptedProvider(
        "anthropic", explore_then_answer(f"{best} arrive en tête avec {amount} €.")
    )
    outcome = await run_case(CASES["data-schema-avant-requete"], deps_for(anthropic), RunOptions())
    attempt = outcome.attempts[0]
    assert attempt.passed, attempt.checks
    assert attempt.tools == ["data_via_describe_dataset", "data_via_query"]
    assert not attempt.warnings
    assert any(a.startswith("data_preview") for a in attempt.artifacts)


async def test_invented_number_is_a_warning_not_a_failure() -> None:
    anthropic = ScriptedProvider(
        "anthropic", explore_then_answer("Île-de-France arrive en tête avec 999 999 €.")
    )
    attempt = (
        await run_case(CASES["data-schema-avant-requete"], deps_for(anthropic), RunOptions())
    ).attempts[0]
    assert attempt.passed
    assert [w.name for w in attempt.warnings] == ["chiffres sourcés"]
    assert "999999" in attempt.warnings[0].detail


async def test_query_without_schema_fails_the_order_check() -> None:
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response(
                "data_via_query",
                {"dataset_id": DATASET_ID, "measures": [{"field": "chiffre_affaires"}]},
            ),
            text_response("Île-de-France est en tête."),
        ],
    )
    attempt = (
        await run_case(CASES["data-schema-avant-requete"], deps_for(anthropic), RunOptions())
    ).attempts[0]
    assert not attempt.passed
    assert {c.name for c in attempt.failures} >= {"ordre des outils"}


async def test_write_is_never_executed_and_approval_is_checked() -> None:
    fake = SimulatedProjets()

    def env() -> ToolEnvironment:
        base = simulated_environment()
        base._transports["projets"] = httpx.MockTransport(fake)
        return base

    args = {
        "story_id": 2,
        "type": "TASK",
        "title": "Écrire les tests de synchronisation",
        "estimated_hours": 4,
    }
    anthropic = ScriptedProvider("anthropic", [tool_response("projets_create_work_item", args)])
    outcome = await run_case(
        CASES["projets-creation-soumise-a-validation"],
        deps_for(anthropic, env_factory=env),
        RunOptions(),
    )
    attempt = outcome.attempts[0]
    assert attempt.passed, attempt.checks
    assert attempt.stop_reason == "awaiting_approval" and attempt.pending == [
        "projets_create_work_item"
    ]
    assert not [r for r in fake.requests if r.method != "GET"]


async def test_local_lock_case_passes_without_calling_any_model() -> None:
    anthropic, ollama = ScriptedProvider("anthropic"), ScriptedProvider("ollama")
    outcome = await run_case(
        CASES["finance-claude-refuse"], deps_for(anthropic, ollama), RunOptions()
    )
    assert outcome.attempts[0].passed
    assert not anthropic.requests and not ollama.requests


async def test_local_agent_on_claude_is_skipped_not_failed() -> None:
    """Un agent 100 % local joué avec --provider anthropic : le verrou refuse Claude, ce n'est
    pas un échec de l'agent (le cas se joue sur Ollama)."""
    anthropic = ScriptedProvider("anthropic")
    outcome = await run_case(
        CASES["finance-synthese-locale"],
        deps_for(anthropic),
        RunOptions(provider="anthropic"),
    )
    assert outcome.skipped == "agent 100 % local : à jouer avec --provider ollama"
    assert not anthropic.requests


async def test_case_is_skipped_when_its_app_is_missing() -> None:
    deps = deps_for(ScriptedProvider("anthropic"))
    outcome = await run_case(CASES["dev-jamais-sur-main"], deps, RunOptions())
    assert outcome.skipped and "github" in outcome.skipped and not outcome.attempts


async def test_repeat_measures_flakiness() -> None:
    anthropic = ScriptedProvider(
        "anthropic",
        [
            tool_response("current_datetime", {}),
            text_response("Nous sommes mercredi."),
            text_response("Je ne sais pas."),  # 2e essai : n'appelle pas l'outil
        ],
    )
    outcome = await run_case(
        CASES["assistant-date-du-jour"], deps_for(anthropic), RunOptions(repeat=2)
    )
    assert outcome.passes == 1 and outcome.pass_rate == 0.5


# ─── Juge ─────────────────────────────────────────────────────────


def test_parse_verdict() -> None:
    assert parse_verdict('Voici : {"verdict": "ok", "raison": "Complet."}') == (True, "Complet.")
    assert parse_verdict('{"verdict": "KO", "raison": "Il manque la région."}')[0] is False
    assert parse_verdict("pas de json")[0] is False


async def test_judge_runs_on_the_same_engine_and_counts() -> None:
    script = explore_then_answer("Île-de-France arrive en tête.")
    script.append(text_response('{"verdict": "ko", "raison": "Aucun chiffre par région."}'))
    anthropic = ScriptedProvider("anthropic", script)
    attempt = (
        await run_case(
            CASES["data-schema-avant-requete"], deps_for(anthropic), RunOptions(judge=True)
        )
    ).attempts[0]
    judge = next(c for c in attempt.checks if c.name == "juge")
    assert not judge.ok and judge.severity == "required" and not attempt.passed
    assert "<transcription>" in anthropic.requests[-1].messages[0].text
    # Le juge voit ce que l'agent a lu : un fait tiré d'un outil n'est pas « inventé »
    prompt = anthropic.requests[-1].messages[0].text
    assert "Résultats des outils" in prompt and "- data_via_describe_dataset :" in prompt


async def test_judge_of_a_local_agent_stays_local() -> None:
    ollama = ScriptedProvider(
        "ollama",
        [
            tool_response("tresorerie_dashboard", {}, provider="ollama"),
            text_response("Votre situation est saine.", provider="ollama"),
            text_response('{"verdict": "ok", "raison": "Factuel."}', provider="ollama"),
        ],
    )
    anthropic = ScriptedProvider("anthropic")
    attempt = (
        await run_case(
            CASES["finance-synthese-locale"],
            deps_for(anthropic, ollama),
            RunOptions(judge=True, judge_provider=None),
        )
    ).attempts[0]
    assert attempt.provider == "ollama"
    assert next(c for c in attempt.checks if c.name == "juge").ok
    assert not anthropic.requests  # ni l'agent ni le juge n'ont parlé à Claude

    refused = ScriptedProvider(
        "ollama",
        [
            tool_response("tresorerie_dashboard", {}, provider="ollama"),
            text_response("Saine.", provider="ollama"),
        ],
    )
    attempt = (
        await run_case(
            CASES["finance-synthese-locale"],
            deps_for(anthropic, refused),
            RunOptions(judge=True, judge_provider="anthropic"),
        )
    ).attempts[0]
    judge = next(c for c in attempt.checks if c.name == "juge")
    assert not judge.ok and judge.severity == "advisory" and not anthropic.requests


# ─── Rapport ──────────────────────────────────────────────────────


def outcome(case_id: str, results: list[bool]) -> CaseOutcome:
    return CaseOutcome(
        id=case_id,
        agent="data_analyst",
        source="donnees.toml",
        prompt="?",
        attempts=[
            Attempt(
                passed=ok,
                checks=[] if ok else [CheckOut(name="ordre des outils", ok=False, detail="x")],
            )
            for ok in results
        ],
    )


def test_report_markdown_comparison_and_round_trip(tmp_path: Path) -> None:
    before = EvalReport(mode="simulees", provider="ollama", model="llama3.1:8b", judge=False, repeat=2,
                        cases=[outcome("a", [True, True]), outcome("b", [False, False])])  # fmt: skip
    after = EvalReport(mode="simulees", provider="ollama", model="qwen2.5:14b", judge=False, repeat=2,
                       cases=[outcome("a", [True, False]), outcome("b", [True, True]),
                              CaseOutcome(id="c", agent="x", source="s", prompt="?", skipped="github")])  # fmt: skip
    worse, better = compare(after, before)
    assert [c.id for c in worse] == ["a"] and [c.id for c in better] == ["b"]
    assert not after.success and [c.id for c in after.flaky] == ["a"]
    text = to_markdown(after, before)
    assert "🔻 `a` : 100% → 50%" in text and "🔺 `b`" in text and "ignoré" in text
    assert "ordre des outils" in text
    json_path, md_path = save(after, tmp_path, before)
    assert md_path.read_text(encoding="utf-8") == text
    assert load(json_path).cases[0].pass_rate == 0.5
    assert json.loads(json_path.read_text())["model"] == "qwen2.5:14b"


def test_eval_case_rejects_unknown_expectation() -> None:
    with pytest.raises(ValueError):
        EvalCase.model_validate(
            {"id": "abc", "agent": "assistant", "prompt": "abc", "expect": {"outil": 1}}
        )


async def test_engine_outage_skips_the_case_instead_of_blaming_the_agent() -> None:
    from app.core.llm.errors import ProviderUnavailableError

    ollama = ScriptedProvider(
        "ollama", [ProviderUnavailableError("Ollama injoignable", provider="ollama")]
    )
    outcome = await run_case(
        CASES["finance-synthese-locale"],
        deps_for(ScriptedProvider("anthropic"), ollama),
        RunOptions(),
    )
    assert outcome.skipped and "moteur indisponible" in outcome.skipped
    assert not outcome.attempts and outcome.pass_rate is None


def test_output_contains_any_looks_in_artifacts_too() -> None:
    from app.agents.base import AgentResult
    from app.tools.base import Artifact
    from evals.checks import evaluate

    case = EvalCase.model_validate(
        {
            "id": "relance",
            "agent": "commercial",
            "prompt": "Relance",
            "expect": {"output_contains_any": ["Bonjour"]},
        }
    )
    transcript = Transcript(prompt="Relance")
    transcript.result = AgentResult(
        agent="commercial", provider="anthropic", model="m", text="Voici le brouillon.",
        stop_reason="end_turn", iterations=1, usage=Usage(), artifacts=[], new_messages=[],
    )  # fmt: skip
    check = next(c for c in evaluate(case, transcript) if c.name.startswith("livrable"))
    assert not check.ok
    transcript.artifacts.append(
        Artifact(kind="markdown", title="Relance", content="Bonjour Madame,")
    )
    check = next(c for c in evaluate(case, transcript) if c.name.startswith("livrable"))
    assert check.ok


def test_totals_and_shares_count_as_grounded() -> None:
    from app.agents.base import AgentResult
    from evals.checks import ToolCallRecord

    transcript = Transcript(prompt="Total ?")
    transcript.calls.append(ToolCallRecord(id="1", name="q", input={}, result="A | 300\nB | 100"))
    transcript.result = AgentResult(
        agent="a", provider="anthropic", model="m", text="Total 400 €, dont A 75 % et B 25 %.",
        stop_reason="end_turn", iterations=1, usage=Usage(), artifacts=[], new_messages=[],
    )  # fmt: skip
    assert ungrounded_numbers(transcript) == []
