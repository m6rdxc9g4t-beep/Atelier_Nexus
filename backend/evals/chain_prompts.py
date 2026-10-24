"""Messages de relais de la Chaîne Équipe pour les évaluations (cas `chaine-equipe-*`).

Produits par la vraie fonction `handoff_message` à partir d'une demande et de livrables fictifs
cohérents avec la démo « App E-Commerce v2 » : le cas d'évaluation rejoue exactement ce que
reçoit l'agent de l'étape. `tests/test_chains.py` vérifie que les prompts des cas restent égaux
à ce que produit le code.
"""

from __future__ import annotations

from app.chains.definitions import EQUIPE
from app.chains.handoff import handoff_message
from app.schemas.chains import StageDeliverable, StageState

REQUEST = (
    "Lancer la version mobile de la boutique (App E-Commerce v2) pour la fin décembre : panier "
    "et paiement d'abord."
)
NAMES = {
    "direction": "Direction",
    "product_owner": "Product Owner",
    "chef_de_projet": "Chef de projet",
    "redacteur": "Rédacteur",
}
CADRAGE = """Objectif : boutique utilisable sur mobile pour le 18/12/2026.
Périmètre : panier et paiement sur mobile (dedans) ; application native, catalogue (dehors).
Priorités : 1. panier mobile ; 2. paiement mobile ; 3. tests sur deux téléphones.
Critères de réussite : un achat complet sur mobile en moins de 2 minutes ; aucune erreur bloquante.
Risque : #12345 (synchronisation Git) en retard de 3 j, à finir avant."""
STORIES = """US1 — En tant que client sur mobile, je veux modifier mon panier d'un doigt, afin d'acheter
sans zoomer. Critères : boutons de 44 px au moins ; total mis à jour sans recharger. Estimation : 3 j.
US2 — En tant que client sur mobile, je veux payer en une page, afin de finir mon achat vite.
Critères : formulaire sur un écran ; erreurs affichées sous le champ. Estimation : 4 j.
US3 — En tant qu'équipe, nous voulons tester sur deux téléphones, afin d'éviter les surprises.
Critères : parcours complet sur iPhone et Android. Estimation : 1 j.
Spécification rangée dans le Wiki : page « Spécification boutique mobile » (page 12)."""
PLANNING = """Tâches créées dans Atelier Projets (projet 1, story 2) :
#20001 Panier mobile — 3 j — échéance 20/11 — priorité haute
#20002 Paiement en une page — 4 j — échéance 04/12 — priorité haute
#20003 Tests sur deux téléphones — 1 j — échéance 11/12 — priorité normale
Charge : tient dans l'échéance si #12345 est terminé avant le 31/10."""


def prompt(stage: int) -> str:
    """Relais de l'étape `stage` (1 à 4), avec les livrables validés des étapes précédentes."""
    texts = [CADRAGE, STORIES, PLANNING]
    states = [
        StageState(
            agent=s.agent,
            role=s.role,
            status="validated" if i < stage - 1 else ("active" if i == stage - 1 else "pending"),
            deliverable=StageDeliverable(text=texts[i]) if i < stage - 1 else None,
        )
        for i, s in enumerate(EQUIPE.stages)
    ]
    return handoff_message(EQUIPE, REQUEST, states, stage - 1, NAMES)


def relay_prompt(chain: str, stage: int) -> str:
    """Relais d'une étape pour un cas d'évaluation (`relais = "chaine_equipe:3"`)."""
    if chain != EQUIPE.id:
        raise ValueError(f"pas de relais d'évaluation pour la chaîne « {chain} »")
    if not 1 <= stage <= len(EQUIPE.stages):
        raise ValueError(f"étape {stage} hors de la chaîne « {chain} »")
    return prompt(stage)


if __name__ == "__main__":
    import sys

    print(prompt(int(sys.argv[1])))
