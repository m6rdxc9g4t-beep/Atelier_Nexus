"""Cas d'évaluation : une demande réelle à un agent et ce qui doit être vrai à la fin.

Les cas vivent dans `evals/cases/*.toml` :

    [[case]]
    id = "data-schema-avant-requete"
    agent = "data_analyst"
    apps = ["data_via"]
    prompt = "Quel est le chiffre d'affaires total par région ?"
    rubric = "Donne le total de chaque région et nomme la région en tête."   # facultatif

    [case.expect]
    tools_in_order = ["data_via_describe_dataset", "data_via_query"]
    artifacts = [{ kind = "data_preview", title_contains = "Requete" }]
    grounded_numbers = "warn"

On évalue l'**état final** (outils appelés, livrables, validations demandées, réponse), pas
chaque étape : deux chemins différents vers le bon résultat sont tous deux justes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import ApprovalMode
from app.core.llm.types import ProviderName
from app.tools.base import ArtifactKind

CASES_DIR = Path(__file__).resolve().parent / "cases"

AppId = Literal[
    "data_via", "projets", "tresorerie", "tab", "cine", "savoir", "cuisine", "github"
]  # fmt: skip
Grounding = Literal["off", "warn", "strict"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactExpectation(_Strict):
    """Au moins un artefact publié correspond à tous les critères donnés."""

    kind: ArtifactKind | None = None
    title_contains: str | None = None
    content_contains: list[str] = Field(default_factory=list)
    #: Aucun de ces textes dans le contenu (ex. un critère discriminatoire écarté de l'annonce)
    content_not_contains: list[str] = Field(default_factory=list)
    content_regex: str | None = None
    #: Instructions d'intégration (`notes` de `publish_artifact`, ex. étapes dans Power BI Desktop)
    notes_contains: list[str] = Field(default_factory=list)


class ToolArgsExpectation(_Strict):
    """Un appel de `tool` dont l'entrée (JSON) contient chaque texte de `contains` ET dont chaque
    clé de premier niveau de `equals` vaut exactement la valeur donnée.

    `contains` (sans accents ni casse) convient aux textes libres (titre, message) ; `equals`
    aux identifiants et aux valeurs fermées : `story_id = 2` refuse 20 ou 21, que `contains`
    accepterait. Nombres comparés en valeur (2 = 2.0 = "2"), textes sans accents ni casse."""

    tool: str
    contains: list[str] = Field(default_factory=list)
    equals: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _something_to_check(self) -> Self:
        if not (self.contains or self.equals):
            raise ValueError(f"{self.tool} : renseigner `contains` ou `equals`")
        return self


class Expect(_Strict):
    #: Raisons d'arrêt acceptées (`end_turn`, `awaiting_approval`, `max_iterations`…)
    stop_reason: list[str] = Field(default_factory=lambda: ["end_turn"])
    tools_called: list[str] = Field(default_factory=list)
    #: Sous-séquence : ces outils sont appelés dans cet ordre (d'autres peuvent s'intercaler)
    tools_in_order: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)
    tool_args: list[ToolArgsExpectation] = Field(default_factory=list)
    #: Contrôle négatif : AUCUN appel de l'outil ne correspond (ex. un commit demandé sur main)
    tool_args_forbidden: list[ToolArgsExpectation] = Field(default_factory=list)
    #: Nombre maximal d'appels d'outils en erreur (entrée invalide, refus de validation locale…)
    tool_errors_max: int | None = None
    #: Outils en attente de validation à la fin du tour (et donc jamais exécutés)
    approval_requested: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactExpectation] = Field(default_factory=list)
    #: Tous ces textes figurent dans la réponse finale (sans accents ni casse)
    text_contains: list[str] = Field(default_factory=list)
    #: Au moins un de ces textes figure dans la réponse finale
    text_contains_any: list[str] = Field(default_factory=list)
    text_not_contains: list[str] = Field(default_factory=list)
    #: Motif (expression régulière) sur le texte BRUT de la réponse : insensible à la casse,
    #: accents conservés
    text_regex: str | None = None
    #: Comme `text_*`, mais sur la réponse ET les artefacts publiés (contenu et notes) : un
    #: livrable peut arriver dans le chat s'il est court, ou dans le panneau s'il est long
    output_contains: list[str] = Field(default_factory=list)
    output_contains_any: list[str] = Field(default_factory=list)
    output_not_contains: list[str] = Field(default_factory=list)
    #: Les nombres de la réponse viennent des outils (« pas de chiffre inventé »)
    grounded_numbers: Grounding = "off"
    max_iterations: int | None = None
    #: Moteur effectivement utilisé (verrou local : `ollama`)
    provider: ProviderName | None = None
    #: Le tour doit échouer avec ce code (ex. `provider_not_allowed`)
    error_code: str | None = None


class EvalCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    agent: str
    prompt: str = Field(min_length=3)
    description: str = ""
    #: Applications nécessaires ; le cas est ignoré si l'une manque
    apps: list[AppId] = Field(default_factory=list)
    #: Moteur imposé pour ce cas (sinon celui de la ligne de commande)
    provider: ProviderName | None = None
    #: Mode de validation joué. `writes_only` (défaut) : seules les écritures arrêtent le tour.
    #: `every_step` (mode par défaut de l'interface) : chaque appel attend « Autoriser » ; sur les
    #: applications simulées, l'évaluation autorise les lectures et délégations par des requêtes
    #: séparées, comme l'interface, et ne valide JAMAIS une écriture (docs/evaluations.md §2).
    approval_mode: ApprovalMode = "writes_only"
    tags: list[str] = Field(default_factory=list)
    expect: Expect = Field(default_factory=Expect)
    #: Critère jugé par un modèle (option --judge), en une ou deux phrases
    rubric: str | None = None
    #: Fichier d'origine (renseigné au chargement)
    source: str = ""


class CaseFileError(ValueError):
    pass


def load_file(path: Path) -> list[EvalCase]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CaseFileError(f"{path.name} : TOML invalide ({exc})") from exc
    unknown = set(data) - {"case"}
    if unknown:
        raise CaseFileError(
            f"{path.name} : clés inattendues {sorted(unknown)} (attendu : [[case]])"
        )
    cases = []
    for index, raw in enumerate(data.get("case", []), start=1):
        try:
            cases.append(EvalCase.model_validate({**raw, "source": path.name}))
        except ValidationError as exc:
            raise CaseFileError(f"{path.name}, cas n° {index} : {exc}") from exc
    return cases


def load_cases(directory: Path = CASES_DIR) -> list[EvalCase]:
    """Tous les cas, triés par fichier ; identifiants uniques."""
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.toml")):
        cases.extend(load_file(path))
    seen: dict[str, str] = {}
    for case in cases:
        if case.id in seen:
            raise CaseFileError(
                f"Identifiant en double « {case.id} » ({seen[case.id]}, {case.source})"
            )
        seen[case.id] = case.source
    return cases


def select(
    cases: list[EvalCase],
    *,
    agents: list[str] | None = None,
    ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[EvalCase]:
    """Filtre par agent, par identifiant (préfixe accepté) et par étiquette."""
    out = cases
    if agents:
        out = [c for c in out if c.agent in agents]
    if ids:
        out = [c for c in out if any(c.id == i or c.id.startswith(i) for i in ids)]
    if tags:
        out = [c for c in out if set(tags) & set(c.tags)]
    return out
