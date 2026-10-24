"""Socle des connecteurs bâtis sur le contrat `atelier-node/1` (Atelier Wiki, Atelier Formulaire).

Les actions déclarées par le manifeste de l'application passent par `SuiteNodes.run_action` :
adresse de bouclage seulement, entrée validée contre le schéma publié, idempotence par
`Idempotency-Key`, erreurs `{detail, code}` relayées. Les quelques routes hors manifeste
(création d'un formulaire, d'un espace) passent par le même client HTTP de nœud, donc par les
mêmes garde-fous. Aucune route n'est inventée : chacune est citée dans le module du connecteur.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, ClassVar

from app.suite.apps import app_name
from app.suite.nodes import NodeResult, SuiteNodes
from app.tools.base import BaseTool, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.tools.formatting import data_artifact, is_atelier_table, markdown_table
from app.tools.http import AppError

MAX_ROWS_FOR_MODEL = 50


class NodeTool[InputT: ToolInput](BaseTool[InputT]):
    """Outil d'une application `atelier-node/1` : `app` fixe, nœuds créés à la demande."""

    app: ClassVar[str]
    expected_errors: ClassVar[tuple[type[Exception], ...]] = (AppError,)

    def __init__(self, env: ToolEnvironment) -> None:
        self.env = env

    @property
    def suite(self) -> SuiteNodes:
        return self.env.suite()

    async def action(
        self, action_id: str, payload: dict[str, Any], *, idempotent_on: Any = None
    ) -> Any:
        """Exécute une action du manifeste et rend ses données (voir `run_node`)."""
        return (await self.run_node(action_id, payload, idempotent_on=idempotent_on)).data

    async def run_node(
        self, action_id: str, payload: dict[str, Any], *, idempotent_on: Any = None
    ) -> NodeResult:
        """Action du manifeste ; `idempotent_on` (écritures) : clé stable dérivée de ces valeurs,
        pour qu'une même écriture validée deux fois ne crée rien en double. Le résultat dit si
        l'application a rejoué une écriture déjà faite (`replayed`) : à signaler au modèle."""
        key = idempotency_key(self.app, action_id, idempotent_on) if idempotent_on else None
        return await self.suite.run_action(self.app, action_id, payload, idempotency_key=key)

    async def http(self, method: str, path: str, body: Any = None) -> Any:
        """Route hors manifeste, lue dans le dépôt de l'application (même client, mêmes gardes)."""
        response = await self.suite.http(self.app).call(method, path, json_body=body)
        return response.body


def idempotency_key(app: str, action: str, values: Any) -> str:
    raw = json.dumps([app, action, values], ensure_ascii=False, sort_keys=True, default=str)
    return f"nexus-{hashlib.sha256(raw.encode()).hexdigest()[:40]}"


REPLAYED = (
    " (écriture identique déjà faite récemment : l'application a rendu le résultat précédent, "
    "rien de nouveau n'a été écrit)"
)


def rows_of(app: str, data: Any) -> list[dict[str, Any]]:
    """Lignes d'une table `atelier-table/1` ; réponse mal formée → erreur claire (sans trace)."""
    if not is_atelier_table(data):
        raise AppError(f"Réponse inattendue de {app_name(app)} (table attendue).", app=app)
    return [r for r in data["rows"] if isinstance(r, dict)]


def table_output(
    app: str, data: Any, *, noun: str = "ligne", empty: str = "Aucun résultat."
) -> ToolOutput:
    """Table `atelier-table/1` → tableau Markdown borné pour le modèle ; détail en artefact."""
    if not is_atelier_table(data):
        return ToolOutput(content=f"Réponse inattendue de {app_name(app)}.", is_error=True)
    columns = [
        c
        for c in data["columns"]
        if isinstance(c, dict) and "key" in c and c["key"] not in ("url", "chemin")
    ]
    keys = [c["key"] for c in columns]
    headers = [str(c.get("label") or c["key"]) for c in columns]
    rows = [[r.get(k) for k in keys] for r in data["rows"] if isinstance(r, dict)]
    if not rows:
        return ToolOutput(content=empty, data=data)
    total = data.get("total")
    lines = [
        f"{len(rows)} {noun}(s)"
        + (f" sur {total}" if isinstance(total, int) and total > len(rows) else "")
        + (" (liste tronquée)" if data.get("truncated") else "")
        + " :",
        as_data(
            markdown_table(headers, rows[:MAX_ROWS_FOR_MODEL]), kind=f"{app_name(app)} · {noun}s"
        ),
    ]
    artifacts = []
    if len(rows) > MAX_ROWS_FOR_MODEL:
        lines.append(f"[{len(rows) - MAX_ROWS_FOR_MODEL} {noun}(s) de plus dans l'artefact]")
        numeric = {h for h, c in zip(headers, columns, strict=True) if c.get("type") == "number"}
        artifacts.append(
            data_artifact(
                f"{app_name(app)} · {data.get('label') or noun}", headers, rows, numeric=numeric
            )
        )
    return ToolOutput(content="\n".join(lines), artifacts=artifacts, data=data)


_TAG = re.compile(r"<\s*/?\s*donnee", re.IGNORECASE)


def escape_data(text: str) -> str:
    """Neutralise toute balise `<donnee` / `</donnee` (casse, espaces) dans un contenu d'app."""
    return _TAG.sub(lambda m: m.group(0).replace("<", "‹"), text)


def as_data(text: str, *, kind: str, limit: int = 30_000, keep: str = "start") -> str:
    """Contenu d'une application présenté au modèle comme une DONNÉE, borné et délimité.

    `keep="end"` garde la fin (journal : les notes les plus récentes sont en bas)."""
    head = tail = ""
    cut = text
    if len(text) > limit:
        hidden = len(text) - limit
        if keep == "end":
            cut, head = text[-limit:], f"[… {hidden} caractère(s) plus anciens non montrés]\n"
        else:
            cut, tail = text[:limit], f"\n[… {hidden} caractère(s) de plus non montrés]"
    label = re.sub(r"[^\w ·'’-]", "", kind)[:80]
    return f'<donnee type="{label}">\n{head}{escape_data(cut)}{tail}\n</donnee>'


class NoInput(ToolInput):
    pass
