"""Mise en forme commune des résultats d'outils pour le modèle (tableaux, montants)."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal

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
    finite = [
        [None if isinstance(v, float) and not math.isfinite(v) else v for v in r] for r in rows
    ]
    return Artifact(
        kind="data_preview",
        title=title,
        # NaN / Infinity : JSON invalide pour le navigateur → vides (allow_nan=False en garde-fou)
        content=json.dumps(
            {"columns": columns, "rows": finite}, ensure_ascii=False, default=str, allow_nan=False
        ),
        language="json",
        metadata=metadata or {},
    )


# ─── Table d'échange `atelier-table/1` (docs/apps/noeud-atelier.md §7.2) ──────

TABLE_FORMAT = "atelier-table/1"
TableType = Literal["string", "number", "date", "datetime", "boolean"]
_KEY_CHARS = re.compile(r"[^a-z0-9]+")


def snake_key(text: str) -> str:
    """Clé `snake_case` sans accent : « Coût HT » → `cout_ht`, `sum(ca)` → `sum_ca`."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    key = _KEY_CHARS.sub("_", plain).strip("_")
    if not key:
        return "colonne"
    return key if key[0].isalpha() else f"c_{key}"


def cell_value(value: Any) -> Any:
    """Valeur JSON d'une cellule : dates en ISO 8601, vide = `null`."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value == "":
        return None
    return value


def atelier_table(
    name: str,
    label: str,
    columns: Sequence[tuple[str, str, TableType]],
    rows: Sequence[Sequence[Any]],
    *,
    total: int | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Table `atelier-table/1`. `columns` : `(clé, libellé, type)` ; la clé est normalisée en
    `snake_case` et rendue unique ; `rows` : valeurs dans l'ordre des colonnes."""
    keys: list[str] = []
    for key, _, _ in columns:
        base = snake_key(key) if not key.startswith("_") else key
        candidate, n = base, 2
        while candidate in keys:
            candidate, n = f"{base}_{n}", n + 1
        keys.append(candidate)
    return {
        "format": TABLE_FORMAT,
        "name": name,
        "label": label,
        "columns": [
            {"key": k, "label": lbl, "type": t}
            for k, (_, lbl, t) in zip(keys, columns, strict=True)
        ],
        "rows": [{k: cell_value(v) for k, v in zip(keys, row, strict=False)} for row in rows],
        "total": len(rows) if total is None and not truncated else total,
        "truncated": truncated,
    }


def is_atelier_table(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("format") == TABLE_FORMAT
        and isinstance(value.get("columns"), list)
        and isinstance(value.get("rows"), list)
    )


def table_hint(*columns: tuple[str, str, TableType]) -> dict[str, Any]:
    """`output_hint` d'un outil qui renvoie une table aux colonnes connues d'avance."""
    return {"columns": [{"key": k, "label": lbl, "type": t} for k, lbl, t in columns]}
