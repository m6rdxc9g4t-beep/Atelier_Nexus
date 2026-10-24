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
from typing import Any, ClassVar

from app.suite.apps import app_name
from app.suite.nodes import SuiteNodes
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
        """Exécute une action du manifeste ; `idempotent_on` (écritures) : clé stable dérivée
        de ces valeurs, pour qu'une même écriture validée deux fois ne crée rien en double."""
        key = idempotency_key(self.app, action_id, idempotent_on) if idempotent_on else None
        result = await self.suite.run_action(self.app, action_id, payload, idempotency_key=key)
        return result.data

    async def http(self, method: str, path: str, body: Any = None) -> Any:
        """Route hors manifeste, lue dans le dépôt de l'application (même client, mêmes gardes)."""
        response = await self.suite.http(self.app).call(method, path, json_body=body)
        return response.body


def idempotency_key(app: str, action: str, values: Any) -> str:
    raw = json.dumps([app, action, values], ensure_ascii=False, sort_keys=True, default=str)
    return f"nexus-{hashlib.sha256(raw.encode()).hexdigest()[:40]}"


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
        markdown_table(headers, rows[:MAX_ROWS_FOR_MODEL]),
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


def as_data(text: str, *, kind: str, limit: int = 30_000) -> str:
    """Contenu d'une application présenté au modèle comme une DONNÉE, borné et délimité."""
    cut = text[:limit]
    more = (
        f"\n[… {len(text) - limit} caractère(s) de plus non montrés]" if len(text) > limit else ""
    )
    safe = cut.replace("</donnee>", "</ donnee>")
    return f'<donnee type="{kind}">\n{safe}{more}\n</donnee>'


class NoInput(ToolInput):
    pass
