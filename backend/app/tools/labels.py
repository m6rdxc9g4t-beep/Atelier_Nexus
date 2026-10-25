"""Libellés lisibles des outils et résumé par défaut d'un appel (carte de validation).

En `APPROVAL_MODE=every_step`, chaque appel d'outil (lectures comprises) est montré à
l'utilisateur avant d'être exécuté : le résumé doit se lire sans connaître le nom technique.
Les noms ci-dessous sont les mêmes que dans l'interface (`ToolCall.tsx`).
"""

from __future__ import annotations

import re
from typing import Any

TOOL_LABELS: dict[str, str] = {
    "current_datetime": "Date et heure",
    "publish_artifact": "Publication d'un artefact",
    "data_via_list_datasets": "Data Via · jeux de données",
    "data_via_describe_dataset": "Data Via · schéma",
    "data_via_query": "Data Via · requête",
    "data_via_rows": "Data Via · lignes",
    "data_via_check_expression": "Data Via · vérification de mesure",
    "data_via_check_relation": "Data Via · vérification de relation",
    "projets_list_projects": "Projets · liste",
    "projets_dashboard": "Projets · tableau de bord",
    "projets_structure": "Projets · arborescence",
    "projets_list_work_items": "Projets · éléments",
    "projets_work_item": "Projets · détail d'un élément",
    "projets_timesheet": "Projets · feuille de temps",
    "projets_milestones": "Projets · jalons",
    "projets_create_story": "Projets · création d'une story",
    "projets_create_work_item": "Projets · création d'un élément",
    "projets_update_work_item": "Projets · modification d'un élément",
    "projets_add_time_entry": "Projets · saisie de temps",
    "projets_add_log_entry": "Projets · journal d'avancement",
    "tresorerie_dashboard": "Trésorerie · synthèse",
    "tresorerie_accounts": "Trésorerie · comptes",
    "tresorerie_categories": "Trésorerie · catégories",
    "tresorerie_transactions": "Trésorerie · opérations",
    "tresorerie_budgets": "Trésorerie · budgets",
    "tresorerie_goals": "Trésorerie · objectifs",
    "tresorerie_holdings": "Trésorerie · placements",
    "tresorerie_category_totals": "Trésorerie · totaux par catégorie",
    "tab_list_tables": "Tab · tables",
    "tab_read_table": "Tab · lecture d'une table",
    "tab_aggregate": "Tab · totaux",
    "tab_check_table": "Tab · contrôle",
    "tab_set_cells": "Tab · modification de cellules",
    "tab_add_rows": "Tab · ajout de lignes",
    "tab_delete_rows": "Tab · suppression de lignes",
    "tab_add_column": "Tab · ajout d'une colonne",
    "tab_create_table": "Tab · création d'une table",
    "projets_preview_tab_import": "Projets · aperçu de l'import Tab",
    "projets_import_tab_table": "Projets · import d'une table Tab",
    "cine_library": "Ciné · médiathèque",
    "cine_title": "Ciné · fiche",
    "cine_library_report": "Ciné · bilan",
    "cine_ai_summary": "Ciné · synopsis (IA locale)",
    "savoir_overview": "Savoir · vue d'ensemble",
    "savoir_course": "Savoir · cours",
    "savoir_chapter": "Savoir · chapitre",
    "savoir_flashcards": "Savoir · cartes",
    "savoir_due_cards": "Savoir · séance du jour",
    "cuisine_stock": "Cuisine · stock",
    "cuisine_meal_plan": "Cuisine · planning des repas",
    "cuisine_shopping_list": "Cuisine · liste de courses",
    "cuisine_budget": "Cuisine · budget du mois",
    "github_repo_overview": "GitHub · dépôt",
    "github_list_files": "GitHub · fichiers",
    "github_read_file": "GitHub · lecture d'un fichier",
    "github_search_code": "GitHub · recherche de code",
    "github_list_pull_requests": "GitHub · pull requests",
    "github_pull_request": "GitHub · détail d'une pull request",
    "github_list_issues": "GitHub · tickets",
    "github_create_branch": "GitHub · création de branche",
    "github_edit_file": "GitHub · modification d'un fichier",
    "github_commit_files": "GitHub · commit",
    "github_open_pull_request": "GitHub · pull request",
    "delegate_to_agent": "Délégation à un agent",
}

#: Paramètres montrés dans le résumé par défaut (les autres sont comptés)
MAX_SHOWN = 4
MAX_VALUE = 60


def short_label(description: str) -> str:
    """Libellé court d'un outil : début de sa description (« Liste les projets… »)."""
    first = re.split(r"(?<=[a-zé])\. | : |\(", description, maxsplit=1)[0].strip().rstrip(".")
    return first if len(first) <= 70 else first[:69].rstrip() + "…"


def tool_label(name: str, description: str = "") -> str:
    """Nom lisible d'un outil : libellé connu, sinon début de sa description, sinon son nom."""
    return TOOL_LABELS.get(name) or (short_label(description) if description else "") or name


def short_value(value: Any) -> str:
    """Valeur d'un paramètre en quelques mots : texte tronqué, listes et objets résumés."""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, str):
        text = " ".join(value.split())
        return f"« {text[: MAX_VALUE - 1]}… »" if len(text) > MAX_VALUE else f"« {text} »"
    if isinstance(value, list):
        return f"{len(value)} élément(s)"
    if isinstance(value, dict):
        return f"{len(value)} champ(s)"
    return str(value)


def default_summary(label: str, params: dict[str, Any]) -> str:
    """« Data Via · requête : dataset = « ventes », limit = 50 (+2 autres) »."""
    shown = [(k, v) for k, v in params.items() if v not in (None, "", [], {})]
    if not shown:
        return label
    parts = ", ".join(f"{k} = {short_value(v)}" for k, v in shown[:MAX_SHOWN])
    more = f" (+{len(shown) - MAX_SHOWN} autre(s))" if len(shown) > MAX_SHOWN else ""
    return f"{label} : {parts}{more}"
