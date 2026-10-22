"""Socle des outils d'agents.

Un outil = un schéma d'entrée Pydantic strict + une coroutine `run`.
Son JSON Schema est rendu portable (références `$ref` déroulées) pour être
accepté à l'identique par l'API Anthropic (Tool Use) et par Ollama.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.types import ToolSpec
from app.tools.labels import default_summary, tool_label

logger = logging.getLogger(__name__)

ArtifactKind = Literal[
    "sql", "dax", "powerquery", "python", "react", "code", "markdown", "json", "data_preview"
]


class Artifact(BaseModel):
    """Livrable destiné au panneau latéral (`useArtifactStore` côté frontend)."""

    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    title: str = Field(min_length=1, max_length=200)
    content: str
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Texte renvoyé au modèle : concis, factuel
    content: str
    is_error: bool = False
    # Livrables affichés à l'utilisateur, hors du fil de discussion
    artifacts: list[Artifact] = Field(default_factory=list)
    # Sortie structurée (JSON : table `atelier-table/1` ou fiche) pour les workflows v2.
    # Jamais envoyée au modèle : seul `content` l'est.
    data: Any = None


class ToolContext(BaseModel):
    """Contexte d'exécution transmis aux outils (identité, conversation…)."""

    conversation_id: str | None = None
    user_id: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    # État partagé entre les outils pendant UN tour d'agent (ex. schémas déjà consultés)
    state: dict[str, Any] = Field(default_factory=dict)


#: Sérialisation de clés de `ToolContext.state` (objets Python) pour qu'un workflow v2 repris
#: après une validation retrouve le contexte des étapes déjà exécutées : clé → (export, import)
STATE_CODECS: dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any]]] = {}


def register_state_codec(key: str, dump: Callable[[Any], Any], load: Callable[[Any], Any]) -> None:
    STATE_CODECS[key] = (dump, load)


def dump_state(state: dict[str, Any]) -> dict[str, Any]:
    """Partie sérialisable du contexte partagé (clés enregistrées seulement)."""
    return {k: STATE_CODECS[k][0](v) for k, v in state.items() if k in STATE_CODECS}


def load_state(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in STATE_CODECS:
            try:
                out[key] = STATE_CODECS[key][1](value)
            except (ValueError, TypeError):
                continue  # contexte illisible : l'outil redemandera l'étape préalable
    return out


class ToolInput(BaseModel):
    """Base des schémas d'entrée : stricts, champs inconnus refusés."""

    model_config = ConfigDict(extra="forbid")


class BaseTool[InputT: ToolInput](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: type[InputT]
    # Erreurs prévisibles : renvoyées au modèle telles quelles, sans trace dans les journaux
    expected_errors: ClassVar[tuple[type[Exception], ...]] = ()
    # Action qui modifie des données : l'agent s'arrête et attend « Autoriser » / « Refuser »
    requires_approval: ClassVar[bool] = False
    # Données sensibles (finances…) : l'agent qui l'utilise est verrouillé sur un modèle local
    sensitive: ClassVar[bool] = False
    # Forme de `ToolOutput.data` annoncée au catalogue des workflows v2
    output_format: ClassVar[Literal["atelier-table/1", "json", "text"]] = "text"
    # Colonnes (`{key, label, type}`) ou champs attendus, quand ils sont connus d'avance
    output_hint: ClassVar[dict[str, Any] | None] = None

    @abstractmethod
    async def run(self, params: InputT, ctx: ToolContext) -> ToolOutput:
        """Logique métier de l'outil. Les exceptions sont converties en erreur d'outil."""

    @property
    def label(self) -> str:
        """Nom lisible (« Data Via · requête ») pour les cartes de validation."""
        return tool_label(self.name, self.description)

    def approval_summary(self, params: InputT) -> str:
        """Phrase montrée à l'utilisateur avant validation. Par défaut : nom lisible et
        paramètres principaux (« Data Via · requête : dataset = « ventes », limit = 50 ») ;
        un outil d'écriture la surcharge (« Créer la TASK … »)."""
        return default_summary(self.label, params.model_dump(exclude_none=True))

    def summarize(self, raw_input: dict[str, Any]) -> str:
        """Résumé d'un appel brut (entrée invalide : on le dit, l'outil la refusera)."""
        try:
            return self.approval_summary(self.input_model.model_validate(raw_input))
        except ValidationError:
            return f"{self.label} (paramètres invalides)"

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=portable_schema(self.input_model),
        )

    async def invoke(self, raw_input: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        """Valide l'entrée brute du modèle puis exécute. Ne lève jamais : le modèle
        reçoit l'erreur sous forme de `tool_result` et peut corriger son appel."""
        try:
            params = self.input_model.model_validate(raw_input)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(racine)'}: {e['msg']}"
                for e in exc.errors()
            )
            return ToolOutput(content=f"Paramètres invalides — {details}", is_error=True)
        try:
            return await self.run(params, ctx)
        except self.expected_errors as exc:
            logger.info("Outil %s : %s", self.name, exc)
            return ToolOutput(content=str(exc), is_error=True)
        except Exception as exc:
            logger.exception("Échec de l'outil %s", self.name)
            return ToolOutput(content=f"Erreur pendant l'exécution : {exc}", is_error=True)


def portable_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema sans `$ref`/`$defs` ni titres : la forme la plus largement
    supportée par les modèles locaux comme par Claude."""
    schema = model.model_json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})

    def resolve(node: Any, stack: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in stack:
                    raise ValueError(f"Schéma récursif non supporté par les outils : {name}")
                target = resolve(defs[name], (*stack, name))
                extra = {k: resolve(v, stack) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            # « title » annotatif (chaîne) retiré ; une propriété nommée « title » est conservée
            return {
                k: resolve(v, stack)
                for k, v in node.items()
                if not (k == "title" and isinstance(v, str))
            }
        if isinstance(node, list):
            return [resolve(v, stack) for v in node]
        return node

    resolved: dict[str, Any] = resolve(schema, ())
    resolved.setdefault("type", "object")
    resolved.setdefault("properties", {})
    return resolved
