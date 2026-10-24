"""Identité des applications de la suite : nom affiché et couleur signature (docs/SUITE.md §1.7)."""

from __future__ import annotations

NEXUS_COLOR = "#E8590C"

APP_COLORS: dict[str, str] = {
    "viz": "#F2C811",
    "tab": "#21A366",
    "projets": "#94D82D",
    "nexus": NEXUS_COLOR,
    "cine": "#E64980",
    "savoir": "#9B5DE5",
    "tresorerie": "#3B5BDB",
    "cuisine": "#E056E2",
    "dates": "#E03131",
    "wiki": "#4DABF7",
    "formulaire": "#38D9A9",
    "convert": "#C9951D",
}

APP_NAMES: dict[str, str] = {
    "viz": "Atelier Viz",
    "tab": "Atelier Tab",
    "projets": "Atelier Projets",
    "nexus": "Atelier Nexus",
    "cine": "Atelier Ciné",
    "savoir": "Atelier Savoir",
    "tresorerie": "Atelier Trésorerie",
    "cuisine": "Atelier Cuisine",
    "dates": "Atelier Dates",
    "wiki": "Atelier Wiki",
    "formulaire": "Atelier Formulaire",
    "convert": "Atelier Convert",
    "github": "GitHub",
}

#: Applications qui implémentent le contrat `atelier-node/1`
NODE_APPS = ("viz", "tab", "projets", "wiki", "formulaire", "convert")


def app_color(app: str | None) -> str:
    """Couleur d'une application ; outil système (None) ou application hors liste → Nexus."""
    return APP_COLORS.get(app or "nexus", NEXUS_COLOR)


def app_name(app: str) -> str:
    return APP_NAMES.get(app, app)
