"""Chaînes fournies. Une étape = un agent expert et sa mission dans la chaîne."""

from __future__ import annotations

from app.agents import BaseAgent
from app.schemas.chains import ChainDefinition, ChainInfo, ChainStage, ChainStageInfo

DATA = ChainDefinition(
    id="chaine_data",
    title="Chaîne Data",
    description=(
        "Des données brutes aux mesures Power BI vérifiées : préparation, modèle en étoile, "
        "mesures DAX, contrôle qualité. Vous validez le livrable de chaque étape."
    ),
    icon="database",
    stages=[
        ChainStage(
            agent="ingenieur_donnees",
            role="Préparation des données",
            instructions=(
                "Identifie les sources utiles à la demande, mesure leur qualité et écris les "
                "transformations (Atelier Viz ou Power Query). Ne fais ni modèle ni DAX."
            ),
        ),
        ChainStage(
            agent="modelisateur_bi",
            role="Modèle en étoile",
            instructions=(
                "À partir des données préparées, conçois le modèle en étoile (grain, faits, "
                "dimensions, table Date, relations). N'écris pas de mesures DAX."
            ),
        ),
        ChainStage(
            agent="data_analyst",
            role="Mesures DAX et analyse",
            instructions=(
                "Sur le modèle validé, écris les mesures DAX qui répondent à la demande "
                "(VAR … RETURN, DIVIDE, commentées), vérifie leurs équivalents dans Atelier Viz "
                "et donne les chiffres clés obtenus."
            ),
        ),
        ChainStage(
            agent="controleur_donnees",
            role="Contrôle qualité",
            instructions=(
                "Recalcule dans Atelier Viz chaque chiffre clé et le résultat attendu de chaque "
                "mesure annoncés aux étapes précédentes ; donne le tableau des écarts et un verdict."
            ),
        ),
    ],
)

DEV = ChainDefinition(
    id="chaine_dev",
    title="Chaîne Dev",
    description=(
        "D'une idée à une pull request relue : user story, conception, code sur une branche, "
        "tests, relecture. Vous validez le livrable de chaque étape."
    ),
    icon="code",
    stages=[
        ChainStage(
            agent="product_owner",
            role="User story",
            instructions=(
                "Rédige la user story et ses critères d'acceptation testables. Ne crée rien dans "
                "Atelier Projets sauf si l'utilisateur le demande."
            ),
        ),
        ChainStage(
            agent="architecte",
            role="Conception",
            instructions=(
                "Lis le dépôt et conçois la réalisation de la user story validée : fichiers, "
                "étapes, contrats, risques, plan de tests, nom de branche. N'écris pas de code."
            ),
        ),
        ChainStage(
            agent="developpeur",
            role="Réalisation",
            instructions=(
                "Réalise la conception validée sur la branche proposée (jamais main), puis ouvre "
                "une PR brouillon. Donne le nom de la branche et le lien de la PR."
            ),
        ),
        ChainStage(
            agent="testeur",
            role="Tests",
            instructions=(
                "Écris les tests prévus par la conception sur la même branche que la réalisation "
                "et dis comment les lancer."
            ),
        ),
        ChainStage(
            agent="relecteur_code",
            role="Relecture",
            instructions=(
                "Relis la branche et la PR par rapport à la user story et à la conception "
                "validées ; donne ton verdict et les remarques classées."
            ),
        ),
    ],
)

CHAINS: dict[str, ChainDefinition] = {c.id: c for c in (DATA, DEV)}


class ChainNotFoundError(LookupError):
    pass


def get_chain(chain_id: str) -> ChainDefinition:
    try:
        return CHAINS[chain_id]
    except KeyError:
        raise ChainNotFoundError(chain_id) from None


def chain_info(chain: ChainDefinition, agents: dict[str, BaseAgent]) -> ChainInfo:
    """Fiche publique : noms affichés et verrou local de chaque étape."""
    return ChainInfo(
        id=chain.id,
        title=chain.title,
        description=chain.description,
        icon=chain.icon,
        stages=[
            ChainStageInfo(
                **stage.model_dump(),
                display_name=agents[stage.agent].display_name
                if stage.agent in agents
                else stage.agent,
                local_only=agents[stage.agent].local_only if stage.agent in agents else False,
            )
            for stage in chain.stages
        ],
    )


def leaks_local_data(previous: list[BaseAgent], following: BaseAgent) -> bool:
    """Vrai si un livrable d'agent « 100 % local » partirait chez un agent qui peut utiliser
    Claude : interdit (ses données ne doivent pas quitter la machine)."""
    return any(a.local_only for a in previous) and not following.local_only
