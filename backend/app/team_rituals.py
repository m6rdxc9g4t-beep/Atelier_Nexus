"""Rituels de l'équipe : workflows v2 sans modèle + déclencheurs horaires, installables en un clic.

Règles reprises des workflows et des déclencheurs (docs/declencheurs-api.md §0) : aucun appel de
modèle ; en `APPROVAL_MODE=every_step` chaque étape attend « Autoriser » dans la boîte « À
valider » ; au plus une exécution en attente par déclencheur. Un rituel installé est un workflow
et un déclencheur ordinaires : modifiables, désactivables, supprimables comme les autres.

Un rituel est reconnu installé par son titre (préfixe « Rituel · »).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings

PREFIX = "Rituel · "


@dataclass(frozen=True)
class Ritual:
    id: str
    title: str
    description: str
    #: Libellé lisible de l'horaire (« chaque lundi à 08:30 »)
    when: str
    workflow: dict[str, Any]
    trigger: dict[str, Any]
    #: Applications nécessaires : (réglage, nom affiché)
    needs: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def missing(self, settings: Settings) -> list[str]:
        return [label for attr, label in self.needs if not getattr(settings, attr)]


def _workflow(
    ritual_title: str, description: str, steps: list[dict[str, Any]], agent: str | None = None
) -> dict[str, Any]:
    return {
        "version": 2,
        "agent": agent,
        "title": PREFIX + ritual_title,
        "description": description,
        "steps": [{"label": "", "needs": [], "on_error": "stop", **s} for s in steps],
        "params": [],
    }


def _daily(at: str, days: list[str], label: str) -> dict[str, Any]:
    return {
        "kind": "schedule",
        "label": label,
        "enabled": True,
        "params": {},
        "max_runs_per_hour": 1,
        "schedule": {"kind": "daily", "at": at, "days": days},
    }


RITUALS: tuple[Ritual, ...] = (
    Ritual(
        id="point-lundi",
        title="Point d'avancement du lundi",
        description=(
            "Chaque lundi matin : point d'avancement calculé depuis Atelier Projets (retards, "
            "échéances, blocages, jalons), noté au journal de l'équipe dans le Wiki."
        ),
        when="chaque lundi à 08:30",
        workflow=_workflow(
            "Point d'avancement du lundi",
            "Point d'avancement de tous les projets, noté au journal de l'équipe (rituel de l'équipe).",
            [
                {
                    "id": "rapport",
                    "label": "Point d'avancement",
                    "uses": "tool:equipe_point_avancement",
                    "input": {"horizon_jours": 7},
                },
                {
                    "id": "journal",
                    "label": "Note au journal",
                    "uses": "tool:equipe_noter",
                    "needs": ["rapport"],
                    "input": {
                        "texte": "{{steps.rapport.content}}",
                        "auteur": "Rituel du lundi",
                        "titre": "Point d'avancement",
                    },
                },
            ],
        ),  # fmt: skip
        trigger=_daily("08:30", ["mon"], "Chaque lundi, 08:30"),
        needs=(("projets_base_url", "Atelier Projets"), ("wiki_base_url", "Atelier Wiki")),
    ),
    Ritual(
        id="retours-vendredi",
        title="Retours des formulaires du vendredi",
        description=(
            "Chaque vendredi après-midi : synthèse agrégée des formulaires ouverts (sans aucune "
            "réponse individuelle), notée au journal de l'équipe s'il y en a."
        ),
        when="chaque vendredi à 16:00",
        workflow=_workflow(
            "Retours des formulaires du vendredi",
            "Synthèse agrégée des formulaires ouverts, notée au journal de l'équipe (rituel de l'équipe).",
            [
                {
                    "id": "synthese",
                    "label": "Synthèse des formulaires",
                    "uses": "tool:equipe_synthese_formulaires",
                    "input": {},
                },
                {
                    "id": "journal",
                    "label": "Note au journal",
                    "uses": "tool:equipe_noter",
                    "needs": ["synthese"],
                    "when": {"left": "{{steps.synthese.data.forms}}", "op": "not_empty"},
                    "input": {
                        "texte": "{{steps.synthese.content}}",
                        "auteur": "Rituel du vendredi",
                        "titre": "Retours des formulaires",
                    },
                },
            ],
        ),  # fmt: skip
        trigger=_daily("16:00", ["fri"], "Chaque vendredi, 16:00"),
        needs=(("formulaire_base_url", "Atelier Formulaire"), ("wiki_base_url", "Atelier Wiki")),
    ),
    Ritual(
        id="tresorerie-lundi",
        title="Bilan de trésorerie du lundi",
        description=(
            "Chaque lundi : synthèse d'Atelier Trésorerie (patrimoine, revenus, dépenses, épargne), "
            "consultable dans l'exécution du workflow. Rien n'est écrit ailleurs : les données "
            "restent sur la machine."
        ),
        when="chaque lundi à 08:00",
        workflow=_workflow(
            "Bilan de trésorerie du lundi",
            "Synthèse d'Atelier Trésorerie, gardée dans l'exécution (rituel de l'équipe, données locales).",
            [
                {
                    "id": "bilan",
                    "label": "Synthèse de trésorerie",
                    "uses": "tool:tresorerie_dashboard",
                    "input": {},
                }
            ],
            agent="finance",
        ),  # fmt: skip
        trigger=_daily("08:00", ["mon"], "Chaque lundi, 08:00"),
        needs=(("tresorerie_base_url", "Atelier Trésorerie"),),
    ),
)


def ritual(ritual_id: str) -> Ritual | None:
    return next((r for r in RITUALS if r.id == ritual_id), None)


def installed(
    titles: dict[str, str], key: Callable[[Ritual], str] = lambda r: PREFIX + r.title
) -> dict[str, str]:
    """Rituel → identifiant du workflow installé (reconnu par son titre)."""
    return {r.id: titles[key(r)] for r in RITUALS if key(r) in titles}
