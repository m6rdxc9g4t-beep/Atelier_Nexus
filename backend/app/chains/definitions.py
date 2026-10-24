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

EQUIPE = ChainDefinition(
    id="chaine_equipe",
    title="Chaîne Équipe",
    description=(
        "D'un objectif à un projet lancé dans vos applications : cadrage par la Direction, "
        "user stories, tâches dans Atelier Projets, compte rendu de lancement dans le Wiki. "
        "Vous validez le livrable de chaque étape et chaque écriture."
    ),
    icon="users",
    stages=[
        ChainStage(
            agent="direction",
            role="Cadrage",
            instructions=(
                "Lis la mémoire d'équipe et, si un projet existant est concerné, son point "
                "d'avancement. Cadre la demande : objectif, périmètre (dedans / dehors), au plus "
                "trois priorités, critères de réussite mesurables, échéance, risques. Ne crée rien "
                "dans Atelier Projets : la planification est l'étape 3. Une décision n'est "
                "enregistrée (equipe_decision) que si l'utilisateur la prend explicitement."
                " Ne note pas au journal : le compte rendu de l'étape 4 en tient lieu."
            ),
        ),
        ChainStage(
            agent="product_owner",
            role="User stories",
            instructions=(
                "À partir du cadrage validé, écris les user stories (« En tant que…, je veux…, "
                "afin de… ») avec leurs critères d'acceptation testables et une estimation EN HEURES, "
                "dans l'ordre des priorités. Propose de ranger la spécification dans une page du Wiki "
                "(wiki_search d'abord, puis wiki_create_page après accord). Ne crée pas encore de "
                "tâches dans Atelier Projets. Ne note pas au journal : le compte rendu de l'étape 4 en tient lieu."
            ),
        ),
        ChainStage(
            agent="chef_de_projet",
            role="Planification",
            instructions=(
                "Planifie les user stories validées dans Atelier Projets : choisis ou fais choisir "
                "le projet et la story parente (projets_structure), propose la liste des tâches "
                "(titre, estimation en heures, échéance, priorité) AVANT de les créer ; l'accord "
                "de l'utilisateur sur cette liste vaut intention, puis crée-les une par une "
                "(projets_create_work_item, chacune validée). Charge : equipe_point_avancement "
                "donne retards, blocages et jalons du projet (pas la charge) ; compare toi-même la "
                "somme des estimations aux jours ouvrés restants avant l'échéance, calcul montré "
                "(heures, heures par jour du projet, jours), et signale ce qui ne tient pas. Ne note pas au journal : le compte rendu de l'étape 4 en tient lieu."
            ),
        ),
        ChainStage(
            agent="redacteur",
            role="Communication",
            instructions=(
                "Rédige le compte rendu de lancement à partir des livrables validés (objectif, "
                "priorités, user stories, tâches créées avec leurs identifiants, échéances, "
                "risques) et range-le dans la mémoire d'équipe (equipe_compte_rendu, après "
                "accord) ; pas de note au journal en plus. Rédige aussi le court message d'annonce à envoyer aux personnes "
                "concernées, publié en artefact. N'ajoute rien qui ne soit dans les livrables."
            ),
        ),
    ],
)

CHAINS: dict[str, ChainDefinition] = {c.id: c for c in (DATA, DEV, EQUIPE)}


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
