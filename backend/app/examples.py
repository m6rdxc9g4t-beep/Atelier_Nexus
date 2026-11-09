"""Exemples de la suite (`exemples-suite/`, format `atelier-exemples/1`) : histoires fictives
communes à toutes les applications, générées par Atelier_Deploy (`exemples/generer.py`).

Pour Nexus, une histoire apporte des modèles de la bibliothèque (`workflows_v2/library.py`) et
des références vers ce que les autres applications ont chargé (projet Tab, clé du jeu Viz, nom de
l'alerte, projet et story Projets). Ce module est pur : il lit les fichiers, résout les
références à partir des réponses des applications et prépare les corps des workflows et du
déclencheur. Les appels (applications, base) sont dans `app/api/examples.py`.

Un workflow d'exemple se reconnaît à sa marque `[exemple:<id>]` en fin de description : la
retirer (ou modifier la description) le rend à l'utilisateur, qui le garde au retrait.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.workflows_v2 import WorkflowTemplate, WorkflowV2Create

FORMAT = "atelier-exemples/1"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MARK = re.compile(r"\[exemple:([a-z0-9][a-z0-9-]{0,63})\]\s*$")
#: Dossier du dépôt (backend/app/examples.py → <dépôt>/exemples-suite)
REPO_DIR = Path(__file__).resolve().parents[2] / "exemples-suite"
ALERT_TEMPLATE = "viz-alerte-tache-projets"
DESCRIPTION_MAX = 500


class ExampleError(Exception):
    """Histoire absente ou fichier illisible (→ 404)."""


def folder(setting: str | None) -> Path:
    return Path(setting).expanduser() if setting else REPO_DIR


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExampleError(f"{path.name} illisible") from exc


def stories(base: Path) -> list[dict[str, Any]]:
    """Histoires de l'index (format vérifié, identifiants sûrs) ; liste vide sans index."""
    try:
        index = _read(base / "index.json")
    except ExampleError:
        return []
    if not isinstance(index, dict) or index.get("format") != FORMAT:
        return []
    out = []
    for story in index.get("histoires") or []:
        if isinstance(story, dict) and SAFE_ID.match(str(story.get("id", ""))):
            out.append(story)
    return out


def part(base: Path, story_id: str) -> dict[str, Any]:
    """Part Nexus d'une histoire de l'index (jamais un chemin libre)."""
    if not any(s["id"] == story_id for s in stories(base)):
        raise ExampleError(f"Exemple « {story_id} » introuvable.")
    data = _read(base / f"{story_id}.json")
    if (
        not isinstance(data, dict)
        or data.get("format") != FORMAT
        or not isinstance(data.get("workflows"), list)
        or not isinstance(data.get("references"), dict)
    ):
        raise ExampleError(f"Exemple « {story_id} » illisible.")
    return data


def mark_of(description: str) -> str | None:
    """Identifiant de l'histoire d'un workflow d'exemple (marque en fin de description)."""
    found = MARK.search(description or "")
    return found.group(1) if found else None


# ─── Résolution des références ────────────────────────────────────


def dataset_id(datasets: Any, key: str) -> str | None:
    """Id du jeu Viz dont la clé externe (`origin.key`, jeu alimenté par un nœud) est `key`."""
    if not isinstance(datasets, list):
        return None
    for item in datasets:
        origin = item.get("origin") if isinstance(item, dict) else None
        if isinstance(origin, dict) and origin.get("key") == key and item.get("id"):
            return str(item["id"])
    return None


def project_id(projects: Any, name: str) -> int | None:
    if not isinstance(projects, list):
        return None
    for item in projects:
        if isinstance(item, dict) and item.get("name") == name and isinstance(item.get("id"), int):
            return int(item["id"])
    return None


def story_id(tree: Any, title: str) -> int | None:
    """N° de la story `title` dans l'arbre d'un projet (phases › epics › stories)."""
    if not isinstance(tree, dict):
        return None
    for phase in tree.get("phases") or []:
        for epic in (phase or {}).get("epics") or []:
            for story in (epic or {}).get("stories") or []:
                if (
                    isinstance(story, dict)
                    and story.get("title") == title
                    and isinstance(story.get("id"), int)
                ):
                    return int(story["id"])
    return None


@dataclass
class Resolved:
    """Références trouvées dans les applications (None : absente, avec la raison dans notes)."""

    jeu: str | None = None
    #: N° du projet de l'histoire dans Atelier Projets
    projet: int | None = None
    story: int | None = None
    notes: list[str] = field(default_factory=list)


# ─── Corps des workflows et du déclencheur ────────────────────────


def _description(template: WorkflowTemplate, titre: str, story: str) -> str:
    tail = f"\n\nExemple de la suite « {titre} ». [exemple:{story}]"
    room = DESCRIPTION_MAX - len(tail)
    text = template.description
    if len(text) > room:
        text = text[: room - 1].rstrip() + "…"
    return text + tail


def defaults_for(data: dict[str, Any], resolved: Resolved) -> dict[str, str]:
    """Valeurs des paramètres d'un modèle pour l'histoire (vides si non résolues). Les noms de
    paramètres sont ceux de la bibliothèque ; un paramètre inconnu garde sa valeur par défaut."""
    refs = data["references"]
    story = data["histoire"]["id"]
    tables = [str(t) for t in refs.get("tab_tables") or []]
    # Table métier de l'histoire (planning, backlog…) : la première après celle des opérations
    business = tables[1] if len(tables) > 1 else ""
    values = {
        "projet_tab": str(refs.get("tab_projet") or ""),
        "table": business,
        "table_budget": tables[0] if tables else "",
        "projet": str(resolved.projet) if resolved.projet is not None else "",
        "jeu": resolved.jeu or "",
        "alerte": str(refs.get("viz_alerte") or ""),
        "valeur": str(refs.get("valeur") or ""),
        "seuil": str(refs.get("seuil") or ""),
        "story": str(resolved.story) if resolved.story is not None else "",
        # Jeux Viz écrits par les workflows de l'histoire : une clé par histoire
        "cle_viz": f"exemple:{story}:suivi",
        "cle_temps": f"exemple:{story}:temps",
        "cle_elements": f"exemple:{story}:elements",
    }
    return {k: v for k, v in values.items() if v}


def workflow_body(
    template: WorkflowTemplate, data: dict[str, Any], resolved: Resolved
) -> WorkflowV2Create:
    """Le modèle copié en workflow de l'histoire : titre, marque, paramètres préremplis."""
    histoire = data["histoire"]
    defaults = defaults_for(data, resolved)
    params = [
        p.model_copy(update={"default": defaults[p.name]}) if defaults.get(p.name) else p
        for p in template.params
    ]
    title = f"{template.title} · {histoire['titre']}"
    return WorkflowV2Create(
        version=2,
        agent=None,
        title=title[:120],
        description=_description(template, histoire["titre"], histoire["id"]),
        steps=template.steps,
        params=params,
    )


def alert_trigger(data: dict[str, Any], resolved: Resolved) -> dict[str, Any]:
    """Déclencheur de l'alerte Viz de l'histoire (filtré sur son nom). Actif seulement si la
    story Projets est connue : sinon la tâche n'aurait nulle part où aller."""
    refs = data["references"]
    params = {
        "jeu": "{{event.data.dataset_id}}",
        "alerte": "{{event.subject.label}}",
        "valeur": "{{event.data.value}}",
        "seuil": "{{event.data.threshold}}",
    }
    if resolved.story is not None:
        params["story"] = str(resolved.story)
    return {
        "kind": "event",
        "label": f"Alerte « {refs.get('viz_alerte')} »"[:120],
        "enabled": resolved.story is not None,
        "app": "viz",
        "types": ["viz.alert.triggered"],
        "filters": [{"path": "subject.label", "op": "eq", "value": str(refs.get("viz_alerte"))}],
        "params": params,
        "max_runs_per_hour": 2,
        "debounce_seconds": 0,
    }
