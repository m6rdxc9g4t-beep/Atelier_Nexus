"""Rapport d'une campagne d'évaluation : JSON (comparable) et Markdown (lisible)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from evals.runner import CaseOutcome, Mode

RESULTS_DIR = Path(__file__).resolve().parent / "resultats"


class EvalReport(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: Mode
    provider: str | None
    model: str | None
    judge: bool
    repeat: int
    cases: list[CaseOutcome]

    @property
    def played(self) -> list[CaseOutcome]:
        return [c for c in self.cases if not c.skipped]

    @property
    def reliable(self) -> list[CaseOutcome]:
        return [c for c in self.played if c.pass_rate == 1]

    @property
    def flaky(self) -> list[CaseOutcome]:
        return [c for c in self.played if c.pass_rate is not None and 0 < c.pass_rate < 1]

    @property
    def failing(self) -> list[CaseOutcome]:
        return [c for c in self.played if c.pass_rate == 0]

    @property
    def success(self) -> bool:
        return bool(self.played) and len(self.reliable) == len(self.played)

    def label(self) -> str:
        engine = self.provider or "moteur par défaut"
        return f"{engine}{f' · {self.model}' if self.model else ''}"


class Change(BaseModel):
    id: str
    before: float | None
    after: float | None


def compare(current: EvalReport, previous: EvalReport) -> tuple[list[Change], list[Change]]:
    """(régressions, progrès) entre deux campagnes, cas communs joués dans les deux."""
    before = {c.id: c.pass_rate for c in previous.played}
    worse: list[Change] = []
    better: list[Change] = []
    for case in current.played:
        if case.id not in before:
            continue
        old, new = before[case.id], case.pass_rate
        if old is None or new is None or old == new:
            continue
        (worse if new < old else better).append(Change(id=case.id, before=old, after=new))
    return worse, better


def _rate(case: CaseOutcome) -> str:
    if case.skipped:
        return "ignoré"
    icon = "✅" if case.pass_rate == 1 else ("⚠️" if case.passes else "❌")
    return f"{icon} {case.passes}/{len(case.attempts)}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def to_markdown(report: EvalReport, previous: EvalReport | None = None) -> str:
    played = report.played
    tokens = sum(a.tokens for c in played for a in c.attempts)
    seconds = sum(a.duration_s for c in played for a in c.attempts)
    lines = [
        f"# Évaluation des agents — {report.created_at:%d/%m/%Y %H:%M} UTC",
        "",
        f"- Moteur : **{report.label()}** · applications **{report.mode}** · "
        f"{report.repeat} essai(s) par cas{' · juge activé' if report.judge else ''}",
        f"- Cas joués : **{len(played)}** — fiables {len(report.reliable)}, instables "
        f"{len(report.flaky)}, en échec {len(report.failing)} ; ignorés "
        f"{len(report.cases) - len(played)}",
        f"- Jetons : {tokens:,} · durée totale : {seconds:,.0f} s".replace(",", " "),
        "",
        "| Cas | Agent | Réussite | Contrôles en échec | Jetons (moy.) | Durée (moy.) |",
        "|---|---|---|---|---|---|",
    ]
    for case in report.cases:
        if case.skipped:
            lines.append(f"| `{case.id}` | {case.agent} | ignoré | {case.skipped} | | |")
            continue
        failed = sorted({c.name for a in case.attempts for c in a.failures})
        n = len(case.attempts) or 1
        lines.append(
            f"| `{case.id}` | {case.agent} | {_rate(case)} | {', '.join(failed) or '—'} | "
            f"{sum(a.tokens for a in case.attempts) // n} | "
            f"{sum(a.duration_s for a in case.attempts) / n:.1f} s |"
        )
    if previous is not None:
        worse, better = compare(report, previous)
        lines += [
            "",
            f"## Par rapport au {previous.created_at:%d/%m/%Y %H:%M} ({previous.label()})",
            "",
        ]
        if not worse and not better:
            lines.append("Aucun changement sur les cas communs.")
        for change in worse:
            lines.append(f"- 🔻 `{change.id}` : {_pct(change.before)} → {_pct(change.after)}")
        for change in better:
            lines.append(f"- 🔺 `{change.id}` : {_pct(change.before)} → {_pct(change.after)}")
    details = [c for c in played if c.pass_rate != 1 or any(a.warnings for a in c.attempts)]
    if details:
        lines += ["", "## Détail des écarts", ""]
    for case in details:
        lines += [f"### `{case.id}` — {case.agent}", "", f"> {case.prompt}", ""]
        for index, attempt in enumerate(case.attempts, start=1):
            status = "réussi" if attempt.passed else "échoué"
            # En every_step, les validations données par l'évaluation (lectures, délégations)
            mode = (
                f", every_step : {attempt.requests} requête(s), "
                f"{len(attempt.approved)} validation(s) simulée(s)"
                if attempt.approval_mode == "every_step"
                else ""
            )
            lines.append(
                f"**Essai {index}** ({status}, {attempt.provider or '?'} · {attempt.model or '?'}{mode}) — "
                f"outils : {' → '.join(attempt.tools) or 'aucun'}"
            )
            for check in attempt.failures + attempt.warnings:
                mark = "❌" if check.severity == "required" else "⚠️"
                lines.append(f"- {mark} {check.name} : {check.detail}")
            if attempt.error:
                lines.append(f"- ❌ {attempt.error}")
            if not attempt.passed and attempt.text:
                excerpt = attempt.text[:400].replace("\n", " ")
                lines.append(f"- Réponse : « {excerpt}{'…' if len(attempt.text) > 400 else ''} »")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save(
    report: EvalReport, directory: Path = RESULTS_DIR, previous: EvalReport | None = None
) -> tuple[Path, Path]:
    """Écrit le rapport en JSON (pour comparer) et en Markdown (pour lire)."""
    directory.mkdir(parents=True, exist_ok=True)
    engine = (report.provider or "defaut") + (f"_{report.model}" if report.model else "")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in engine)
    stem = f"{report.created_at:%Y-%m-%d_%H%M%S}_{safe}"
    json_path = directory / f"{stem}.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path = directory / f"{stem}.md"
    md_path.write_text(to_markdown(report, previous), encoding="utf-8")
    return json_path, md_path


def load(path: Path) -> EvalReport:
    return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def latest(directory: Path = RESULTS_DIR, *, exclude: Path | None = None) -> Path | None:
    """Rapport JSON le plus récent du dossier (hors `exclude`)."""
    paths = sorted(p for p in directory.glob("*.json") if p != exclude)
    return paths[-1] if paths else None
