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
    artifacts = [{ kind = "data_preview" }]
    grounded_numbers = "warn"

On évalue l'**état final** (outils appelés, livrables, validations demandées, réponse), pas
chaque étape : deux chemins différents vers le bon résultat sont tous deux justes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    content_regex: str | None = None


class ToolArgsExpectation(_Strict):
    """Au moins un appel de `tool` dont l'entrée (JSON) contient chaque texte de `contains`."""

    tool: str
    contains: list[str] = Field(min_length=1)


class Expect(_Strict):
    #: Raisons d'arrêt acceptées (`end_turn`, `awaiting_approval`, `max_iterations`…)
    stop_reason: list[str] = Field(default_factory=lambda: ["end_turn"])
    tools_called: list[str] = Field(default_factory=list)
    #: Sous-séquence : ces outils sont appelés dans cet ordre (d'autres peuvent s'intercaler)
    tools_in_order: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)
    tool_args: list[ToolArgsExpectation] = Field(default_factory=list)
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
    text_regex: str | None = None
    #: Au moins un de ces textes figure dans la réponse OU dans un artefact publié (un livrable
    #: peut arriver dans le chat s'il est court, ou dans le panneau s'il est long)
    output_contains_any: list[str] = Field(default_factory=list)
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
