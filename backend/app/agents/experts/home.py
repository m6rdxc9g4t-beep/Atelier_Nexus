"""Agent Ciné-club, branché sur Atelier Ciné (médiathèque personnelle)."""

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
