"""Événements des déclencheurs : lecture d'un chemin, filtres, gabarits `{{event.…}}` (pur).

Chemins : `type`, `seq`, `at`, `subject.id`, `subject.label`, `subject.kind`, `data.<chemin>`
(`.champ`, `[n]`). Un chemin absent vaut « absent » pour les filtres et `""` dans un gabarit.
Les gabarits sont résolus en **texte** : les paramètres d'un workflow sont du texte.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.schemas.triggers import EventFilter
from app.workflows_v2.templates import TEMPLATE, as_text, evaluate

#: Expression d'un gabarit d'événement (sans les accolades)
EVENT_REF = re.compile(
    r"^event\.(type|seq|at|subject\.(?:id|label|kind)|data(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+)$"
)
EVENT_MENTION = re.compile(r"\{\{\s*event\b")
TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


class _Missing:
    def __repr__(self) -> str:
        return "<absent>"


MISSING: Any = _Missing()


def event_value(event: Mapping[str, Any], path: str) -> Any:
    """Valeur d'un chemin de l'événement, ou `MISSING`."""
    current: Any = event
    for name, index in TOKEN.findall(path):
        if index:
            position = int(index)
            if not isinstance(current, list) or position >= len(current):
                return MISSING
            current = current[position]
        else:
            if not isinstance(current, Mapping) or name not in current:
                return MISSING
            current = current[name]
    return current


def matches(filters: Iterable[EventFilter], event: Mapping[str, Any]) -> bool:
    """Toutes les conditions doivent être vraies. Chemin absent : seul `ne` est vrai."""
    for item in filters:
        value = event_value(event, item.path)
        if item.op == "exists":
            ok = value is not MISSING and value is not None
        elif value is MISSING:
            ok = item.op == "ne"
        elif item.op == "in":
            ok = any(evaluate("eq", value, choice) for choice in item.value or [])
        else:
            ok = evaluate(item.op, value, item.value)
        if not ok:
            return False
    return True


def _text(value: Any) -> str:
    if value is MISSING:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return as_text(value)


def render(text: str, event: Mapping[str, Any]) -> str:
    """Remplace les gabarits `{{event.…}}` d'un texte par les valeurs de l'événement."""

    def one(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if not EVENT_REF.match(expr):
            return match.group(0)  # refusé à l'enregistrement : laissé tel quel
        return _text(event_value(event, expr.removeprefix("event.")))

    return TEMPLATE.sub(one, text)


def render_params(params: Mapping[str, str], event: Mapping[str, Any] | None) -> dict[str, str]:
    """Paramètres d'un lancement : gabarits résolus (sans événement : chemins absents → "")."""
    return {name: render(value, event or {}) for name, value in params.items()}


def template_problems(params: Mapping[str, str], *, allow_event: bool) -> list[str]:
    """Gabarits refusés dans les paramètres d'un déclencheur (messages en français)."""
    problems: list[str] = []
    for name, value in params.items():
        for match in TEMPLATE.finditer(value):
            expr = match.group(1).strip()
            if not expr.startswith("event."):
                problems.append(
                    f"Paramètre « {name} » : seuls les gabarits {{{{event.…}}}} sont permis "
                    f"dans un déclencheur ({{{{{expr}}}}})."
                )
            elif not allow_event:
                problems.append(
                    f"Paramètre « {name} » : les gabarits {{{{event.…}}}} sont réservés aux "
                    "déclencheurs sur événement."
                )
            elif not EVENT_REF.match(expr):
                problems.append(
                    f"Paramètre « {name} » : gabarit {{{{{expr}}}}} illisible (attendu : "
                    "event.type, event.seq, event.at, event.subject.id|label|kind ou "
                    "event.data.<chemin>)."
                )
    return problems


def mentions_event(value: Any) -> bool:
    """Un texte (ou une valeur composée) cite-t-il `{{event…}}` ?"""
    if isinstance(value, str):
        return bool(EVENT_MENTION.search(value))
    if isinstance(value, dict):
        return any(mentions_event(v) for v in value.values())
    if isinstance(value, list):
        return any(mentions_event(v) for v in value)
    return False
