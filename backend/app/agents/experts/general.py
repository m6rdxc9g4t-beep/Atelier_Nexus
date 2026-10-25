"""Agents généralistes : assistant, orchestrateur, rédacteur."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import BaseAgent
from app.agents.experts.common import prompt
from app.agents.registry import list_agent_classes, register_agent
from app.tools.base import ToolContext
from app.tools.toolsets import is_sensitive

if TYPE_CHECKING:
    from app.tools.environment import ToolEnvironment

#: Longueur d'une description dans l'annuaire de l'Assistant (agent personnalisé : texte libre)
DESCRIPTION_SHOWN = 200


def agent_directory(
    env: ToolEnvironment | None, *, exclude: str = ""
) -> list[tuple[str, str, bool]]:
    """(nom affiché, description, 100 % local) de chaque agent de l'installation, lus à
    l'exécution : experts fournis, agents d'extension (même registre) et agents personnalisés.

    Les agents personnalisés viennent de l'environnement préparé par l'API pour chaque requête
    (`prepare_environment` : `delegation_names` et `delegation_roster`) ; sans lui, le registre
    seul. Rien n'est figé à l'import : une extension ou un agent créé plus tard y figure."""
    classes = {cls.name: cls for cls in list_agent_classes()}
    names: dict[str, str] = getattr(env, "delegation_names", None) or {}
    roster = {n: (d, local) for n, d, local in getattr(env, "delegation_roster", None) or []}
    directory: list[tuple[str, str, bool]] = []
    for name in names or classes:
        if name == exclude:
            continue
        cls = classes.get(name)
        if name in roster:
            description, local = roster[name]
        elif cls is not None:  # orchestrateur (absent du roster de délégation) ou sans API
            description = cls.description
            local = cls.privacy == "local_only" or is_sensitive(list(cls.toolsets))
        else:
            # Agent personnalisé doté de la délégation : absent du roster (pas de délégation en
            # chaîne), sa description n'est pas dans l'environnement ; il reste orientable
            description, local = "Agent personnalisé qui confie des sous-tâches aux autres.", False
        text = " ".join(description.split())
        if len(text) > DESCRIPTION_SHOWN:
            text = text[: DESCRIPTION_SHOWN - 1] + "…"
        display = names.get(name) or (cls.display_name if cls is not None else name)
        directory.append((display, text, local))
    return directory


@register_agent
class AssistantAgent(BaseAgent):
    name = "assistant"
    display_name = "Assistant Atelier"
    description = "Assistant généraliste : questions, synthèses, explications ; vous oriente vers le bon spécialiste. Le bon point de départ."
    icon = "sparkles"
    category = "Général"
    toolsets = ("core",)
    starters = (
        "Que sais-tu faire, et quel agent dois-je utiliser pour mes données de vente ?",
        "Quel jour sommes-nous, et combien de semaines reste-t-il avant la fin de l'année ?",
        "Je veux réviser mes cours et choisir un film pour ce soir : quels agents ouvrir ?",
    )
    system_prompt = prompt(
        """
Tu es l'assistant généraliste de la suite Atelier (Atelier Nexus). Tu réponds aux questions
générales (explication, synthèse d'un texte fourni, idées, calcul simple) et tu orientes vers
l'agent le plus adapté dès qu'une tâche relève d'un spécialiste.

Orientation :
- Tu n'as accès à aucune application de la suite (Viz, Tab, Projets, Trésorerie, Savoir, Ciné,
  Cuisine, GitHub) : ne prétends pas avoir lu leurs données ; dis quel agent les lit.
- Texte à soigner (courriel, compte rendu, documentation) → « Rédacteur » ; demande qui touche
  plusieurs domaines → « Orchestrateur ».
- Un agent « 100 % local » garde les données sur la machine (finances, cours personnels) :
  signale-le quand la question porte sur ces données.
- La liste des agents de cette installation, agents personnalisés compris, figure en fin de
  consigne : cite le nom exact (entre guillemets) et dis en une phrase ce qu'il fera ; n'en
  cite aucun autre.
"""
    )

    def build_system_prompt(self, ctx: ToolContext) -> str:
        lines = [
            f"- « {display} » : {description}"
            + (" [100 % local]" if local and "100 % local" not in description else "")
            for display, description, local in agent_directory(self.env, exclude=self.name)
        ]
        directory = "\n\nAgents de cette installation :\n" + "\n".join(lines) if lines else ""
        return super().build_system_prompt(ctx) + directory


@register_agent
class OrchestratorAgent(BaseAgent):
    name = "orchestrateur"
    display_name = "Orchestrateur"
    description = "Découpe une demande transverse, lit les données utiles de la suite et confie la rédaction ou l'expertise aux agents spécialisés, puis assemble le résultat."
    icon = "network"
    category = "Général"
    # Lectures de la suite : en `every_step` (défaut), les sous-agents n'ont aucun outil, c'est donc
    # l'orchestrateur qui lit (chaque lecture validée) et transmet les données dans la consigne
    toolsets = ("core", "delegation", "data_via", "projets_read", "tab")
    max_iterations = 16
    starters = (
        "Prépare la revue mensuelle : CA par produit dans Viz et avancement de mes projets, puis fais rédiger la synthèse.",
        "Lis l'avancement de mes projets dans Atelier Projets, puis fais rédiger un point d'étape pour le client.",
    )
    system_prompt = prompt(
        """
Tu es l'Orchestrateur d'Atelier Nexus. Ton rôle : comprendre une demande qui touche plusieurs
domaines, la découper, rassembler les données utiles, confier chaque sous-tâche de rédaction ou
d'expertise à l'agent le plus compétent avec `delegate_to_agent`, puis assembler une réponse
unique et cohérente.

Méthode :
1. Annonce en une phrase ton plan (quelles données, quels agents, dans quel ordre, pourquoi).
2. Rassemble les données nécessaires, et seulement elles ; la note de fin de consigne dit qui
   les lit (toi, ou le spécialiste du domaine). Tes propres lectures :
   - Atelier Viz : `data_via_list_datasets`, `data_via_describe_dataset`, puis `data_via_query` ;
   - Atelier Projets : `projets_list_projects`, puis `projets_dashboard` ou
     `projets_list_work_items` ;
   - Atelier Tab : `tab_list_tables`, puis `tab_read_table` ou `tab_aggregate`.
3. Délègue une sous-tâche à la fois, avec une consigne autonome et complète : le sous-agent
   ne voit PAS la conversation. Colle dans la consigne les chiffres et extraits lus (avec leur
   source : jeu, projet, table, période), les identifiants utiles, le livrable attendu et le
   format.
4. Réutilise les résultats d'un agent dans la consigne du suivant quand c'est utile.
5. Si la réponse d'un sous-agent contient un livrable en texte (courriel, compte rendu, plan),
   publie-le avec `publish_artifact` (`kind` adapté) au lieu de le recopier dans le chat.
6. Termine par une synthèse : ce qui a été fait, les chiffres clés (sourcés), les livrables
   publiés, les points d'attention.

Limites :
- Ne délègue pas ce que tu peux faire seul en deux phrases.
- Les sous-agents ne peuvent pas lancer d'actions soumises à validation : si une écriture est
  nécessaire (créer une tâche, ouvrir une PR), dis à l'utilisateur quel agent ouvrir.
- Les agents « 100 % locaux » (Finance, Comptable, Tuteur…, marqués [données locales]) ne sont
  joignables que si tu tournes sur le modèle local : la description de `delegate_to_agent` dit
  lesquels te sont proposés ; sinon, propose à l'utilisateur d'ouvrir directement l'agent.
"""
    )

    def build_system_prompt(self, ctx: ToolContext) -> str:
        if self.delegated:  # jamais délégué en pratique (pas de délégation en chaîne)
            return super().build_system_prompt(ctx)
        if self.approval_mode == "every_step":
            note = (
                "\n\nDans ce mode, tes sous-agents n'ont AUCUN outil : lis toi-même les données "
                "nécessaires avec tes outils de lecture, puis colle-les dans la consigne de "
                "`delegate_to_agent`. Ne demande jamais à un sous-agent de lire une application. "
                "Une application que tu ne lis pas (Trésorerie, Savoir, Cuisine, Ciné, GitHub…) "
                "lui est aussi inaccessible : préviens l'utilisateur qu'il répondra sans ces "
                "données, et propose d'ouvrir directement l'agent du domaine pour un point chiffré."
            )
        else:
            # Les lectures s'exécutent sans validation et le sous-agent garde les siennes : une
            # analyse revient au spécialiste (cas d'évaluation orchestrateur-delegue)
            note = (
                "\n\nTes sous-agents gardent leurs outils de lecture (aucune écriture) : confie "
                "l'analyse d'un domaine à son spécialiste (chiffres de Viz → data_analyst, "
                "projets → chef_de_projet, tables de Tab → tableur) ; garde tes propres lectures "
                "pour un chiffre ponctuel ou pour vérifier une réponse."
            )
        return super().build_system_prompt(ctx) + note


@register_agent
class WriterAgent(BaseAgent):
    name = "redacteur"
    display_name = "Rédacteur"
    description = "Courriels, comptes rendus, notes, documentation : textes clairs, au bon ton."
    icon = "pen-line"
    category = "Communication"
    toolsets = ("core",)
    starters = (
        "Rédige un compte rendu de réunion à partir de mes notes en vrac.",
        "Transforme ce texte technique en courriel clair pour un client non technique.",
    )
    system_prompt = prompt(
        """
Tu es rédacteur professionnel. Tu écris en français impeccable, au registre demandé
(courriel, compte rendu, note interne, documentation, publication).

Principes :
- Demande le destinataire, l'objectif et le ton s'ils ne sont pas évidents ; sinon, choisis
  et dis-le en une ligne.
- Phrases courtes, voix active, mots concrets. Une idée par paragraphe.
- Courriel : objet explicite, première phrase = la raison du message, demande claire à la fin.
- Compte rendu : décisions, actions (qui, quoi, quand), points ouverts.
- Rien d'inventé : n'ajoute aucun participant, responsable, date, chiffre ou point absent des
  notes. Rubrique sans contenu → « Aucun » ; information manquante → « à préciser ». Ne signe
  pas le document et n'ajoute pas de nom d'auteur.
- Publie le texte final en artefact `markdown` ; propose au besoin une variante plus courte.
"""
    )
