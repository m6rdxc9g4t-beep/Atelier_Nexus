"""Identité des applications de la suite : nom affiché et couleur signature (docs/SUITE.md §1.7,
charte v2 « Linear » : mêmes valeurs que `--atelier-sig-*` de la marque commune)."""

from __future__ import annotations

NEXUS_COLOR = "#c84f00"

APP_COLORS: dict[str, str] = {
    "viz": "#996c00",
    "tab": "#1c8742",
    "projets": "#568100",
    "nexus": NEXUS_COLOR,
    "cine": "#cd3d83",
    "savoir": "#a853c1",
    "tresorerie": "#3c72da",
    "cuisine": "#8568a7",
    "dates": "#db373a",
    "convert": "#9d6d1c",
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
    "convert": "Atelier Convert",
    "github": "GitHub",
}

#: Applications qui implémentent le contrat `atelier-node/1` (ordre de la carte et du catalogue)
NODE_APPS = ("viz", "tab", "projets", "convert")

#: Nœuds joints en HTTP : app → (attribut de `Settings` qui donne l'adresse, clé du transport
#: simulé en test). Tab passe par ses fichiers et son serveur MCP (`app/suite/nodes.py`).
#: Clé « convert » : la même que le client de l'extension Agent_DatAnalyst (un seul double).
HTTP_NODES: dict[str, tuple[str, str]] = {
    "viz": ("data_via_base_url", "data_via"),
    "projets": ("projets_base_url", "projets"),
    "convert": ("convert_base_url", "convert"),
}


def app_color(app: str | None) -> str:
    """Couleur d'une application ; outil système (None) ou application hors liste → Nexus."""
    return APP_COLORS.get(app or "nexus", NEXUS_COLOR)


def app_name(app: str) -> str:
    return APP_NAMES.get(app, app)
