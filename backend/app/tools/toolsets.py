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
from app.tools.artifacts import PublishArtifactTool
from app.tools.base import BaseTool
from app.tools.cine import cine_read_tools, cine_write_tools
from app.tools.data_via import DataViaNotConfiguredError, data_via_tools
from app.tools.environment import ToolEnvironment
from app.tools.github import github_read_tools, github_write_tools
from app.tools.http import AppNotConfiguredError
from app.tools.projets import projets_read_tools, projets_write_tools
from app.tools.savoir import savoir_read_tools, savoir_write_tools
from app.tools.system import CurrentDateTimeTool
from app.tools.tab import tab_tools
from app.tools.tab_mcp import tab_write_tools
from app.tools.tresorerie import tresorerie_tools


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


def build_tools(
    ids: list[str], env: ToolEnvironment
) -> tuple[list[BaseTool[Any]], list[UnavailableToolset]]:
    """Outils des boîtes demandées, dans l'ordre, sans doublon de nom.

    Une boîte non configurée (adresse ou jeton absent) est écartée et signalée :
    l'agent reste utilisable avec ses autres outils.
    """
    tools: list[BaseTool[Any]] = []
    unavailable: list[UnavailableToolset] = []
    seen: set[str] = set()
    for toolset_id in ids:
        toolset = get_toolset(toolset_id)
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
