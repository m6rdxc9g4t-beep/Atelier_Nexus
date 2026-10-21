"""Contrôles déterministes de l'état final d'un tour d'agent."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.base import AgentResult, PendingCall
from app.db.search import normalize as _normalize
from app.tools.base import Artifact
from evals.cases import EvalCase, Expect

Severity = Literal["required", "advisory"]


def normalize(text: str) -> str:
    """Minuscules, sans accents, apostrophes typographiques ramenées à « ' »."""
    return _normalize(text.replace("\u2019", "'").replace("\u2018", "'"))


@dataclass
class ToolCallRecord:
    id: str
    name: str
    input: dict[str, Any]
    result: str | None = None
    is_error: bool = False


@dataclass
class Transcript:
    """Ce qu'a fait l'agent pendant un tour (rempli à partir du flux d'événements)."""

    prompt: str
    calls: list[ToolCallRecord] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    pending: list[PendingCall] = field(default_factory=list)
    result: AgentResult | None = None
    #: Échec du tour : (code, message)
    error: tuple[str, str] | None = None

    @property
    def text(self) -> str:
        return self.result.text if self.result else ""

    @property
    def tool_names(self) -> list[str]:
        return [c.name for c in self.calls]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    severity: Severity = "required"


# ─── Nombres sourcés ──────────────────────────────────────────────

_NUMBER = re.compile(
    r"(?<![\w.,])-?\d{1,3}(?:[ \u00a0\u202f.,]\d{3})+(?:[.,]\d+)?(?![\w])"
    r"|(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\w])"
)


def _to_float(raw: str) -> float | None:
    text = re.sub(r"[ \u00a0\u202f]", "", raw)
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in text:
        text = (
            text.replace(",", "")
            if re.fullmatch(r"-?\d{1,3}(,\d{3}){2,}", text)
            else text.replace(",", ".")
        )
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3}){2,}", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def numbers_in(text: str) -> list[float]:
    out = []
    for match in _NUMBER.finditer(text):
        value = _to_float(match.group(0))
        if value is not None:
            out.append(value)
    return out


def _trivial(value: float) -> bool:
    """Petits entiers (rangs, jours, mois, quantités) et années : pas des chiffres à sourcer."""
    if value.is_integer() and (0 <= value <= 31 or 1990 <= value <= 2100):
        return True
    return False


def _close(value: float, source: float) -> bool:
    for scaled in (source, source / 1_000, source / 1_000_000, source * 100):
        if scaled == 0:
            if value == 0:
                return True
            continue
        if abs(value - scaled) <= max(abs(scaled) * 0.01, 0.006):
            return True
    return False


def _with_derived(numbers: list[float]) -> list[float]:
    """Les nombres d'un résultat, plus leur total et la part de chacun (en %) : un modèle qui
    additionne les régions ou donne des parts ne doit pas être soupçonné d'invention."""
    values = [n for n in numbers if not _trivial(n)]
    total = sum(values)
    if len(values) < 2 or not total:
        return numbers
    return [*numbers, total, *(n / total * 100 for n in values)]


def ungrounded_numbers(transcript: Transcript) -> list[float]:
    """Nombres de la réponse finale introuvables dans les résultats d'outils, les artefacts
    ou la demande (à 1 % près, en tenant compte des milliers, millions, pourcentages, totaux et
    parts du total)."""
    sources: list[float] = numbers_in(transcript.prompt)
    for call in transcript.calls:
        sources += numbers_in(json.dumps(call.input, ensure_ascii=False))
        sources += _with_derived(numbers_in(call.result or ""))
    for artifact in transcript.artifacts:
        sources += _with_derived(numbers_in(artifact.content))
    return [
        n
        for n in numbers_in(transcript.text)
        if not _trivial(n) and not any(_close(n, s) for s in sources)
    ]


# ─── Contrôles ────────────────────────────────────────────────────


def _is_subsequence(wanted: list[str], seen: list[str]) -> bool:
    it = iter(seen)
    return all(any(name == s for s in it) for name in wanted)


def _artifact_matches(artifact: Artifact, exp: Any) -> bool:
    if exp.kind and artifact.kind != exp.kind:
        return False
    if exp.title_contains and normalize(exp.title_contains) not in normalize(artifact.title):
        return False
    content = normalize(artifact.content)
    if any(normalize(t) not in content for t in exp.content_contains):
        return False
    return not (exp.content_regex and not re.search(exp.content_regex, artifact.content, re.S))


def _describe(exp: Any) -> str:
    parts = [f"{k}={v!r}" for k, v in exp.model_dump(exclude_defaults=True).items()]
    return ", ".join(parts) or "un artefact"


def evaluate(case: EvalCase, transcript: Transcript) -> list[CheckResult]:
    exp: Expect = case.expect
    checks: list[CheckResult] = []

    def add(name: str, ok: bool, detail: str = "", severity: Severity = "required") -> None:
        checks.append(CheckResult(name, ok, "" if ok else detail, severity))

    # Échec attendu (verrou local…) : seul le code compte
    if exp.error_code:
        got = transcript.error[0] if transcript.error else None
        add(
            "erreur attendue",
            got == exp.error_code,
            f"attendu {exp.error_code}, obtenu {got or 'aucune erreur'}",
        )
        return checks
    if transcript.error:
        code, message = transcript.error
        add("tour terminé", False, f"{code} : {message}")
        return checks

    result = transcript.result
    assert result is not None
    names = transcript.tool_names
    text = normalize(transcript.text)

    add(
        "raison d'arrêt",
        result.stop_reason in exp.stop_reason,
        f"{result.stop_reason} (attendu : {', '.join(exp.stop_reason)})",
    )
    if exp.provider:
        add(
            "moteur",
            result.provider == exp.provider,
            f"{result.provider} au lieu de {exp.provider}",
        )
    if exp.max_iterations is not None:
        add(
            "étapes",
            result.iterations <= exp.max_iterations,
            f"{result.iterations} étapes (max {exp.max_iterations})",
        )
    missing = [t for t in exp.tools_called if t not in names]
    if exp.tools_called:
        add("outils appelés", not missing, f"jamais appelés : {', '.join(missing)}")
    if exp.tools_in_order:
        add(
            "ordre des outils",
            _is_subsequence(exp.tools_in_order, names),
            f"attendu dans l'ordre {' → '.join(exp.tools_in_order)} ; obtenu {' → '.join(names) or 'aucun'}",
        )
    forbidden = [t for t in exp.tools_forbidden if t in names]
    if exp.tools_forbidden:
        add("outils interdits", not forbidden, f"appelés : {', '.join(forbidden)}")
    for args in exp.tool_args:
        inputs = [
            normalize(json.dumps(c.input, ensure_ascii=False))
            for c in transcript.calls
            if c.name == args.tool
        ]
        ok = any(all(normalize(t) in i for t in args.contains) for i in inputs)
        add(f"paramètres de {args.tool}", ok, f"aucun appel avec {args.contains}")
    if exp.tool_errors_max is not None:
        errors = [c.name for c in transcript.calls if c.is_error]
        add(
            "outils en erreur",
            len(errors) <= exp.tool_errors_max,
            f"{len(errors)} en erreur ({', '.join(errors)}), max {exp.tool_errors_max}",
        )
    if exp.approval_requested:
        waiting = [p.name for p in transcript.pending]
        absent = [t for t in exp.approval_requested if t not in waiting]
        add(
            "validation demandée",
            not absent,
            f"pas de validation demandée pour : {', '.join(absent)}",
        )
    for artifact_exp in exp.artifacts:
        ok = any(_artifact_matches(a, artifact_exp) for a in transcript.artifacts)
        got = ", ".join(f"{a.kind} « {a.title} »" for a in transcript.artifacts) or "aucun"
        add(f"artefact ({_describe(artifact_exp)})", ok, f"publiés : {got}")
    absent_text = [t for t in exp.text_contains if normalize(t) not in text]
    if exp.text_contains:
        add("réponse contient", not absent_text, f"absent : {absent_text}")
    if exp.text_contains_any:
        add(
            "réponse contient l'un de",
            any(normalize(t) in text for t in exp.text_contains_any),
            f"aucun de {exp.text_contains_any}",
        )
    present = [t for t in exp.text_not_contains if normalize(t) in text]
    if exp.text_not_contains:
        add("réponse ne contient pas", not present, f"présent : {present}")
    if exp.text_regex:
        add(
            "réponse (motif)",
            bool(re.search(exp.text_regex, transcript.text, re.S | re.I)),
            exp.text_regex,
        )
    if exp.output_contains_any:
        output = " ".join([text, *(normalize(a.content) for a in transcript.artifacts)])
        add(
            "livrable contient l'un de",
            any(normalize(t) in output for t in exp.output_contains_any),
            f"aucun de {exp.output_contains_any} (réponse et artefacts)",
        )
    if exp.grounded_numbers != "off":
        loose = ungrounded_numbers(transcript)
        shown = ", ".join(f"{n:g}" for n in loose[:8])
        add(
            "chiffres sourcés",
            not loose,
            f"introuvables dans les outils : {shown}",
            "required" if exp.grounded_numbers == "strict" else "advisory",
        )
    return checks


def passed(checks: list[CheckResult]) -> bool:
    return all(c.ok for c in checks if c.severity == "required")
