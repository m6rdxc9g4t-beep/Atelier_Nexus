"""Validation d'un workflow v2 : erreurs par étape et par champ, codes stables.

Codes (docs/workflows-v2-api.md §4) : `DUPLICATE_ID`, `BAD_ID`, `UNKNOWN_USES`, `UNAVAILABLE`,
`CYCLE`, `UNKNOWN_NEED`, `REF_NOT_ANCESTOR`, `UNDECLARED_PARAM`, `INPUT_INVALID`,
`TOO_MANY_STEPS`, `NOT_REPLAYABLE` ; plus, comme la validation locale de l'éditeur :
`NO_STEPS`, `DUPLICATE_PARAM`, `BAD_TEMPLATE`, `BAD_CONDITION`.

Un champ d'entrée qui contient un gabarit n'est vérifié qu'à l'exécution (sa valeur réelle
n'est connue qu'alors).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.schemas.workflows_v2 import ValidationIssue, ValidationResult, WorkflowV2Fields
from app.suite.nodes import validate_input
from app.workflows_v2.graph import ancestors, topo_order
from app.workflows_v2.steps import NodeTarget, StepProblem, StepRegistry, ToolTarget
from app.workflows_v2.templates import Ref, has_template, refs_in

STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_STEPS = 30
#: Erreurs qui n'empêchent pas d'enregistrer un brouillon (vérifiées au lancement) :
#: application lancée plus tard, entrée ou condition encore incomplètes
SAVE_TOLERATED = {"UNAVAILABLE", "INPUT_INVALID", "BAD_CONDITION"}


def _issue(step_id: str | None, field: str | None, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(step_id=step_id, field=field, code=code, message=message)


def template_fields(raw_input: dict[str, Any]) -> set[str]:
    return {key for key, value in raw_input.items() if has_template(value)}


def input_issues(
    target: ToolTarget | NodeTarget, raw_input: dict[str, Any]
) -> list[tuple[str, str]]:
    """(champ, message) des erreurs d'entrée, hors champs qui contiennent un gabarit."""
    skip = template_fields(raw_input)
    issues: list[tuple[str, str]] = []
    if isinstance(target, ToolTarget):
        try:
            target.tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            for error in exc.errors():
                loc = [str(p) for p in error["loc"]]
                field = loc[0] if loc else ""
                if field in skip:
                    continue
                where = ".".join(loc)
                issues.append((field, f"{where} : {error['msg']}" if where else error["msg"]))
        return issues
    for field, message in validate_input(target.action, raw_input):
        if field in skip:
            continue
        issues.append((field, message))
    return issues


def validate_workflow(body: WorkflowV2Fields, registry: StepRegistry) -> ValidationResult:
    issues: list[ValidationIssue] = []
    steps = body.steps
    if not steps:
        issues.append(_issue(None, None, "NO_STEPS", "Ajoutez au moins une étape."))
    if len(steps) > MAX_STEPS:
        issues.append(
            _issue(None, None, "TOO_MANY_STEPS", f"{MAX_STEPS} étapes au plus ({len(steps)}).")
        )
    declared: set[str] = set()
    for param in body.params:
        if param.name in declared:
            issues.append(
                _issue(
                    None,
                    f"params.{param.name}",
                    "DUPLICATE_PARAM",
                    f"Paramètre « {param.name} » déclaré deux fois.",
                )
            )
        declared.add(param.name)

    ids = {s.id for s in steps}
    seen: set[str] = set()
    for step in steps:
        if not STEP_ID.match(step.id):
            issues.append(
                _issue(
                    step.id,
                    "id",
                    "BAD_ID",
                    "Identifiant invalide : minuscule en tête, puis a-z, 0-9 ou _ "
                    "(40 caractères au plus).",
                )
            )
        if step.id in seen:
            issues.append(
                _issue(step.id, "id", "DUPLICATE_ID", f"Identifiant « {step.id} » déjà utilisé.")
            )
        seen.add(step.id)
        for need in step.needs:
            if need not in ids:
                issues.append(
                    _issue(step.id, "needs", "UNKNOWN_NEED", f"Étape amont inconnue : « {need} ».")
                )
        target = registry.lookup(step.uses)
        if isinstance(target, StepProblem):
            issues.append(_issue(step.id, None, target.code, target.message))
        else:
            for field, message in input_issues(target, step.input):
                issues.append(_issue(step.id, field or None, "INPUT_INVALID", message))
        if step.when is not None:
            unary = step.when.op in ("empty", "not_empty")
            if not step.when.left.strip():
                issues.append(
                    _issue(
                        step.id, "when", "BAD_CONDITION", "Condition : valeur à tester manquante."
                    )
                )
            if not unary and step.when.right in (None, ""):
                issues.append(
                    _issue(
                        step.id,
                        "when",
                        "BAD_CONDITION",
                        "Condition : valeur de comparaison manquante.",
                    )
                )

    order, cyclic = topo_order(steps)
    for step_id in sorted(cyclic):
        issues.append(
            _issue(
                step_id,
                "needs",
                "CYCLE",
                "Boucle dans les dépendances : une étape ne peut pas s'attendre elle-même.",
            )
        )

    for step in steps:
        upstream = ancestors(steps, step.id)
        cited: list[tuple[str | None, Ref]] = [(f or None, r) for f, r in refs_in(step.input)]
        if step.when is not None:
            cited += [("when", r) for _, r in refs_in(step.when.model_dump())]
        reported: set[tuple[str | None, str]] = set()
        for where, ref in cited:
            if (where, ref.raw) in reported:
                continue
            reported.add((where, ref.raw))
            if ref.kind == "invalid":
                issues.append(
                    _issue(
                        step.id, where, "BAD_TEMPLATE", f"Gabarit illisible : {{{{{ref.raw}}}}}."
                    )
                )
            elif ref.kind == "param" and ref.name not in declared:
                issues.append(
                    _issue(
                        step.id,
                        where,
                        "UNDECLARED_PARAM",
                        f"Paramètre non déclaré : « {ref.name} ».",
                    )
                )
            elif ref.kind == "step" and ref.name not in upstream:
                message = (
                    "Une étape ne peut pas citer sa propre sortie."
                    if ref.name == step.id
                    else f"« {ref.name} » n'est pas une étape amont : reliez-la avant de citer "
                    "sa sortie."
                )
                issues.append(_issue(step.id, where, "REF_NOT_ANCESTOR", message))

    return ValidationResult(ok=not issues, errors=issues, order=order if not issues else [])


def blocking(result: ValidationResult) -> list[ValidationIssue]:
    """Erreurs qui empêchent d'enregistrer (structure du graphe, étapes inconnues)."""
    return [e for e in result.errors if e.code not in SAVE_TOLERATED]
