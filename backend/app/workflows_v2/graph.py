"""Graphe des étapes (arêtes `needs`) : ordre topologique stable, cycles, ancêtres."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.workflows_v2 import WorkflowStepV2


def topo_order(steps: Sequence[WorkflowStepV2]) -> tuple[list[str], set[str]]:
    """(ordre d'exécution, étapes prises dans un cycle). À égalité, l'ordre de déclaration.
    Les `needs` inconnus sont ignorés ici (signalés par la validation)."""
    ids = [s.id for s in steps]
    known = set(ids)
    pending = {s.id: {n for n in s.needs if n in known and n != s.id} for s in steps}
    for s in steps:
        if s.id in s.needs:
            pending[s.id].add(s.id)  # dépendance à soi-même : cycle
    order: list[str] = []
    done: set[str] = set()
    progressed = True
    while progressed:
        progressed = False
        for step_id in ids:
            if step_id not in done and pending[step_id] <= done:
                order.append(step_id)
                done.add(step_id)
                progressed = True
                break  # repart du début : ordre de déclaration à égalité
    cyclic = known - done
    return order, cyclic


def ancestors(steps: Sequence[WorkflowStepV2], step_id: str) -> set[str]:
    """Étapes amont d'une étape, transitivement (elle-même exclue)."""
    needs = {s.id: list(s.needs) for s in steps}
    seen: set[str] = set()
    stack = list(needs.get(step_id, []))
    while stack:
        current = stack.pop()
        if current in seen or current not in needs:
            continue
        seen.add(current)
        stack.extend(needs[current])
    seen.discard(step_id)
    return seen
