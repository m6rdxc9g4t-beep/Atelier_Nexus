"""Jeu de travail : colonnes typées en mémoire, et inférence des types d'un fichier.

Types : `number`, `string`, `date` (ISO `AAAA-MM-JJ`, ou date-heure ISO), `boolean`.
Valeur manquante = `None`. Les nombres d'un fichier sont lus au format français d'abord
(« 1 234,56 », « 12,5 % », « 1.234,56 € ») puis anglais (« 1,234.56 »).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

ColumnType = Literal["number", "string", "date", "boolean"]

MISSING_TOKENS = {
    "", "na", "n/a", "n.a.", "nan", "null", "none", "nil", "-", "—", "–", "#n/a", "#na", "?",
    "nd", "n.d.", "#valeur!", "#value!", "#div/0!", "#ref!", "#nom?", "#name?",
}  # fmt: skip
_TRUE = {"oui", "vrai", "true", "yes", "x", "✓", "1"}
_FALSE = {"non", "faux", "false", "no", "0"}
_NUMBER_CHARS = re.compile(r"[\s  €$£¥%]|eur\b|chf\b", re.IGNORECASE)
_UNITS = re.compile(r"[€$£¥%]|\beur\b|\bchf\b", re.IGNORECASE)
_SPACES = re.compile(r"[\s\u00a0\u202f]")
_SPACED_THOUSANDS = re.compile(r"^[+\-−]?\s*\d{1,3}([\s\u00a0\u202f]\d{3})+([.,]\d+)?$")
_LEADING_ZERO = re.compile(r"^0\d+$")  # code postal, client, téléphone : à garder en texte
_AMBIGUOUS = re.compile(r"^\d{1,3}[.,]\d{3}$")  # « 1,234 » : milliers anglais ou décimale ?
_DATE_DMY = re.compile(
    r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_DATE_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_NUM_FR = re.compile(r"^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_NUM_EN = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_NUM_SCI = re.compile(r"^[+-]?\d+([.,]\d+)?[eE][+-]?\d+$")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    return isinstance(value, str) and value.strip().lower() in MISSING_TOKENS


def parse_number(value: Any) -> float | None:
    """Nombre d'une cellule (int, float ou texte français / anglais) ; None si illisible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    negative = text.startswith("(") and text.endswith(")")  # (1 234,00) = négatif comptable
    if negative:
        text = text[1:-1]
    text = _UNITS.sub("", text).strip()
    # Espaces dans le nombre : seulement des groupes de milliers (« 1 234 567,8 »), jamais un
    # numéro de téléphone (« 06 12 34 56 78 ») ni deux nombres collés
    if _SPACES.search(text) and not _SPACED_THOUSANDS.match(text):
        return None
    text = _NUMBER_CHARS.sub("", text).replace("−", "-").replace("'", "")
    if not text:
        return None
    if _NUM_SCI.match(text):
        out = float(text.replace(",", "."))
    elif "," in text and "." in text:
        # Le dernier séparateur est le séparateur décimal
        if text.rfind(",") > text.rfind("."):
            if not _NUM_FR.match(text):
                return None
            out = float(text.replace(".", "").replace(",", "."))
        else:
            if not _NUM_EN.match(text):
                return None
            out = float(text.replace(",", ""))
    elif "," in text:
        # Virgule décimale (français), sauf groupes de milliers multiples « 1,234,567 »
        if re.match(r"^[+-]?\d{1,3}(,\d{3}){2,}$", text):
            out = float(text.replace(",", ""))
        elif re.match(r"^[+-]?\d+,\d+$", text):
            out = float(text.replace(",", "."))
        else:
            return None
    elif text.count(".") > 1:
        if not _NUM_FR.match(text):
            return None
        out = float(text.replace(".", ""))
    else:
        try:
            out = float(text)
        except ValueError:
            return None
    if not math.isfinite(out):
        return None
    return -out if negative else out


def parse_date(value: Any) -> str | None:
    """Date ISO (`AAAA-MM-JJ`, ou `AAAA-MM-JJTHH:MM:SS`) d'une cellule ; None si illisible.
    Les dates à barres obliques sont lues jour/mois/année (usage français)."""
    if isinstance(value, datetime):
        return (
            value.date().isoformat()
            if value.time() == datetime.min.time()
            else (value.replace(microsecond=0, tzinfo=None).isoformat())
        )
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _DATE_ISO.match(text)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        hh, mm, ss = m[4], m[5], m[6]
    else:
        m = _DATE_DMY.match(text)
        if not m:
            return None
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        y = y + 2000 if y < 100 and y < 70 else (y + 1900 if y < 100 else y)
        hh, mm, ss = m[4], m[5], m[6]
    try:
        day = date(y, mo, d)
    except ValueError:
        return None
    if hh is None:
        return day.isoformat()
    try:
        return datetime(y, mo, d, int(hh), int(mm), int(ss or 0)).isoformat()
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return None


def date_ordinal(iso: str) -> float:
    """Jours depuis le 1er janvier de l'an 1 (fraction de jour pour une date-heure)."""
    if "T" in iso:
        dt = datetime.fromisoformat(iso)
        return dt.toordinal() + (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400
    return float(date.fromisoformat(iso).toordinal())


@dataclass
class Inference:
    type: ColumnType
    values: list[Any]
    #: Valeurs présentes mais illisibles dans le type retenu (mises à vide)
    invalid: int = 0
    invalid_examples: list[str] = field(default_factory=list)
    #: Avertissements de lecture (codes à zéro initial, séparateurs ambigus)
    notes: list[str] = field(default_factory=list)


def _clean_text(value: Any) -> Any:
    if isinstance(value, str):
        text = unicodedata.normalize("NFC", value)
        return None if is_missing(text) else text
    return None if is_missing(value) else value


def infer_column(raw: Sequence[Any], *, threshold: float = 0.95) -> Inference:
    """Type d'une colonne brute. Un type est retenu si au moins `threshold` des valeurs
    présentes s'y lisent ; les autres sont mises à vide et comptées comme invalides."""
    values = [_clean_text(v) for v in raw]
    present = [v for v in values if v is not None]
    if not present:
        return Inference("string", [None] * len(values))

    def attempt(kind: ColumnType, parse: Any) -> Inference | None:
        parsed = [parse(v) if v is not None else None for v in values]
        bad = [str(v) for v, p in zip(values, parsed, strict=True) if v is not None and p is None]
        if len(present) - len(bad) >= threshold * len(present) and len(bad) < len(present):
            return Inference(kind, parsed, len(bad), bad[:5])
        return None

    numeric_like = [v for v in present if not isinstance(v, str)]
    if (
        numeric_like
        and all(isinstance(v, bool) for v in numeric_like)
        and len(numeric_like) == len(present)
    ):
        return Inference("boolean", values)
    texts = {str(v).strip().lower() for v in present}
    if texts <= (_TRUE | _FALSE) and len(texts) <= 2 and not texts <= {"0", "1"}:
        found = attempt("boolean", parse_bool)
        if found:
            return found
    strings = [v.strip() for v in present if isinstance(v, str)]
    codes = sum(1 for v in strings if _LEADING_ZERO.match(v))
    if codes:  # « 01000 » : un code, pas le nombre 1000 (le zéro initial serait perdu)
        out = Inference("string", [None if v is None else _as_text(v) for v in values])
        if codes < len(present):
            out.notes.append(
                f"{codes} valeur(s) à zéro initial (ex. « {next(v for v in strings if _LEADING_ZERO.match(v))} ») : "
                "colonne gardée en texte (codes). `convertir` en nombre si ce sont des quantités."
            )
        return out
    for kind, parse in (("number", parse_number), ("date", parse_date)):
        found = attempt(kind, parse)  # type: ignore[arg-type]
        if found:
            ambiguous = sum(1 for v in strings if _AMBIGUOUS.match(v))
            if kind == "number" and ambiguous and ambiguous >= 0.5 * len(strings):
                found.notes.append(
                    f"{ambiguous} valeur(s) du type « 1,234 » lues avec une virgule ou un point "
                    "DÉCIMAL (1,234) : si ce sont des milliers, la colonne est fausse d'un facteur 1000."
                )
            return found
    return Inference("string", [None if v is None else _as_text(v) for v in values])


def _as_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value).strip() if isinstance(value, str) else str(value)


def coerce(value: Any, kind: ColumnType) -> Any:
    """Valeur déjà typée par une application (Viz, Tab) ramenée au type du jeu."""
    if is_missing(value):
        return None
    if kind == "number":
        return parse_number(value)
    if kind == "date":
        return parse_date(value)
    if kind == "boolean":
        return parse_bool(value) if not isinstance(value, bool) else value
    return _as_text(value)


@dataclass
class Column:
    name: str
    type: ColumnType
    values: list[Any]


@dataclass
class Frame:
    """Jeu de travail : colonnes de même longueur, nom unique dans la conversation."""

    name: str
    label: str
    origin: str
    columns: list[Column]
    #: Avertissements de chargement (troncature, valeurs illisibles…)
    notes: list[str] = field(default_factory=list)
    #: Étapes de nettoyage appliquées depuis la source (recette rejouable)
    recipe: list[dict[str, Any]] = field(default_factory=list)
    #: Nombre total de lignes de la source (avant troncature)
    source_rows: int | None = None

    @property
    def rows(self) -> int:
        return len(self.columns[0].values) if self.columns else 0

    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        """Colonne par nom exact, puis sans casse ni accents."""
        for c in self.columns:
            if c.name == name:
                return c
        wanted = _norm(name)
        matches = [c for c in self.columns if _norm(c.name) == wanted]
        if len(matches) == 1:
            return matches[0]
        hint = suggest(name, self.names())
        raise ColumnError(f"Colonne « {name} » introuvable dans « {self.name} ».{hint}")

    def numeric(self, name: str) -> list[float]:
        col = self.column(name)
        if col.type == "number":
            return [v for v in col.values if v is not None]
        if col.type == "date":
            return [date_ordinal(v) for v in col.values if v is not None]
        raise ColumnError(
            f"« {col.name} » est de type {TYPE_LABELS[col.type]} : une analyse numérique demande "
            "une colonne de nombres (ou de dates). Convertis-la avec `analyse_nettoyer` si elle "
            "contient des nombres écrits en texte."
        )

    def copy(self, name: str, label: str | None = None) -> Frame:
        return Frame(
            name=name,
            label=label or self.label,
            origin=self.origin,
            columns=[Column(c.name, c.type, list(c.values)) for c in self.columns],
            notes=list(self.notes),
            recipe=list(self.recipe),
            source_rows=self.source_rows,
        )

    def row(self, i: int) -> dict[str, Any]:
        return {c.name: c.values[i] for c in self.columns}

    def take(self, indices: Iterable[int]) -> None:
        """Garde les lignes d'indices donnés (ordre conservé)."""
        idx = list(indices)
        for c in self.columns:
            c.values = [c.values[i] for i in idx]


TYPE_LABELS: dict[str, str] = {
    "number": "nombre",
    "string": "texte",
    "date": "date",
    "boolean": "oui/non",
}


class ColumnError(ValueError):
    """Colonne absente ou de mauvais type : message clair au modèle."""


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def suggest(name: str, candidates: Sequence[str]) -> str:
    import difflib

    close = difflib.get_close_matches(_norm(name), [_norm(c) for c in candidates], n=1, cutoff=0.6)
    if close:
        original = next(c for c in candidates if _norm(c) == close[0])
        return f" Vouliez-vous dire « {original} » ?"
    shown = ", ".join(f"« {c} »" for c in candidates[:25])
    return f" Colonnes : {shown}."


def unique_names(names: Sequence[str]) -> list[str]:
    """Noms de colonnes non vides et uniques (« Colonne 3 », « Montant (2) »…)."""
    out: list[str] = []
    for i, raw in enumerate(names):
        base = (" ".join(str(raw).split())[:80] if raw is not None else "") or f"Colonne {i + 1}"
        candidate, n = base, 2
        while candidate in out:
            candidate, n = f"{base} ({n})", n + 1
        out.append(candidate)
    return out


def row_key_value(value: Any) -> Any:
    """Valeur comparée pour les doublons : texte sans casse ni espaces en trop."""
    return " ".join(value.split()).lower() if isinstance(value, str) else value


_TOTAL_LABEL = re.compile(r"^\s*(sous[- ]?)?total(\s+g[ée]n[ée]ral)?\s*:?\s*$", re.IGNORECASE)


def is_total_row(row: Sequence[Any]) -> bool:
    """Ligne de total d'un export : première cellule renseignée = « Total », « Sous-total »,
    « Total général » (exactement : « Total Energies » n'en est pas une). Règle unique du
    chargement, du profil et de l'opération `supprimer_totaux`."""
    first = next((v for v in row if not is_missing(v)), None)
    return isinstance(first, str) and bool(_TOTAL_LABEL.match(first))


def frame_from_rows(
    name: str,
    label: str,
    origin: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    types: Sequence[ColumnType | None] | None = None,
) -> Frame:
    """Jeu à partir de lignes : types fournis (application) ou inférés (fichier)."""
    names = unique_names(headers)
    width = len(names)
    columns: list[Column] = []
    notes: list[str] = []
    if types is None:  # fichier : une ligne « Total » fausserait tous les calculs
        kept = [r for r in rows if not is_total_row(r)]
        if len(kept) < len(rows):
            notes.append(
                f"{len(rows) - len(kept)} ligne(s) de total ou sous-total exclue(s) (elles fausseraient les calculs)."
            )
            rows = kept
    for j, col_name in enumerate(names):
        raw = [r[j] if j < len(r) else None for r in rows]
        kind = types[j] if types is not None and j < len(types) else None
        if kind is not None:
            values = [coerce(v, kind) for v in raw]
            columns.append(Column(col_name, kind, values))
            continue
        inferred = infer_column(raw)
        columns.append(Column(col_name, inferred.type, inferred.values))
        notes += [f"« {col_name} » : {n}" for n in inferred.notes]
        if inferred.invalid:
            examples = ", ".join(f"« {e} »" for e in inferred.invalid_examples)
            notes.append(
                f"« {col_name} » lue comme {TYPE_LABELS[inferred.type]} : {inferred.invalid} "
                f"valeur(s) illisible(s) mise(s) à vide ({examples})."
            )
    frame = Frame(name=name, label=label, origin=origin, columns=columns, notes=notes)
    if width == 0:
        frame.notes.append("Aucune colonne lue.")
    return frame
