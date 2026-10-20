"""Mise en forme commune des résultats d'outils pour le modèle (tableaux, montants)."""

from __future__ import annotations

import json
import math
from typing import Any

from app.tools.base import Artifact

MAX_ROWS_FOR_MODEL = 50


def fmt(value: Any) -> str:
    """Valeur de cellule : précision conservée, jamais de notation scientifique."""
    if value is None:
        return "∅"
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        text = format(round(value, 4), "f") if abs(value) >= 1 else format(value, ".10f")
        return text.rstrip("0").rstrip(".") or "0"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 80 else text[:77] + "…"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "| " + " | ".join(fmt(h) for h in headers) + " |"
    sep = "|" + "---|" * len(headers)
    body = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join([head, sep, *body])


def euros(cents: int | None) -> str:
    """Montant en centimes → « 1234.56 € » (lisible et réutilisable par le modèle)."""
    if cents is None:
        return "∅"
    return f"{cents / 100:.2f} €"


def table_for_model(
    headers: list[str], rows: list[list[Any]], *, noun: str = "ligne"
) -> tuple[str, bool]:
    """Tableau tronqué à MAX_ROWS_FOR_MODEL lignes ; renvoie (texte, tronqué ?)."""
    shown = rows[:MAX_ROWS_FOR_MODEL]
    summary = f"{len(rows)} {noun}(s)"
    truncated = len(rows) > len(shown)
    if truncated:
        summary += f" ; {len(shown)} premières ci-dessous, la liste complète est dans l'artefact"
    return f"{summary}.\n{markdown_table(headers, shown)}", truncated


def data_artifact(
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    *,
    numeric: set[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    """Artefact `data_preview` (même format que les requêtes Data Via) pour le panneau."""
    numeric = numeric or set()
    columns = [
        {"key": h, "field": h, "role": "dimension", "type": "number" if h in numeric else "string"}
        for h in headers
    ]
    return Artifact(
        kind="data_preview",
        title=title,
        content=json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False, default=str),
        language="json",
        metadata=metadata or {},
    )
