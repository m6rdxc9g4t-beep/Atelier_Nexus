"""Gabarits `{{…}}` des workflows v2 (docs/workflows-v2-api.md §2).

| Gabarit | Valeur |
|---|---|
| `{{params.nom}}` ou `{{nom}}` (forme v1) | paramètre de lancement (texte) |
| `{{steps.<id>.data}}`, `{{steps.<id>.data.rows[0].titre}}` | sortie structurée, chemin `.champ` / `[n]` |
| `{{steps.<id>.content}}` | texte de l'étape |
| `{{steps.<id>.status}}` | `ok` / `error` / `refused` / `skipped` |
| `{{run.id}}` | identifiant de l'exécution |

Une valeur qui est exactement un gabarit garde le type JSON de sa cible ; un gabarit inclus dans
un texte devient du texte (JSON compact pour un objet ou une liste).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

TEMPLATE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
EXACT = re.compile(r"^\s*\{\{\s*([^{}]*?)\s*\}\}\s*$")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
PARAM = re.compile(r"^params\.([a-z][a-z0-9_]{0,39})$")
STEP = re.compile(
    r"^steps\.([a-z][a-z0-9_]{0,39})\.(data|content|status)((?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)$"
)
RUN = re.compile(r"^run\.(id)$")
PATH_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


@dataclass(frozen=True)
class Ref:
    kind: Literal["param", "step", "run", "invalid"]
    raw: str
    name: str = ""  # paramètre ou étape
    part: str = ""  # data | content | status (étape), id (exécution)
    path: tuple[str | int, ...] = ()


def parse_ref(expr: str) -> Ref:
    raw = expr.strip()
    if NAME.match(raw):
        return Ref("param", raw, name=raw)
    if m := PARAM.match(raw):
        return Ref("param", raw, name=m.group(1))
    if m := STEP.match(raw):
        if m.group(2) != "data" and m.group(3):
            return Ref("invalid", raw)  # pas de chemin dans un texte ni un statut
        path = tuple(
            int(t.group(2)) if t.group(2) is not None else t.group(1)
            for t in PATH_TOKEN.finditer(m.group(3))
        )
        return Ref("step", raw, name=m.group(1), part=m.group(2), path=path)
    if m := RUN.match(raw):
        return Ref("run", raw, part=m.group(1))
    return Ref("invalid", raw)


def strings_with_field(value: Any, field: str = "") -> Iterator[tuple[str, str]]:
    """(champ de premier niveau, texte) de chaque chaîne d'une valeur, récursivement."""
    if isinstance(value, str):
        yield field, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings_with_field(item, field or str(key))
    elif isinstance(value, list):
        for item in value:
            yield from strings_with_field(item, field)


def refs_in(value: Any) -> Iterator[tuple[str, Ref]]:
    """(champ de premier niveau, référence) de chaque gabarit cité dans une valeur."""
    for field, text in strings_with_field(value):
        for match in TEMPLATE.finditer(text):
            yield field, parse_ref(match.group(1))


def has_template(value: Any) -> bool:
    return any(TEMPLATE.search(text) for _, text in strings_with_field(value))


# ─── Résolution ───────────────────────────────────────────────────


class RefNotFoundError(LookupError):
    """Référence introuvable à l'exécution (étape sans sortie, chemin absent) → REF_NOT_FOUND."""


@dataclass
class StepOutcome:
    """Ce qu'une étape terminée expose aux suivantes."""

    status: str
    content: str
    data: Any


class Scope:
    """Valeurs citables par une étape : paramètres, sorties des ancêtres, exécution."""

    def __init__(
        self,
        params: Mapping[str, str],
        outcomes: Mapping[str, StepOutcome],
        run_id: str,
        ancestors: set[str] | None = None,
    ) -> None:
        self.params = params
        self.outcomes = outcomes
        self.run_id = run_id
        self.ancestors = ancestors

    def lookup(self, ref: Ref) -> Any:
        if ref.kind == "param":
            if ref.name not in self.params:
                raise RefNotFoundError(f"Paramètre « {ref.name} » non déclaré.")
            return self.params[ref.name]
        if ref.kind == "run":
            return self.run_id
        if ref.kind == "step":
            if self.ancestors is not None and ref.name not in self.ancestors:
                raise RefNotFoundError(f"« {ref.name} » n'est pas une étape amont.")
            outcome = self.outcomes.get(ref.name)
            if outcome is None:
                raise RefNotFoundError(f"L'étape « {ref.name} » n'a pas été exécutée.")
            if ref.part == "status":
                return outcome.status
            if ref.part == "content":
                return outcome.content
            if outcome.status != "ok":
                raise RefNotFoundError(
                    f"L'étape « {ref.name} » n'a pas de sortie (statut {outcome.status})."
                )
            return follow(outcome.data, ref.path, ref.raw)
        raise RefNotFoundError(f"Gabarit illisible : {{{{{ref.raw}}}}}.")


def follow(value: Any, path: tuple[str | int, ...], raw: str) -> Any:
    current = value
    for token in path:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise RefNotFoundError(f"{{{{{raw}}}}} : élément [{token}] introuvable.")
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise RefNotFoundError(f"{{{{{raw}}}}} : champ « {token} » introuvable.")
            current = current[token]
    return current


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def resolve(value: Any, scope: Scope) -> Any:
    """Remplace les gabarits d'une valeur (récursif). Lève `RefNotFoundError`."""
    if isinstance(value, str):
        exact = EXACT.match(value)
        if exact:
            return scope.lookup(parse_ref(exact.group(1)))
        return TEMPLATE.sub(lambda m: as_text(scope.lookup(parse_ref(m.group(1)))), value)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def exact_param_fields(raw_input: dict[str, Any]) -> set[str]:
    """Champs de premier niveau dont la valeur est exactement un paramètre (texte)."""
    out = set()
    for key, value in raw_input.items():
        if isinstance(value, str) and (m := EXACT.match(value)):
            if parse_ref(m.group(1)).kind == "param":
                out.add(key)
    return out


def coerce_params(
    resolved: dict[str, Any], raw_input: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Un paramètre est du texte : pour une action de nœud (JSON Schema strict), « 20 » devient
    20 si le champ attend un nombre, « true » devient vrai pour un booléen. Rien d'autre ne change."""
    props = schema.get("properties") or {}
    out = dict(resolved)
    for key in exact_param_fields(raw_input):
        value = out.get(key)
        expected = (props.get(key) or {}).get("type")
        if not isinstance(value, str) or expected is None:
            continue
        types = expected if isinstance(expected, list) else [expected]
        if "string" in types:
            continue
        text = value.strip()
        if "integer" in types and re.fullmatch(r"-?\d+", text):
            out[key] = int(text)
        elif "number" in types:
            try:
                out[key] = float(text) if not re.fullmatch(r"-?\d+", text) else int(text)
            except ValueError:
                pass
        elif "boolean" in types and text.lower() in ("true", "false", "oui", "non"):
            out[key] = text.lower() in ("true", "oui")
    return out


# ─── Conditions ───────────────────────────────────────────────────


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def evaluate(op: str, left: Any, right: Any = None) -> bool:
    """Condition `when` : comparaisons numériques quand les deux côtés sont des nombres
    (« 20 » compris), sinon textuelles."""
    if op == "empty":
        return _empty(left)
    if op == "not_empty":
        return not _empty(left)
    if op == "contains":
        if isinstance(left, list):
            return right in left or as_text(right) in [as_text(v) for v in left]
        if isinstance(left, dict):
            return as_text(right) in left
        return as_text(right) in as_text(left)
    ln, rn = _number(left), _number(right)
    if op in ("eq", "ne"):
        same = ln == rn if ln is not None and rn is not None else left == right
        if not same and not isinstance(left, dict | list) and not isinstance(right, dict | list):
            same = as_text(left) == as_text(right)
        return same if op == "eq" else not same
    if ln is not None and rn is not None:
        return _compare(op, ln, rn)
    return _compare(op, as_text(left), as_text(right))


def _compare[T: (float, str)](op: str, a: T, b: T) -> bool:
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "lt":
        return a < b
    return a <= b
