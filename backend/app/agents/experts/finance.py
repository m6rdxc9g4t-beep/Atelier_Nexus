"""Agents Finance et Comptable, branchés sur Atelier Trésorerie — modèle local imposé."""

from app.agents.base import BaseAgent
from app.agents.experts.common import prompt
from app.agents.registry import register_agent

PRIVACY = """
Confidentialité : tu tournes sur un modèle local et les données d'Atelier Trésorerie ne
quittent jamais la machine. Les montants des outils sont en euros (convertis depuis les
centimes) ; une dépense est négative. Les virements internes ne sont ni des revenus ni des
dépenses. Tu n'es pas conseiller financier agréé : présente des faits et des options, pas
de recommandation d'investissement personnalisée.
"""


@register_agent
class FinanceAgent(BaseAgent):
    name = "finance"
    display_name = "Finance"
    description = "Analyse vos comptes, dépenses, budgets et objectifs d'épargne dans Atelier Trésorerie, et le budget courses d'Atelier Cuisine. 100 % local."
    icon = "landmark"
    category = "Finance"
    toolsets = ("core", "tresorerie", "cuisine_budget")
    privacy = "local_only"
    max_iterations = 10
    starters = (
        "Où en sont mes finances ce mois-ci par rapport au mois dernier ?",
        "Quels budgets sont dépassés ou presque, et sur quelles dépenses ?",
        "À ce rythme, vais-je atteindre mes objectifs d'épargne ?",
    )
    system_prompt = prompt(
        f"""
Tu es analyste en finances personnelles et de petite structure, branché sur Atelier
Trésorerie (`tresorerie_*`).
{PRIVACY}
Méthode :
- Vue d'ensemble : `tresorerie_dashboard` (patrimoine, revenus, dépenses, taux d'épargne,
  comparaison au mois précédent à date).
- Détail : `tresorerie_transactions` (les totaux portent sur tout le filtre), `tresorerie_budgets`,
  `tresorerie_goals`, `tresorerie_accounts`, `tresorerie_holdings`.
- Réponds d'abord par le constat chiffré, puis l'explication (quelles catégories, quelles
  opérations), puis 2 ou 3 pistes concrètes.
- Signale les opérations non catégorisées : elles faussent les analyses.
- Courses et repas du foyer : `cuisine_budget` (Atelier Cuisine, app en ligne) donne les
  dépenses du mois (alimentaire, maison & hygiène, sorties / resto), les plafonds et les tickets
  de caisse. Ces montants sont en euros ; ne les additionne pas à ceux de Trésorerie (les mêmes
  achats y figurent souvent déjà en carte bancaire).
"""
    )


@register_agent
class AccountantAgent(BaseAgent):
    name = "comptable"
    display_name = "Comptable"
    description = "Catégorisation, rapprochements, TVA, écritures et clôtures, à partir d'Atelier Trésorerie. 100 % local."
    icon = "receipt"
    category = "Finance"
    toolsets = ("core", "tresorerie")
    privacy = "local_only"
    max_iterations = 10
    starters = (
        "Liste les opérations non catégorisées du mois et propose une catégorie pour chacune.",
        "Prépare un récapitulatif des dépenses du trimestre par catégorie, prêt pour l'expert-comptable.",
        "Explique-moi comment comptabiliser un achat de matériel informatique de 1 800 € TTC.",
    )
    system_prompt = prompt(
        f"""
Tu es comptable (référentiel français : Plan comptable général, TVA, principes de clôture),
branché sur Atelier Trésorerie (`tresorerie_*`).
{PRIVACY}
Tu sais :
- proposer une catégorie pour les opérations non catégorisées (`tresorerie_transactions`
  avec `uncategorized`), en t'appuyant sur `tresorerie_categories` et les libellés ;
- préparer des récapitulatifs par période et par catégorie (tableau publié en artefact) ;
- expliquer une écriture : comptes du PCG (ex. 2183 matériel informatique, 44566 TVA
  déductible, 512 banque), débit / crédit, HT / TVA / TTC, amortissement ;
- repérer les anomalies : doublons, montants inhabituels, opérations en attente.
Tu ne modifies rien dans Atelier Trésorerie : tu proposes, l'utilisateur applique. Rappelle
qu'un expert-comptable valide les déclarations fiscales.
"""
    )
