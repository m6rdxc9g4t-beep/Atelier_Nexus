"""Catalogue des boîtes à outils (toolsets).

Un agent — codé ou créé depuis l'interface — déclare les boîtes à outils qu'il utilise
par leur identifiant. Chaque boîte sait si elle est disponible (configuration) et
construit ses outils à partir de l'environnement d'exécution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.config import Settings
from app.tools.analyse import analyse_tools
from app.tools.artifacts import PublishArtifactTool
from app.tools.base import BaseTool
from app.tools.cine import cine_read_tools, cine_write_tools
from app.tools.cuisine import cuisine_budget_tools, cuisine_tools
from app.tools.data_via import DataViaNotConfiguredError, data_via_tools
from app.tools.environment import ToolEnvironment
from app.tools.equipe import equipe_memory_tools, equipe_report_tools, equipe_write_tools
from app.tools.formulaire import (
    formulaire_read_tools,
    formulaire_responses_tools,
    formulaire_write_tools,
)
from app.tools.github import github_read_tools, github_write_tools
from app.tools.http import AppNotConfiguredError
from app.tools.projets import projets_read_tools, projets_write_tools
from app.tools.savoir import savoir_read_tools, savoir_write_tools
from app.tools.system import CurrentDateTimeTool
from app.tools.tab import tab_tools
from app.tools.tab_mcp import tab_write_tools
from app.tools.tab_projets import tab_projets_tools
from app.tools.tresorerie import tresorerie_tools
from app.tools.wiki import wiki_read_tools, wiki_write_tools


@dataclass(frozen=True)
class Toolset:
    id: str
    label: str
    description: str
    build: Callable[[ToolEnvironment], list[BaseTool[Any]]]
    is_configured: Callable[[Settings], bool] = lambda _s: True
    app: str | None = None
    #: Données sensibles : tout agent qui utilise cette boîte est verrouillé sur un modèle local
    sensitive: bool = False
    #: Contient des actions d'écriture (soumises à validation)
    writes: bool = False
    #: Boîte réservée au code (ex. délégation) : non proposée dans l'éditeur d'agents
    internal: bool = False
    #: Écrit dans un espace PARTAGÉ que lisent les agents sur Claude (Wiki, mémoire d'équipe) :
    #: retirée de tout agent verrouillé sur le modèle local, pour que ses données (finances,
    #: réponses individuelles) ne puissent pas y être recopiées (`build_tools(local=True)`)
    shared: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


class ToolInfo(BaseModel):
    name: str
    description: str
    requires_approval: bool
    sensitive: bool


class ToolsetInfo(BaseModel):
    id: str
    label: str
    description: str
    app: str | None
    configured: bool
    sensitive: bool
    writes: bool
    tools: list[ToolInfo]


_TOOLSETS: dict[str, Toolset] = {}


def register_toolset(toolset: Toolset) -> Toolset:
    if toolset.id in _TOOLSETS:
        raise ValueError(f"Boîte à outils déjà enregistrée : {toolset.id}")
    _TOOLSETS[toolset.id] = toolset
    return toolset


def get_toolset(toolset_id: str) -> Toolset:
    try:
        return _TOOLSETS[toolset_id]
    except KeyError:
        raise KeyError(f"Boîte à outils inconnue : {toolset_id}") from None


def toolset_ids(*, include_internal: bool = False) -> list[str]:
    return [t.id for t in _TOOLSETS.values() if include_internal or not t.internal]


class UnavailableToolset(BaseModel):
    id: str
    label: str
    reason: str


SHARED_REFUSED = "refusée à un agent 100 % local (espace lu par les agents sur Claude)"


def build_tools(
    ids: list[str], env: ToolEnvironment, *, local: bool = False
) -> tuple[list[BaseTool[Any]], list[UnavailableToolset]]:
    """Outils des boîtes demandées, dans l'ordre, sans doublon de nom.

    Une boîte non configurée (adresse ou jeton absent) est écartée et signalée :
    l'agent reste utilisable avec ses autres outils. `local` (agent verrouillé sur le modèle
    local) : les boîtes `shared` sont écartées de la même façon.
    """
    tools: list[BaseTool[Any]] = []
    unavailable: list[UnavailableToolset] = []
    seen: set[str] = set()
    for toolset_id in ids:
        toolset = get_toolset(toolset_id)
        if local and toolset.shared:
            unavailable.append(
                UnavailableToolset(id=toolset.id, label=toolset.label, reason=SHARED_REFUSED)
            )
            continue
        if not toolset.is_configured(env.settings):
            unavailable.append(
                UnavailableToolset(id=toolset.id, label=toolset.label, reason="non configurée")
            )
            continue
        try:
            built = toolset.build(env)
        except (AppNotConfiguredError, DataViaNotConfiguredError) as exc:
            unavailable.append(
                UnavailableToolset(id=toolset.id, label=toolset.label, reason=str(exc))
            )
            continue
        for tool in built:
            if tool.name not in seen:
                seen.add(tool.name)
                tools.append(tool)
    return tools, unavailable


def describe_toolsets(env: ToolEnvironment, *, include_internal: bool = False) -> list[ToolsetInfo]:
    infos = []
    for toolset in _TOOLSETS.values():
        if toolset.internal and not include_internal:
            continue
        # Les outils sont construits à blanc (aucun appel réseau) pour lire leurs métadonnées
        try:
            tools = toolset.build(env)
        except Exception:
            tools = []
        infos.append(
            ToolsetInfo(
                id=toolset.id,
                label=toolset.label,
                description=toolset.description,
                app=toolset.app,
                configured=toolset.is_configured(env.settings),
                sensitive=toolset.sensitive,
                writes=toolset.writes,
                tools=[
                    ToolInfo(
                        name=t.name,
                        description=t.description,
                        requires_approval=t.requires_approval,
                        sensitive=t.sensitive,
                    )
                    for t in tools
                ],
            )
        )
    return infos


# ─── Boîtes fournies ──────────────────────────────────────────────

register_toolset(
    Toolset(
        id="core",
        label="Essentiels",
        description="Date et heure, publication de livrables dans le panneau Artefacts.",
        build=lambda env: [CurrentDateTimeTool(), PublishArtifactTool()],
    )
)
register_toolset(
    Toolset(
        id="analyse",
        label="Analyse statistique",
        description=(
            "Charge un jeu (Viz, Tab ou fichier joint), profil et qualité, distributions (asymétrie, "
            "aplatissement, normalité), corrélations, relations, valeurs atypiques, nettoyage d'une "
            "copie, agrégations et graphiques. Calculs faits par Nexus, sans écriture dans les apps."
        ),
        build=lambda env: analyse_tools(env),
        tags=("donnees",),
    )
)
register_toolset(
    Toolset(
        id="data_via",
        label="Data Via (Atelier Viz)",
        description="Jeux de données, schémas, agrégations et vérification de mesures, en lecture.",
        build=lambda env: data_via_tools(env.data_via()),
        is_configured=lambda s: bool(s.data_via_base_url),
        app="viz",
    )
)
register_toolset(
    Toolset(
        id="projets_read",
        label="Atelier Projets — lecture",
        description="Projets, arborescence, éléments, feuilles de temps, jalons.",
        build=lambda env: projets_read_tools(env.projets()),
        is_configured=lambda s: bool(s.projets_base_url),
        app="projets",
    )
)
register_toolset(
    Toolset(
        id="projets_write",
        label="Atelier Projets — modifications",
        description="Créer des éléments, saisir du temps, changer un statut, journaliser (avec validation).",
        build=lambda env: projets_write_tools(env.projets()),
        is_configured=lambda s: bool(s.projets_base_url),
        app="projets",
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="tresorerie",
        label="Atelier Trésorerie",
        description="Comptes, opérations, budgets, objectifs, placements. Données sensibles : modèle local imposé.",
        build=lambda env: tresorerie_tools(env.tresorerie()),
        is_configured=lambda s: bool(s.tresorerie_base_url),
        app="tresorerie",
        sensitive=True,
    )
)
register_toolset(
    Toolset(
        id="tab",
        label="Atelier Tab",
        description="Tables du tableur (valeurs calculées), totaux par groupe, contrôle des erreurs et des échéances, en lecture.",
        build=lambda env: tab_tools(env.tab()),
        is_configured=lambda s: bool(s.tab_exports_dir),
        app="tab",
    )
)
register_toolset(
    Toolset(
        id="tab_write",
        label="Atelier Tab — modifications",
        description="Modifier des cellules, ajouter ou supprimer des lignes, ajouter une colonne, créer une table (avec validation).",
        build=lambda env: tab_write_tools(env.tab_mcp()),
        is_configured=lambda s: bool(s.tab_mcp_command),
        app="tab",
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="tab_projets",
        label="Atelier Tab → Atelier Projets",
        description="Aperçu puis import d'une table de Tab en éléments de Projets (import avec validation, sans doublon).",
        build=lambda env: tab_projets_tools(env.projets(), env.tab()),
        is_configured=lambda s: bool(s.tab_exports_dir and s.projets_base_url),
        app="projets",
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="cine",
        label="Atelier Ciné",
        description="Médiathèque : films, séries, épisodes manquants, qualités, synopsis proposés par l'IA locale de Ciné.",
        build=lambda env: cine_read_tools(env.cine()),
        is_configured=lambda s: bool(s.cine_base_url),
        app="cine",
    )
)
register_toolset(
    Toolset(
        id="cine_write",
        label="Atelier Ciné — analyse des dossiers",
        description="Relancer l'analyse de la médiathèque (avec validation).",
        build=lambda env: cine_write_tools(env.cine()),
        is_configured=lambda s: bool(s.cine_base_url),
        app="cine",
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="savoir_read",
        label="Atelier Savoir — lecture",
        description="Cours, chapitres, cartes de révision et séances du jour. Données personnelles : modèle local imposé.",
        build=lambda env: savoir_read_tools(env.savoir()),
        is_configured=lambda s: bool(s.savoir_base_url),
        app="savoir",
        sensitive=True,
    )
)
register_toolset(
    Toolset(
        id="savoir_write",
        label="Atelier Savoir — modifications",
        description="Créer un cours ou un chapitre, enregistrer des cartes et les résultats d'une interrogation (avec validation).",
        build=lambda env: savoir_write_tools(env.savoir()),
        is_configured=lambda s: bool(s.savoir_base_url),
        app="savoir",
        sensitive=True,
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="cuisine",
        label="Atelier Cuisine",
        description="Stock du foyer (ce qui presse d'abord), planning des repas et liste de courses, en lecture. App en ligne (Supabase).",
        build=lambda env: cuisine_tools(env.cuisine()),
        is_configured=lambda s: s.cuisine_configured,
        app="cuisine",
    )
)
register_toolset(
    Toolset(
        id="cuisine_budget",
        label="Atelier Cuisine — budget",
        description="Dépenses du mois par périmètre, plafonds, tickets de caisse, en lecture. Données financières : modèle local imposé.",
        build=lambda env: cuisine_budget_tools(env.cuisine()),
        is_configured=lambda s: s.cuisine_configured,
        app="cuisine",
        sensitive=True,
    )
)
register_toolset(
    Toolset(
        id="wiki",
        label="Atelier Wiki — lecture",
        description="Espaces, recherche plein texte, liste et contenu des pages (procédures, décisions, comptes rendus).",
        build=lambda env: wiki_read_tools(env),
        is_configured=lambda s: bool(s.wiki_base_url),
        app="wiki",
    )
)
register_toolset(
    Toolset(
        id="wiki_write",
        label="Atelier Wiki — rédaction",
        description="Créer une page ou un espace, compléter une page, réécrire une page (avec validation ; historique gardé).",
        build=lambda env: wiki_write_tools(env),
        is_configured=lambda s: bool(s.wiki_base_url),
        app="wiki",
        writes=True,
        shared=True,
    )
)
register_toolset(
    Toolset(
        id="equipe",
        label="Mémoire d'équipe — lecture",
        description="Journal, décisions et comptes rendus de l'équipe (espace « Équipe Atelier » d'Atelier Wiki).",
        build=lambda env: equipe_memory_tools(env),
        is_configured=lambda s: bool(s.wiki_base_url),
        app="wiki",
    )
)
register_toolset(
    Toolset(
        id="equipe_write",
        label="Mémoire d'équipe — écriture",
        description="Noter au journal, enregistrer une décision, ranger un compte rendu (avec validation).",
        build=lambda env: equipe_write_tools(env),
        is_configured=lambda s: bool(s.wiki_base_url),
        app="wiki",
        writes=True,
        shared=True,
    )
)
register_toolset(
    Toolset(
        id="equipe_rapports",
        label="Rapports de l'équipe",
        description="Point d'avancement calculé depuis Projets, synthèse agrégée des formulaires ouverts (sans modèle).",
        build=lambda env: equipe_report_tools(env),
        is_configured=lambda s: bool(s.projets_base_url or s.formulaire_base_url),
        app="projets",
    )
)
register_toolset(
    Toolset(
        id="formulaire",
        label="Atelier Formulaire — formulaires",
        description="Formulaires, questions et synthèse agrégée des réponses (sans réponse individuelle).",
        build=lambda env: formulaire_read_tools(env),
        is_configured=lambda s: bool(s.formulaire_base_url),
        app="formulaire",
    )
)
register_toolset(
    Toolset(
        id="formulaire_write",
        label="Atelier Formulaire — création",
        description="Créer un formulaire, l'ouvrir ou le fermer, choisir qui peut répondre (avec validation).",
        build=lambda env: formulaire_write_tools(env),
        is_configured=lambda s: bool(s.formulaire_base_url),
        app="formulaire",
        writes=True,
    )
)
register_toolset(
    Toolset(
        id="formulaire_reponses",
        label="Atelier Formulaire — réponses individuelles",
        description="Réponses une par une (répondants, textes libres). Données personnelles : modèle local imposé.",
        build=lambda env: formulaire_responses_tools(env),
        is_configured=lambda s: bool(s.formulaire_base_url),
        app="formulaire",
        sensitive=True,
    )
)
register_toolset(
    Toolset(
        id="github_read",
        label="GitHub — lecture",
        description="Dépôts autorisés : fichiers, recherche de code, pull requests, tickets.",
        build=lambda env: github_read_tools(env.github()),
        is_configured=lambda s: bool(s.github_repo_list),
        app="github",
    )
)
register_toolset(
    Toolset(
        id="github_write",
        label="GitHub — branches et PR",
        description="Créer une branche, committer des fichiers, ouvrir une PR brouillon (avec validation).",
        build=lambda env: github_write_tools(env.github()),
        is_configured=lambda s: bool(s.github_repo_list and s.github_token),
        app="github",
        writes=True,
    )
)


def is_sensitive(ids: list[str]) -> bool:
    return any(get_toolset(i).sensitive for i in ids)


def _blank_settings() -> Settings:
    """Réglages fictifs : toutes les boîtes se construisent, aucune adresse réelle n'est lue."""
    return Settings(
        _env_file=None,
        data_via_base_url="http://application.invalid/api",
        projets_base_url="http://application.invalid/api",
        tresorerie_base_url="http://application.invalid/api",
        cine_base_url="http://application.invalid/api",
        savoir_base_url="http://application.invalid/api",
        wiki_base_url="http://application.invalid/api",
        formulaire_base_url="http://application.invalid/api",
        tab_exports_dir="/dev/null",
        tab_mcp_command="atelier-mcp",
        github_repo="atelier/exemple",
        github_token="invalide",
        cuisine_supabase_url="https://application.invalid",
        cuisine_supabase_anon_key="invalide",
        cuisine_refresh_token="invalide",
    )


_BLANK: dict[str, list[BaseTool[Any]]] = {}


async def blank_tools(ids: list[str]) -> list[tuple[str, BaseTool[Any]]]:
    """(boîte, outil) de toutes les boîtes demandées, configurées ou non, pour lire leurs
    métadonnées (nom, schéma, validation). Construits à blanc avec des adresses fictives :
    aucun appel réseau, aucune lecture des réglages réels ; ces outils ne s'exécutent jamais.
    Gardés en mémoire par boîte (seules les métadonnées servent, clients fermés)."""
    missing = [i for i in ids if i not in _BLANK and i != "delegation"]
    if missing:
        env = ToolEnvironment(_blank_settings())
        try:
            for toolset_id in missing:
                _BLANK[toolset_id] = get_toolset(toolset_id).build(env)
        finally:
            await env.aclose()  # clients HTTP créés à blanc : jamais utilisés, toujours fermés
    out: list[tuple[str, BaseTool[Any]]] = []
    for toolset_id in ids:
        if toolset_id == "delegation":  # dépend de l'environnement (liste des agents)
            env = ToolEnvironment(_blank_settings())
            out += [(toolset_id, t) for t in get_toolset(toolset_id).build(env)]
            continue
        out += [(toolset_id, t) for t in _BLANK[toolset_id]]
    return out


async def declared_tool_names(ids: list[str]) -> set[str]:
    """Noms de tous les outils des boîtes demandées, configurées ou non.

    Sert à vérifier un nom d'outil même quand l'application correspondante n'est pas
    configurée sur cette machine."""
    return {tool.name for _, tool in await blank_tools(ids)}
