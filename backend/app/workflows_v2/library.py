"""Bibliothèque de modèles de workflows de la suite (`GET /api/workflows/library`).

Données et logique pure : chaque modèle enchaîne des actions des nœuds (`node:<app>/<action>`)
et des outils Nexus (`tool:<nom>`) de Convert, Tab, Viz et Projets, avec des identifiants et des
champs RELEVÉS dans les vrais manifestes (validés par `tests/test_workflow_library.py` contre
les manifestes enregistrés dans `tests/fixtures/<app>/manifest.json`).

- Un modèle n'est jamais exécuté tel quel : l'interface le copie dans un brouillon que
  l'utilisateur relit, enregistre puis lance ; chaque étape attend sa validation
  (`APPROVAL_MODE=every_step`), écritures comprises.
- `available` / `missing` sont calculés avec le registre d'étapes de l'environnement réel
  (`StepRegistry`) : étape inconnue, boîte non configurée ou application injoignable sont dites
  en clair (« node:convert/conversions.list : Atelier Convert injoignable »). Rien ici ne
  lève pour une application arrêtée.
- Aucun modèle ne demande de fichier en base64 (`conversions.convert_file`) : un relevé se
  convertit dans Convert, le workflow part de l'historique des conversions.
- Positions de l'éditeur en couches, de gauche à droite (même mise en page que
  `layoutSteps` du frontend : colonnes de 300 px, lignes de 130 px, colonnes centrées).
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.workflows import WorkflowParam
from app.schemas.workflows_v2 import (
    StepPosition,
    WorkflowStepV2,
    WorkflowTemplate,
    WorkflowV2Fields,
)
from app.suite.apps import HTTP_NODES
from app.tools.toolsets import get_toolset
from app.workflows_v2.graph import topo_order
from app.workflows_v2.steps import StepProblem, StepRegistry, parse_uses
from app.workflows_v2.validation import validate_workflow

logger = logging.getLogger(__name__)

COLUMN_WIDTH = 300
ROW_HEIGHT = 130
#: Codes déjà dits par la ligne de l'étape (`missing` : une ligne par étape manquante)
_LOOKUP_CODES = {"UNKNOWN_USES", "UNAVAILABLE", "NOT_REPLAYABLE"}
#: `missing` d'un modèle que la validation n'a pas pu vérifier (exception inattendue)
UNCHECKED = (
    "Vérification impossible sur cette machine : le manifeste d'une application de ce modèle "
    "est inattendu (mettez l'application à jour)."
)


# ─── Construction ─────────────────────────────────────────────────


def _param(name: str, label: str, default: str = "") -> WorkflowParam:
    return WorkflowParam(name=name, label=label, default=default)


def _step(
    step_id: str,
    uses: str,
    label: str,
    input: dict[str, Any],
    needs: list[str] | None = None,
    **extra: Any,
) -> WorkflowStepV2:
    return WorkflowStepV2(
        id=step_id, uses=uses, label=label, input=input, needs=needs or [], **extra
    )


def _rows_present(step_id: str) -> dict[str, Any]:
    """Condition « la table de l'étape a au moins une ligne »."""
    return {"left": f"{{{{steps.{step_id}.data.rows}}}}", "op": "not_empty"}


def layered(steps: list[WorkflowStepV2]) -> list[WorkflowStepV2]:
    """Positions en couches : chaque étape dans la colonne « plus long chemin depuis une
    racine », les colonnes centrées verticalement (comme `layoutSteps` de l'éditeur)."""
    order, _ = topo_order(steps)
    by_id = {s.id: s for s in steps}
    layer: dict[str, int] = {}
    for step_id in order:
        needs = [n for n in by_id[step_id].needs if n in layer]
        layer[step_id] = max(layer[n] for n in needs) + 1 if needs else 0
    columns: list[list[str]] = []
    for step_id in order:
        while len(columns) <= layer[step_id]:
            columns.append([])
        columns[layer[step_id]].append(step_id)
    tallest = max((len(c) for c in columns), default=0)
    positions: dict[str, StepPosition] = {}
    for x, column in enumerate(columns):
        offset = (tallest - len(column)) * ROW_HEIGHT / 2
        for y, step_id in enumerate(column):
            positions[step_id] = StepPosition(x=x * COLUMN_WIDTH, y=offset + y * ROW_HEIGHT)
    return [s.model_copy(update={"position": positions.get(s.id)}) for s in steps]


def _template(**fields: Any) -> WorkflowTemplate:
    fields["steps"] = layered(fields["steps"])
    return WorkflowTemplate(**fields)


# ─── Modèles ──────────────────────────────────────────────────────

#: Prérequis communs, en clair
CONVERT = "Atelier Convert lancé (API locale sur le port 8010, CONVERT_BASE_URL)"
VIZ = "Atelier Viz lancé (DATA_VIA_BASE_URL)"
PROJETS = "Atelier Projets lancé (PROJETS_BASE_URL)"
TAB_MCP = "TAB_MCP_COMMAND (serveur MCP de Tab) pour lire et écrire les tables d'Atelier Tab"
TAB_FILES = "Instantané de la table publié par Atelier Tab (TAB_EXPORTS_DIR)"
IMPORT_TOKEN = "PROJETS_IMPORT_TOKEN si l'import depuis Atelier Tab est protégé dans Projets"
LIMIT_1000 = (
    "1 000 lignes au plus passent d'une étape à l'autre : au-delà, le jeu Viz est partiel "
    "(préférez alors une connexion directe dans Viz)"
)

TEMPLATES: tuple[WorkflowTemplate, ...] = (
    _template(
        slug="convert-derniere-conversion-tab-viz",
        title="Dernière conversion Convert → Tab → Viz",
        description=(
            "Prend la conversion la plus récemment modifiée dans Atelier Convert, l'envoie comme "
            "nouvelle table dans un projet Atelier Tab, la publie comme jeu Atelier Viz (un jeu "
            "par conversion, mis à jour au renvoi) puis calcule les débits et crédits par mois."
        ),
        value=(
            "Après avoir vérifié un relevé dans Convert, un seul lancement le range dans Tab et "
            "met à jour le tableau de bord, sans ressaisie."
        ),
        apps=["convert", "tab", "viz"],
        params=[_param("projet_tab", "Projet Atelier Tab qui reçoit la table (id proj_…)")],
        steps=[
            _step(
                "historique",
                "node:convert/conversions.list",
                "Historique des conversions",
                {},
            ),
            _step(
                "vers_tab",
                "node:convert/conversions.send_to_tab",
                "Envoyer la dernière conversion dans Tab",
                {
                    "conversion_id": "{{steps.historique.data[0].id}}",
                    "project_id": "{{params.projet_tab}}",
                    "table_name": "{{steps.historique.data[0].name}}",
                },
                ["historique"],
                when={"left": "{{steps.historique.data}}", "op": "not_empty"},
            ),
            _step(
                "lignes",
                "node:convert/conversions.table",
                "Lire les lignes de la conversion",
                {"conversion_id": "{{steps.historique.data[0].id}}", "limit": 1000},
                ["historique"],
                when={"left": "{{steps.historique.data}}", "op": "not_empty"},
            ),
            _step(
                "vers_viz",
                "node:viz/datasets.upsert_table",
                "Publier le jeu dans Atelier Viz",
                {
                    "name": "{{steps.historique.data[0].name}}",
                    "key": "convert:{{steps.historique.data[0].id}}",
                    "table": "{{steps.lignes.data}}",
                },
                ["lignes"],
            ),
            _step(
                "par_mois",
                "node:viz/datasets.query",
                "Débits et crédits par mois",
                {
                    "dataset_id": "{{steps.vers_viz.data.dataset_id}}",
                    "dimensions": [{"field": "Date", "bin": "month"}],
                    "measures": [
                        {"field": "Débit", "agg": "sum"},
                        {"field": "Crédit", "agg": "sum"},
                    ],
                },
                ["vers_viz"],
                on_error="continue",
            ),
        ],
        requirements=[
            CONVERT,
            VIZ,
            "Une conversion dans l'historique de Convert ; les colonnes Date, Débit et Crédit "
            "n'existent que pour un relevé bancaire reconnu (sinon la dernière étape échoue sans "
            "arrêter l'exécution)",
            "Projet Atelier Tab existant (id proj_…) : Convert écrit la table dans le dossier de "
            "données de Tab, sans serveur MCP",
            LIMIT_1000,
        ],
        trigger_hint=(
            "Manuel, après avoir vérifié la conversion dans Convert. Chaque lancement crée une "
            "nouvelle table dans Tab."
        ),
    ),
    _template(
        slug="convert-releve-budget-tab-viz",
        title="Relevé converti → budget consolidé Tab → Viz",
        description=(
            "Ajoute les opérations d'une conversion à la table de budget d'Atelier Tab, relit "
            "toute la table, remplace les données du jeu Viz du budget (rapports et visuels "
            "conservés) puis calcule les dépenses et recettes par mois."
        ),
        value=(
            "Un seul budget cumulé mois après mois dans Tab (modifiable, avec formules) et un "
            "tableau de bord Viz toujours à jour."
        ),
        apps=["convert", "tab", "viz"],
        params=[
            _param("conversion", "Conversion à ajouter (12 caractères hexadécimaux)"),
            _param("table_budget", "Table Tab du budget (id ou nom exact)", "Relevés"),
            _param("cle_viz", "Clé du jeu Viz du budget", "nexus:budget-releves"),
        ],
        steps=[
            _step(
                "lire",
                "node:convert/conversions.table",
                "Lire les opérations de la conversion",
                {"conversion_id": "{{params.conversion}}", "limit": 1000},
            ),
            _step(
                "ajouter",
                "node:tab/rows.add",
                "Ajouter les opérations au budget",
                {"table": "{{params.table_budget}}", "rows": "{{steps.lire.data.rows}}"},
                ["lire"],
                when=_rows_present("lire"),
            ),
            _step(
                "relire",
                "node:tab/tables.query",
                "Relire le budget complet",
                {"table": "{{params.table_budget}}", "limit": 1000},
                ["ajouter"],
            ),
            _step(
                "publier",
                "node:viz/datasets.upsert_table",
                "Mettre à jour le jeu Viz du budget",
                {
                    "name": "Budget — relevés consolidés",
                    "key": "{{params.cle_viz}}",
                    "table": "{{steps.relire.data}}",
                },
                ["relire"],
            ),
            _step(
                "par_mois",
                "node:viz/datasets.query",
                "Dépenses et recettes par mois",
                {
                    "dataset_id": "{{steps.publier.data.dataset_id}}",
                    "dimensions": [{"field": "Date", "bin": "month"}],
                    "measures": [
                        {"field": "Débit", "agg": "sum"},
                        {"field": "Crédit", "agg": "sum"},
                    ],
                },
                ["publier"],
                on_error="continue",
            ),
        ],
        requirements=[
            CONVERT,
            TAB_MCP,
            VIZ,
            "Table de budget dans Tab avec les colonnes Date, Libellé, Débit, Crédit et Montant "
            "(retrouvées par leur libellé, casse et accents ignorés) ; une autre colonne de la "
            "conversion (Solde, Date de valeur) doit exister aussi ou être exclue dans Convert",
            "Une conversion n'est ajoutée qu'une fois : relancer avec la même conversion "
            "ajouterait les lignes en double",
            LIMIT_1000,
        ],
        trigger_hint=(
            "Manuel, une fois par relevé. Possible : événement convert.conversion.created filtré "
            "sur data.statement égal à vrai, avec le paramètre conversion = {{event.subject.id}}."
        ),
    ),
    _template(
        slug="tab-planning-vers-projets",
        title="Planning Tab → tâches Projets",
        description=(
            "Contrôle une table de planning d'Atelier Tab, montre l'aperçu de l'import dans "
            "Atelier Projets (éléments à créer, mettre à jour ou ignorer), importe les lignes en "
            "éléments de travail, puis liste les tâches ouvertes et les jalons du projet."
        ),
        value=(
            "Le planning saisi comme dans un tableur devient des tâches suivies dans Projets, "
            "sans doublon au réimport, après relecture de l'aperçu."
        ),
        apps=["tab", "projets"],
        params=[
            _param(
                "table", "Table de planning Tab (id, ex. tbl_planning_lots)", "tbl_planning_lots"
            ),
            _param("projet", "Projet cible dans Atelier Projets (n°)"),
            _param("type", "Type des éléments créés (FEATURE, TASK ou BUG)", "TASK"),
        ],
        steps=[
            _step(
                "controle",
                "tool:tab_check_table",
                "Contrôler la table avant l'import",
                {"table_id": "{{params.table}}"},
            ),
            _step(
                "apercu",
                "tool:projets_preview_tab_import",
                "Aperçu de l'import (rien n'est modifié)",
                {
                    "table_id": "{{params.table}}",
                    "project_id": "{{params.projet}}",
                    "type": "{{params.type}}",
                },
                ["controle"],
            ),
            _step(
                "importer",
                "tool:projets_import_tab_table",
                "Créer ou mettre à jour les éléments",
                {
                    "table_id": "{{params.table}}",
                    "project_id": "{{params.projet}}",
                    "type": "{{params.type}}",
                },
                ["apercu"],
                when={"left": "{{steps.apercu.data.items}}", "op": "not_empty"},
            ),
            _step(
                "a_faire",
                "node:projets/work_items.list",
                "Tâches ouvertes du projet",
                {
                    "project_id": "{{params.projet}}",
                    "status": ["OPEN", "IN_PROGRESS", "ON_HOLD", "BLOCKED"],
                },
                ["importer"],
                on_error="continue",
            ),
            _step(
                "jalons",
                "node:projets/milestones.list",
                "Jalons du projet",
                {"project_id": "{{params.projet}}"},
                ["importer"],
                on_error="continue",
            ),
        ],
        requirements=[
            TAB_FILES,
            PROJETS,
            "Une colonne au rôle « titre » (entity_title) renseignée sur chaque ligne : le "
            "contrôle le signale",
            IMPORT_TOKEN,
        ],
        trigger_hint=(
            "Manuel de préférence : relisez l'aperçu avant d'autoriser l'import. Possible : "
            "événement tab.table.changed, filtre subject.id égal à l'id de la table, « Regrouper "
            "les rafales » 600 s, paramètre table = {{event.subject.id}}."
        ),
    ),
    _template(
        slug="projets-temps-hebdo-viz",
        title="Temps passés Projets → jeux Viz hebdomadaires",
        description=(
            "Lit les saisies de temps et les éléments de travail de tous les projets d'Atelier "
            "Projets, remplace les données de deux jeux Atelier Viz, puis calcule les heures par "
            "semaine et par projet, et l'estimé, le passé et l'écart par projet."
        ),
        value=(
            "Le tableau de bord de charge et de dérive du budget se met à jour chaque lundi, "
            "pour facturer ou recadrer à temps."
        ),
        apps=["projets", "viz"],
        params=[
            _param("cle_temps", "Clé du jeu Viz des temps passés", "nexus:temps-passes"),
            _param("cle_elements", "Clé du jeu Viz des éléments", "nexus:elements-projets"),
        ],
        steps=[
            _step(
                "temps",
                "node:projets/tables.get",
                "Saisies de temps (tous projets)",
                {"name": "time-entries"},
            ),
            _step(
                "elements",
                "node:projets/tables.get",
                "Éléments de travail (tous projets)",
                {"name": "work-items"},
            ),
            _step(
                "publier_temps",
                "node:viz/datasets.upsert_table",
                "Jeu Viz « Temps passés »",
                {
                    "name": "Temps passés (Projets)",
                    "key": "{{params.cle_temps}}",
                    "table": "{{steps.temps.data}}",
                },
                ["temps"],
                when=_rows_present("temps"),
            ),
            _step(
                "publier_elements",
                "node:viz/datasets.upsert_table",
                "Jeu Viz « Éléments de travail »",
                {
                    "name": "Éléments de travail (Projets)",
                    "key": "{{params.cle_elements}}",
                    "table": "{{steps.elements.data}}",
                },
                ["elements"],
                when=_rows_present("elements"),
            ),
            _step(
                "par_semaine",
                "node:viz/datasets.query",
                "Heures par semaine et par projet",
                {
                    "dataset_id": "{{steps.publier_temps.data.dataset_id}}",
                    "dimensions": [{"field": "Date", "bin": "week"}, {"field": "Projet"}],
                    "measures": [{"field": "Heures", "agg": "sum"}],
                    "limit": 500,
                },
                ["publier_temps"],
                on_error="continue",
            ),
            _step(
                "ecarts",
                "node:viz/datasets.query",
                "Estimé, passé et écart par projet",
                {
                    "dataset_id": "{{steps.publier_elements.data.dataset_id}}",
                    "dimensions": [{"field": "Projet"}],
                    "measures": [
                        {"field": "Heures estimées", "agg": "sum"},
                        {"field": "Heures passées", "agg": "sum"},
                        {"field": "Écart (heures)", "agg": "sum"},
                    ],
                },
                ["publier_elements"],
                on_error="continue",
            ),
        ],
        requirements=[PROJETS, VIZ, LIMIT_1000],
        trigger_hint=(
            "Horaire : chaque lundi à 08:00 (« À heure fixe », jour : lundi). Lancées par "
            "l'horaire, les étapes attendent quand même votre validation."
        ),
    ),
    _template(
        slug="tab-controle-qualite-projets",
        title="Contrôle qualité d'une table Tab → journal et tâche Projets",
        description=(
            "Contrôle une table d'Atelier Tab (erreurs de formule, titres vides ou en double, "
            "échéances dépassées, responsables manquants), consigne le rapport dans le journal "
            "d'un élément de suivi d'Atelier Projets et crée une tâche de correction s'il reste "
            "des lignes sans titre."
        ),
        value=(
            "Les tableaux restent propres avant un import ou un rendu, avec un historique daté "
            "des contrôles et une tâche quand il faut corriger."
        ),
        apps=["tab", "projets"],
        params=[
            _param("table", "Table Tab à contrôler (id)", "tbl_planning_lots"),
            _param("colonne_titre", "Colonne du titre (libellé, lettre ou clé)", "Titre"),
            _param("element_suivi", "Élément Projets qui garde l'historique (n°)"),
            _param("story", "Story Projets des tâches de correction (n°)"),
        ],
        steps=[
            _step(
                "controle",
                "tool:tab_check_table",
                "Contrôle de la table",
                {"table_id": "{{params.table}}"},
            ),
            _step(
                "sans_titre",
                "node:tab/tables.query",
                "Lignes sans titre",
                {
                    "table": "{{params.table}}",
                    "columns": ["{{params.colonne_titre}}"],
                    "filters": [{"column": "{{params.colonne_titre}}", "op": "empty"}],
                    "limit": 1000,
                },
            ),
            _step(
                "historique",
                "node:projets/work_items.log",
                "Consigner le rapport dans le journal",
                {
                    "work_item_id": "{{params.element_suivi}}",
                    "text": "Contrôle de la table {{params.table}} (exécution {{run.id}}) :\n\n"
                    "{{steps.controle.content}}",
                },
                ["controle"],
                on_error="continue",
            ),
            _step(
                "correction",
                "node:projets/work_items.create",
                "Créer la tâche de correction",
                {
                    "story_id": "{{params.story}}",
                    "type": "TASK",
                    "title": "Corriger {{steps.sans_titre.data.total}} ligne(s) sans titre dans "
                    "« {{steps.sans_titre.data.label}} »",
                    "priority": "HIGH",
                    "description": "{{steps.controle.content}}",
                },
                ["controle", "sans_titre"],
                when={"left": "{{steps.sans_titre.data.total}}", "op": "gt", "right": 0},
            ),
        ],
        requirements=[
            TAB_FILES,
            TAB_MCP,
            PROJETS,
            "Un élément Projets pour l'historique des contrôles et une story pour les tâches de "
            "correction",
        ],
        trigger_hint=(
            "Événement tab.table.changed, filtre subject.id égal à l'id de la table, « Regrouper "
            "les rafales » 600 s, paramètre table = {{event.subject.id}} ; ou manuel avant un "
            "import."
        ),
    ),
    _template(
        slug="tab-projets-viz-synchro",
        title="Synchronisation Tab → Projets → Viz",
        description=(
            "Importe la table de planning d'Atelier Tab dans Atelier Projets (sans doublon), "
            "relit les éléments du projet, met à jour le jeu Viz de suivi, puis compte les "
            "éléments, les heures passées et l'écart par statut, et liste les éléments bloqués."
        ),
        value=(
            "Une modification du planning dans Tab se répercute dans Projets et dans le tableau "
            "de bord d'avancement sans rien rouvrir."
        ),
        apps=["tab", "projets", "viz"],
        params=[
            _param("table", "Table de planning Tab (id)", "tbl_planning_lots"),
            _param("projet", "Projet Atelier Projets alimenté (n°)"),
            _param("cle_viz", "Clé du jeu Viz de suivi", "nexus:suivi-planning"),
        ],
        steps=[
            _step(
                "importer",
                "tool:projets_import_tab_table",
                "Importer la table dans Atelier Projets",
                {"table_id": "{{params.table}}", "project_id": "{{params.projet}}"},
            ),
            _step(
                "elements",
                "node:projets/tables.get",
                "Relire les éléments du projet",
                {"name": "work-items", "project_id": "{{params.projet}}"},
                ["importer"],
            ),
            _step(
                "bloques",
                "node:projets/work_items.list",
                "Éléments bloqués",
                {"project_id": "{{params.projet}}", "status": ["BLOCKED"]},
                ["importer"],
                on_error="continue",
            ),
            _step(
                "publier",
                "node:viz/datasets.upsert_table",
                "Mettre à jour le jeu Viz de suivi",
                {
                    "name": "Suivi du planning (Projets)",
                    "key": "{{params.cle_viz}}",
                    "table": "{{steps.elements.data}}",
                },
                ["elements"],
                when=_rows_present("elements"),
            ),
            _step(
                "par_statut",
                "node:viz/datasets.query",
                "Éléments et heures par statut",
                {
                    "dataset_id": "{{steps.publier.data.dataset_id}}",
                    "dimensions": [{"field": "Statut"}],
                    "measures": [
                        {"agg": "count"},
                        {"field": "Heures passées", "agg": "sum"},
                        {"field": "Écart (heures)", "agg": "sum"},
                    ],
                },
                ["publier"],
                on_error="continue",
            ),
        ],
        requirements=[TAB_FILES, PROJETS, VIZ, IMPORT_TOKEN, LIMIT_1000],
        trigger_hint=(
            "Événement tab.table.changed, filtre subject.id égal à l'id de la table, « Regrouper "
            "les rafales » 300 s, 2 lancements par heure au plus, paramètre table = "
            "{{event.subject.id}}."
        ),
    ),
    _template(
        slug="viz-alerte-tache-projets",
        title="Alerte Viz → tâche de suivi Projets",
        description=(
            "Quand une alerte d'Atelier Viz se déclenche (dépenses du mois au-dessus du budget, "
            "indicateur hors seuil), lit le profil du jeu concerné, crée une tâche prioritaire "
            "dans une story d'Atelier Projets avec la valeur et le seuil, puis trace l'origine "
            "dans son journal d'avancement."
        ),
        value=(
            "Un dépassement devient une action datée et suivie au lieu d'une notification oubliée."
        ),
        apps=["viz", "projets"],
        params=[
            _param("jeu", "Jeu Viz de l'alerte (id, 12 caractères hexadécimaux)"),
            _param("alerte", "Nom de l'alerte", "Alerte Viz"),
            _param("valeur", "Valeur mesurée", "non renseignée"),
            _param("seuil", "Seuil de l'alerte", "non renseigné"),
            _param("story", "Story Projets où créer la tâche (n°)"),
        ],
        steps=[
            _step(
                "jeu_info",
                "node:viz/datasets.get",
                "Profil du jeu surveillé",
                {"dataset_id": "{{params.jeu}}"},
            ),
            _step(
                "tache",
                "node:projets/work_items.create",
                "Créer la tâche de suivi",
                {
                    "story_id": "{{params.story}}",
                    "type": "TASK",
                    "title": "Alerte « {{params.alerte}} » : {{params.valeur}} "
                    "(seuil {{params.seuil}})",
                    "priority": "HIGH",
                    "description": "Alerte Atelier Viz déclenchée sur le jeu "
                    "« {{steps.jeu_info.data.name}} » ({{steps.jeu_info.data.rows}} lignes).\n\n"
                    "- Valeur mesurée : {{params.valeur}}\n- Seuil : {{params.seuil}}\n\n"
                    "À analyser dans le rapport Viz.",
                },
                ["jeu_info"],
            ),
            _step(
                "journal",
                "node:projets/work_items.log",
                "Tracer l'origine dans le journal",
                {
                    "work_item_id": "{{steps.tache.data.id}}",
                    "text": "Créée par Atelier Nexus (exécution {{run.id}}) à partir de l'alerte "
                    "Viz « {{params.alerte}} ».",
                },
                ["tache"],
                on_error="continue",
            ),
        ],
        requirements=[
            VIZ,
            PROJETS,
            "Une alerte définie dans Viz et une story Projets pour les tâches de suivi",
        ],
        trigger_hint=(
            "Événement viz.alert.triggered ; paramètres du déclencheur : jeu = "
            "{{event.data.dataset_id}}, alerte = {{event.subject.label}}, valeur = "
            "{{event.data.value}}, seuil = {{event.data.threshold}}, story = n° fixe ; "
            "2 lancements par heure au plus (une tâche par déclenchement)."
        ),
    ),
)


def as_fields(template: WorkflowTemplate) -> WorkflowV2Fields:
    """Le modèle tel qu'un brouillon de workflow de suite (corps de validation)."""
    return WorkflowV2Fields(
        version=2,
        agent=None,
        title=template.title,
        description=template.description,
        steps=template.steps,
        params=template.params,
    )


# ─── Disponibilité ────────────────────────────────────────────────


def _setting(app: str) -> str:
    """Réglage(s) qui configure(nt) le nœud, en clair."""
    if app in HTTP_NODES:
        return HTTP_NODES[app][0].upper()
    return "TAB_EXPORTS_DIR ou TAB_MCP_COMMAND" if app == "tab" else app.upper()


def _of(name: str) -> str:
    """« de Viz », « d'Atelier Viz » (élision devant une voyelle ou un h)."""
    first = name[:1].lower()
    return f"d'{name}" if first and first in "aeiouyhéèê" else f"de {name}"


def _why(uses: str, problem: StepProblem, registry: StepRegistry) -> str:
    """Raison courte d'une étape inutilisable sur cette machine."""
    parsed = parse_uses(uses)
    if parsed is None:
        return problem.message
    source, name, action_id = parsed
    if source == "tool":
        declared = registry.declared.get(name)
        if problem.code == "UNAVAILABLE" and declared is not None:
            return f"boîte « {get_toolset(declared[1]).label} » non configurée"
        return "outil inconnu de Nexus" if problem.code == "UNKNOWN_USES" else problem.message
    state = registry.nodes.get(name)
    if state is None:
        return f"application « {name} » inconnue"
    if state.status == "unreachable":
        return f"{state.name} injoignable"
    if state.status == "not_configured":
        return f"{state.name} non configuré ({_setting(name)})"
    if state.status == "no_contract":
        return f"{state.name} sans manifeste atelier-node/1 (version antérieure au contrat)"
    if state.manifest is not None and state.manifest.action(action_id) is None:
        version = f" {state.manifest.version}" if state.manifest.version else ""
        return f"action absente du manifeste {_of(state.name)}{version}"
    return state.not_executable_reason or problem.message


def missing_for(template: WorkflowTemplate, registry: StepRegistry) -> list[str]:
    """Ce qui manque pour lancer le modèle ici : une ligne par étape inutilisable, puis les
    autres erreurs de validation (champ refusé par un manifeste plus récent…). Ne lève jamais."""
    out: list[str] = []
    for step in template.steps:
        target = registry.lookup(step.uses)
        if isinstance(target, StepProblem):
            out.append(f"{step.uses} : {_why(step.uses, target, registry)}")
    result = validate_workflow(as_fields(template), registry)
    for issue in result.errors:
        if issue.code in _LOOKUP_CODES:
            continue
        where = f"Étape « {issue.step_id} »" if issue.step_id else "Modèle"
        out.append(f"{where} : {issue.message}")
    return list(dict.fromkeys(out))


def library(registry: StepRegistry) -> list[WorkflowTemplate]:
    """Les modèles avec leur disponibilité sur cette machine. Un modèle impossible à vérifier
    (manifeste inattendu d'une application) est dit indisponible ; les autres restent servis."""
    out = []
    for template in TEMPLATES:
        try:
            missing = missing_for(template, registry)
        except Exception as exc:  # la galerie ne tombe jamais pour un seul modèle
            logger.warning(
                "Modèle %s : vérification impossible (%s)", template.slug, type(exc).__name__
            )
            missing = [UNCHECKED]
        out.append(template.model_copy(update={"available": not missing, "missing": missing}))
    return out
