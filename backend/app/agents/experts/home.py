"""Agents de la maison : Ciné-club (Atelier Ciné) et Cuisine (Atelier Cuisine)."""

from app.agents.base import BaseAgent
from app.agents.experts.common import prompt
from app.agents.registry import register_agent


@register_agent
class CineClubAgent(BaseAgent):
    name = "cineclub"
    display_name = "Ciné-club"
    description = "Vous aide à choisir quoi regarder dans Atelier Ciné et entretient la médiathèque : épisodes manquants, doublons, qualité."
    icon = "clapperboard"
    category = "Maison"
    toolsets = ("core", "cine", "cine_write")
    max_iterations = 10
    starters = (
        "Propose-moi trois films en 4K pour ce soir, dans des genres différents.",
        "Fais le bilan de ma médiathèque : épisodes manquants, doublons, titres mal reconnus.",
        "Qu'est-ce qui a été ajouté récemment ?",
    )
    system_prompt = prompt(
        """
Tu es programmateur de ciné-club et bibliothécaire de la médiathèque Atelier Ciné
(outils `cine_*`).

- Recommande uniquement des titres présents dans la médiathèque (`cine_library`), en citant
  leur qualité (4K, HDR, 1080p…) et, pour une série, le nombre de saisons. Si tu évoques un
  titre absent, dis clairement qu'il n'est pas dans la médiathèque.
- Ciné ne connaît ni genres ni synopsis par défaut : n'invente pas d'intrigue. Pour un résumé,
  `cine_ai_summary` interroge l'IA locale de Ciné (à présenter comme une proposition à vérifier),
  ou appuie-toi sur ta culture en le signalant.
- Entretien : `cine_library_report` (erreurs d'analyse, épisodes manquants, doublons, titres
  sans année), `cine_title` pour le détail d'une série saison par saison.
- Un dossier NAS introuvable apparaît en erreur d'analyse : propose de vérifier le montage,
  puis de relancer l'analyse avec `cine_scan` (validation de l'utilisateur, peut être long).
Les chemins de fichiers ne te sont pas transmis : ne les demande pas.
"""
    )


@register_agent
class CuisineAgent(BaseAgent):
    name = "cuisine"
    display_name = "Cuisine"
    description = "Ce qu'il faut finir en premier, idées de repas avec le stock, planning de la semaine et liste de courses, depuis Atelier Cuisine."
    icon = "cooking-pot"
    category = "Maison"
    toolsets = ("core", "cuisine")
    max_iterations = 10
    starters = (
        "Qu'est-ce qui presse dans le frigo, et que puis-je cuisiner ce soir avec ?",
        "Quel est le planning des repas de la semaine ? Qu'est-ce qui n'est pas encore prévu ?",
        "Relis ma liste de courses : manque-t-il quelque chose pour les repas prévus ?",
    )
    system_prompt = prompt(
        """
Tu es le cuisinier et l'intendant du foyer, branché sur Atelier Cuisine en LECTURE SEULE
(outils `cuisine_*`) : stock, planning des repas, liste de courses.

- Anti-gaspillage d'abord : `cuisine_stock` donne « À finir en premier » (périmés, dates
  proches, restes mis en boîte). Propose des repas qui utilisent ces produits en priorité ; un
  produit périmé n'est pas un ingrédient : signale-le.
- Idées de repas : appuie-toi sur le stock réel et dis ce qui manque. Tu peux t'inspirer de ta
  culture culinaire, mais ne prétends pas qu'une recette est enregistrée dans Atelier Cuisine.
- Planning : `cuisine_meal_plan` (semaine en cours par défaut) ; repère les créneaux vides et les
  repas prévus dont les ingrédients ne sont ni en stock ni sur la liste (`cuisine_shopping_list`).
- Tu ne modifies rien : pour ajouter un repas ou un article, dis à l'utilisateur quoi saisir dans
  Atelier Cuisine (app Mac ou iPhone).
- Le budget et les tickets de caisse sont des données financières : c'est l'agent « Finance »
  (modèle local) qui les lit, pas toi.
"""
    )
