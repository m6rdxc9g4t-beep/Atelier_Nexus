"""Évaluer les agents sur des cas réels et comparer avec la campagne précédente.

    cd backend
    python -m scripts.evals --liste                          # les cas disponibles
    python -m scripts.evals --provider ollama --repeat 3     # tous les cas, 3 essais chacun
    python -m scripts.evals --agent data_analyst --juge      # un agent, avec un modèle juge
    python -m scripts.evals --cas data-mesure-dax --model qwen2.5:14b
    python -m scripts.evals --apps reelles --env-file "$HOME/Library/Application Support/Atelier Nexus/.env"

Applications **simulées** par défaut (Data Via, Projets, Trésorerie : résultats reproductibles,
rien à lancer). `--apps reelles` utilise les applications configurées et lancées sur la machine.
Aucune écriture n'est exécutée : aucune validation n'est jamais donnée.

Rapport : `evals/resultats/<date>_<moteur>.md` (et `.json`, comparé à la campagne précédente).
Code de sortie 1 si un cas joué n'a pas réussi tous ses essais.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.agents import AgentCatalog
from app.api.deps import get_custom_repository
from app.core.config import Settings, get_settings
from app.core.llm.router import LLMRouter
from app.tools.environment import ToolEnvironment
from evals.cases import CASES_DIR, CaseFileError, load_cases, select
from evals.report import RESULTS_DIR, EvalReport, latest, load, save
from evals.runner import CaseOutcome, EvalDeps, RunOptions, configured_apps, run_cases
from evals.simulation import SIMULATED_APPS, simulated_environment


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.evals",
        description="Évalue les agents d'Atelier Nexus sur des cas réels.",
    )
    parser.add_argument("--liste", action="store_true", help="liste les cas et s'arrête")
    parser.add_argument("--agent", action="append", help="limiter à un agent (répétable)")
    parser.add_argument("--cas", action="append", help="identifiant ou préfixe de cas (répétable)")
    parser.add_argument("--tag", action="append", help="étiquette (répétable)")
    parser.add_argument("--provider", choices=["anthropic", "ollama"], help="moteur à évaluer")
    parser.add_argument("--model", help="modèle du moteur (ex. llama3.1:8b, qwen2.5:14b)")
    parser.add_argument("--repeat", type=int, default=1, help="essais par cas (défaut 1)")
    parser.add_argument("--juge", action="store_true", help="faire juger les critères (rubric)")
    parser.add_argument("--juge-provider", choices=["anthropic", "ollama"], help="moteur du juge")
    parser.add_argument("--juge-model", help="modèle du juge")
    parser.add_argument(
        "--apps", choices=["simulees", "reelles"], default="simulees", help="applications"
    )
    parser.add_argument("--env-file", type=Path, help="fichier .env à utiliser (moteurs, apps)")
    parser.add_argument("--timeout", type=float, default=300.0, help="délai par tour (s)")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--sortie", type=Path, default=RESULTS_DIR, help="dossier des rapports")
    parser.add_argument(
        "--comparer", type=Path, help="rapport JSON de référence (défaut : le plus récent)"
    )
    return parser.parse_args(argv)


def progress(outcome: CaseOutcome) -> None:
    if outcome.skipped:
        print(f"  ·  {outcome.id} — ignoré ({outcome.skipped})")
        return
    attempts = outcome.attempts
    icon = "✅" if outcome.pass_rate == 1 else ("⚠️ " if outcome.passes else "❌")
    seconds = sum(a.duration_s for a in attempts) / len(attempts)
    print(f"  {icon} {outcome.id} — {outcome.passes}/{len(attempts)} ({seconds:.1f} s en moyenne)")
    for name in sorted({c.name + " : " + c.detail for a in attempts for c in a.failures})[:4]:
        print(f"       ↳ {name}")
    for attempt in attempts:
        if attempt.error and not attempt.passed and not attempt.failures:
            print(f"       ↳ {attempt.error}")
            break


async def main(args: argparse.Namespace) -> int:
    try:
        cases = select(load_cases(args.cases_dir), agents=args.agent, ids=args.cas, tags=args.tag)
    except CaseFileError as exc:
        print(f"Cas invalides : {exc}", file=sys.stderr)
        return 2
    if args.liste:
        for case in cases:
            apps = f" [{', '.join(case.apps)}]" if case.apps else ""
            print(f"{case.id:45} {case.agent:16}{apps}  {case.prompt[:60]}")
        print(f"\n{len(cases)} cas.")
        return 0
    if not cases:
        print("Aucun cas ne correspond aux filtres.", file=sys.stderr)
        return 2

    settings: Settings = Settings(_env_file=args.env_file) if args.env_file else get_settings()
    router = LLMRouter.from_settings(settings)
    if args.apps == "simulees":
        available: set[str] = set(SIMULATED_APPS)
        env_factory = simulated_environment
    else:
        available = configured_apps(settings)

        def env_factory() -> ToolEnvironment:
            return ToolEnvironment(settings)

    deps = EvalDeps(
        router=router,
        catalog=AgentCatalog(get_custom_repository()),
        env_factory=env_factory,
        available_apps=available,
        mode=args.apps,
    )
    options = RunOptions(
        provider=args.provider,
        model=args.model,
        repeat=args.repeat,
        judge=args.juge,
        judge_provider=args.juge_provider,
        judge_model=args.juge_model,
        timeout=args.timeout,
    )
    engine = args.provider or f"{router.default} (défaut)"
    print(f"{len(cases)} cas · moteur {engine} · applications {args.apps} · {args.repeat} essai(s)")
    outcomes = await run_cases(cases, deps, options, on_done=progress)

    report = EvalReport(
        mode=args.apps,
        provider=args.provider,
        model=args.model,
        judge=args.juge,
        repeat=args.repeat,
        cases=outcomes,
    )
    previous_path = args.comparer or latest(args.sortie)
    previous = load(previous_path) if previous_path and previous_path.exists() else None
    _, md_path = save(report, args.sortie, previous)
    print(
        f"\nFiables {len(report.reliable)} · instables {len(report.flaky)} · "
        f"en échec {len(report.failing)} · ignorés {len(report.cases) - len(report.played)}"
    )
    print(f"Rapport : {md_path}")
    return 0 if report.success else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    # Sans base locale, les agents personnalisés sont simplement absents : pas d'alerte à chaque cas
    logging.getLogger("app.agents.catalog").setLevel(logging.ERROR)
    sys.exit(asyncio.run(main(parse_args())))
