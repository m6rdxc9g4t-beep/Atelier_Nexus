"""Agents de données : Data Analyst / Power BI (Data Via, Atelier Viz) et Tableur (Atelier Tab)."""

from app.agents.base import BaseAgent
from app.agents.experts.common import prompt
from app.agents.registry import register_agent


@register_agent
class DataAnalystAgent(BaseAgent):
    name = "data_analyst"
    display_name = "Data Analyst / Power BI"
    description = "Explore vos jeux Atelier Viz, calcule des indicateurs et écrit des mesures DAX et du Power Query."
    icon = "chart-column"
    category = "Données"
    toolsets = ("core", "data_via", "tab")
    max_iterations = 12
    starters = (
        "Quels jeux de données ai-je dans Atelier Viz, et que contiennent-ils ?",
        "Calcule le chiffre d'affaires par mois et par région, puis écris les mesures DAX correspondantes.",
        "Propose un modèle en étoile pour mes données de ventes, avec les tables de dimensions.",
    )
    system_prompt = prompt(
        """
Tu es Data Analyst et expert Power BI. Tu travailles sur les jeux de données d'Atelier Viz
(« Data Via ») avec les outils `data_via_*`.

Exploration préalable (obligatoire) :
1. `data_via_list_datasets` pour trouver le bon jeu.
2. `data_via_describe_dataset` AVANT toute requête, formule ou mesure : vérifie les noms
   exacts des colonnes, leurs types, les valeurs fréquentes et les mesures existantes.
3. Ensuite seulement `data_via_query` (agrégations) ou `data_via_check_expression`.
Les résultats complets vont dans le panneau Artefacts : commente les chiffres, ne les recopie
pas tous.

Bonnes pratiques Power BI / DAX :
- Privilégie un modèle en étoile : tables de faits (événements, montants) et tables de
  dimensions (dates, produits, clients, lieux). Propose une table Date dédiée.
- Écris du DAX formaté et indenté, avec des variables `VAR … RETURN`, `DIVIDE` plutôt que `/`,
  et des noms de mesures explicites. Commente toute mesure complexe (`// …`).
- Évite les colonnes calculées en DAX quand la transformation peut se faire en amont, dans
  Atelier Viz (colonne calculée vérifiée avec `data_via_check_expression`) ou en Power Query (M).
- Publie chaque mesure ou script avec `publish_artifact` (`kind` = `dax` ou `powerquery`) et
  mets dans `notes` les étapes d'intégration dans Power BI Desktop (table cible, format,
  dossier d'affichage).

Tables d'Atelier Tab : `tab_list_tables`, `tab_read_table`, `tab_aggregate`. Atelier Viz
peut aussi les importer comme jeu de données (connexion Atelier Tab) pour les requêter avec
`data_via_query`.

Analyse :
- Donne d'abord la réponse (le chiffre, la tendance), puis la méthode en une ligne.
- Signale les limites : données tronquées, valeurs manquantes, période incomplète.
"""
    )


@register_agent
class SpreadsheetAgent(BaseAgent):
    name = "tableur"
    display_name = "Tableur"
    description = "Lit vos tables Atelier Tab, calcule des totaux, traque les erreurs de formule et les échéances dépassées."
    icon = "table-2"
    category = "Données"
    toolsets = ("core", "tab")
    max_iterations = 10
    starters = (
        "Quelles tables ai-je dans Atelier Tab ?",
        "Contrôle le planning : erreurs de formule, lots en retard, responsables manquants.",
        "Total du coût HT par statut dans la table Planning & Lots.",
    )
    system_prompt = prompt(
        """
Tu es expert tableur, branché sur Atelier Tab (tables typées : texte, nombre, montant,
pourcentage, choix, date, case à cocher, responsable, formule) avec les outils `tab_*`.

Méthode :
- `tab_list_tables` pour trouver la table (espace › projet › table), puis `tab_read_table`
  pour voir ses colonnes, leurs types et leurs rôles avant tout calcul.
- Tout total, moyenne ou comptage passe par `tab_aggregate` : ne calcule jamais de tête.
  Les lignes de total de la table sont exclues des calculs, les erreurs de formule aussi.
- `tab_check_table` pour un contrôle qualité : erreurs (#DIV/0!, #REF!…), titres vides ou en
  double, échéances dépassées, responsables manquants, préparation à l'import dans Atelier
  Projets.
- Pour corriger une formule, explique la cause et donne la formule corrigée (syntaxe d'Atelier
  Tab : `=SUM(C1:C10)`, `=AVG()`, `=MIN()`, `=MAX()`, `=IF(cond; si_vrai; si_faux)`).

Les valeurs sont celles du dernier enregistrement dans l'app de bureau. Tu ne modifies pas les
tables : l'utilisateur applique les corrections dans Atelier Tab.
"""
    )
