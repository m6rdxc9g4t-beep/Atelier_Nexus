"""Nettoyage d'un jeu de travail : opérations déterministes, appliquées à une COPIE.

Chaque opération renvoie une phrase d'effet (« 12 doublons supprimés ») ; la liste des
opérations forme une recette rejouable (gardée dans `Frame.recipe`).
"""

from __future__ import annotations

import math
import operator
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.analysis import stats
from app.analysis.frame import (
    Column,
    ColumnError,
    ColumnType,
    Frame,
    is_missing,
    is_total_row,
    parse_bool,
    parse_date,
    parse_number,
    row_key_value,
    unique_names,
)

OpName = Literal[
    "supprimer_doublons",
    "supprimer_lignes_vides",
    "supprimer_totaux",
    "nettoyer_texte",
    "casse",
    "convertir",
    "remplir",
    "supprimer_manquants",
    "plafonner",
    "supprimer_aberrants",
    "log",
    "filtrer",
    "supprimer_colonne",
    "renommer",
]
Comparator = Literal[
    "=", "!=", ">", ">=", "<", "<=", "contient", "ne_contient_pas", "vide", "non_vide"
]


@dataclass(frozen=True)
class Operation:
    op: OpName
    colonne: str | None = None
    valeur: str | None = None
    comparateur: Comparator | None = None
    nouvelle_colonne: str | None = None


class CleaningError(ValueError):
    """Opération impossible (colonne absente, type incompatible…) : message au modèle."""


def apply(frame: Frame, operations: list[Operation]) -> list[str]:
    """Applique les opérations dans l'ordre ; s'arrête à la première impossible."""
    effects: list[str] = []
    for i, op in enumerate(operations, start=1):
        try:
            effects.append(_APPLY[op.op](frame, op))
        except (ColumnError, CleaningError) as exc:
            raise CleaningError(
                f"Opération {i} ({op.op}) : {exc} Aucune opération n'a été appliquée (le jeu "
                "nettoyé n'est pas créé) : corrige celle-ci et renvoie la liste complète."
            ) from exc
        frame.recipe.append({k: v for k, v in op.__dict__.items() if v is not None})
    return effects


def _need_column(frame: Frame, op: Operation) -> Column:
    if not op.colonne:
        raise CleaningError(f"« {op.op} » demande le champ `colonne`.")
    return frame.column(op.colonne)


def _columns(frame: Frame, op: Operation, kinds: tuple[ColumnType, ...]) -> list[Column]:
    if op.colonne:
        return [frame.column(op.colonne)]
    return [c for c in frame.columns if c.type in kinds]


def _key(value: Any) -> Any:
    return row_key_value(value)


def _duplicates(frame: Frame, op: Operation) -> str:
    cols = [frame.column(op.colonne)] if op.colonne else frame.columns
    seen: set[tuple[Any, ...]] = set()
    keep: list[int] = []
    for i in range(frame.rows):
        key = tuple(_key(c.values[i]) for c in cols)
        if op.colonne and key == (None,):  # clé vide : jamais considérée comme un doublon
            keep.append(i)
            continue
        if key not in seen:
            seen.add(key)
            keep.append(i)
    removed = frame.rows - len(keep)
    frame.take(keep)
    scope = f"sur « {cols[0].name} »" if op.colonne else "lignes entièrement identiques"
    return f"{removed} doublon(s) supprimé(s) ({scope}, première occurrence gardée)."


def _empty_rows(frame: Frame, _: Operation) -> str:
    keep = [i for i in range(frame.rows) if any(c.values[i] is not None for c in frame.columns)]
    removed = frame.rows - len(keep)
    frame.take(keep)
    return f"{removed} ligne(s) vide(s) supprimée(s)."


def _totals(frame: Frame, _: Operation) -> str:
    # Même règle qu'au chargement et dans le profil (`is_total_row`) : « Total Energies » reste
    keep = [i for i in range(frame.rows) if not is_total_row([c.values[i] for c in frame.columns])]
    removed = frame.rows - len(keep)
    frame.take(keep)
    return f"{removed} ligne(s) de total ou sous-total supprimée(s)."


def _trim(frame: Frame, op: Operation) -> str:
    changed = 0
    for c in _columns(frame, op, ("string",)):
        if c.type != "string":
            continue
        out = []
        for v in c.values:
            new = re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v
            new = None if isinstance(new, str) and is_missing(new) else new
            changed += new != v
            out.append(new)
        c.values = out
    return f"{changed} valeur(s) texte nettoyée(s) (espaces en trop, cellules « N/A » vidées)."


def _case(frame: Frame, op: Operation) -> str:
    mode = (op.valeur or "titre").lower()
    funcs = {"majuscules": str.upper, "minuscules": str.lower, "titre": _title}
    if mode not in funcs:
        raise CleaningError("`valeur` de « casse » : majuscules, minuscules ou titre.")
    changed = 0
    for c in _columns(frame, op, ("string",)):
        if c.type != "string":
            raise CleaningError(f"« {c.name} » n'est pas une colonne de texte.")
        out = []
        for v in c.values:
            new = funcs[mode](v.strip()) if isinstance(v, str) else v
            changed += new != v
            out.append(new)
        c.values = out
    return f"{changed} valeur(s) mise(s) en casse « {mode} » (variantes « nord » / « Nord » fusionnées)."


def _title(text: str) -> str:
    """Première lettre en capitale ; sigles (« SNCF », « TVA ») gardés en capitales."""
    out = []
    for k, word in enumerate(text.split(" ")):
        if word.isupper() and 2 <= len(word) <= 5:
            out.append(word)
        elif k == 0:
            out.append(word[:1].upper() + word[1:].lower())
        else:
            out.append(word.lower())
    return " ".join(out)


_CONVERT = {
    "nombre": ("number", parse_number),
    "date": ("date", parse_date),
    "booleen": ("boolean", parse_bool),
    "texte": ("string", None),
}


def _convert(frame: Frame, op: Operation) -> str:
    col = _need_column(frame, op)
    target = (op.valeur or "").lower().replace("é", "e")
    if target not in _CONVERT:
        raise CleaningError("`valeur` de « convertir » : nombre, date, booleen ou texte.")
    kind, parse = _CONVERT[target]
    if parse is None:
        col.values = [None if v is None else _text(v) for v in col.values]
        col.type = "string"
        return f"« {col.name} » convertie en texte."
    out, bad = [], []
    for v in col.values:
        p = parse(v) if v is not None else None
        if v is not None and p is None:
            bad.append(str(v))
        out.append(p)
    present = sum(1 for v in col.values if v is not None)
    if present and len(bad) == present:
        raise CleaningError(
            f"aucune valeur de « {col.name} » ne se lit comme {target} (ex. « {bad[0]} ») : "
            "la colonne serait entièrement vidée."
        )
    col.values = out
    col.type = kind  # type: ignore[assignment]
    detail = (
        f" ; {len(bad)} valeur(s) illisible(s) mise(s) à vide (ex. « {bad[0]} »)" if bad else ""
    )
    return f"« {col.name} » convertie en {target}{detail}."


def _text(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _fill(frame: Frame, op: Operation) -> str:
    col = _need_column(frame, op)
    strategy = (op.valeur or "").strip()
    present = [v for v in col.values if v is not None]
    missing = len(col.values) - len(present)
    if not missing:
        return f"« {col.name} » : aucune valeur manquante."
    if not present and strategy in ("mediane", "médiane", "moyenne", "mode"):
        raise CleaningError(f"« {col.name} » est entièrement vide.")
    low = strategy.lower()
    if low in ("mediane", "médiane", "moyenne"):
        if col.type != "number":
            raise CleaningError(
                f"La {low} demande une colonne de nombres ; « {col.name} » ne l'est pas."
            )
        fill: Any = (
            stats.quantile(sorted(present), 0.5)
            if low in ("mediane", "médiane")
            else stats.mean(present)
        )
    elif low == "mode":
        fill = Counter(present).most_common(1)[0][0]
    elif low == "zero" or low == "zéro":
        if col.type != "number":
            raise CleaningError(
                f"« zero » demande une colonne de nombres ; « {col.name} » ne l'est pas."
            )
        fill = 0.0
    elif low == "precedente" or low == "précédente":
        last: Any = None
        out = []
        for v in col.values:
            last = v if v is not None else last
            out.append(last)
        filled = sum(1 for a, b in zip(col.values, out, strict=True) if a is None and b is not None)
        col.values = out
        rest = missing - filled
        tail = f" ; {rest} restée(s) vide(s) en tête de colonne" if rest else ""
        return (
            f"« {col.name} » : {filled} valeur(s) manquante(s) remplie(s) par la précédente{tail}."
        )
    else:
        if not strategy:
            raise CleaningError(
                "`valeur` de « remplir » : mediane, moyenne, mode, zero, precedente ou une valeur fixe."
            )
        fill = _typed(col, strategy)
    col.values = [fill if v is None else v for v in col.values]
    shown = f"{fill:.4g}" if isinstance(fill, float) else f"« {fill} »"
    return f"« {col.name} » : {missing} valeur(s) manquante(s) remplie(s) ({strategy} = {shown})."


def _typed(col: Column, text: str) -> Any:
    parsers = {"number": parse_number, "date": parse_date, "boolean": parse_bool}
    if col.type in parsers:
        value = parsers[col.type](text)
        if value is None:
            raise CleaningError(f"« {text} » n'est pas une valeur valide pour « {col.name} ».")
        return value
    return text


def _drop_missing(frame: Frame, op: Operation) -> str:
    cols = [frame.column(op.colonne)] if op.colonne else frame.columns
    keep = [i for i in range(frame.rows) if all(c.values[i] is not None for c in cols)]
    removed = frame.rows - len(keep)
    frame.take(keep)
    scope = f"vide dans « {cols[0].name} »" if op.colonne else "avec au moins une cellule vide"
    return f"{removed} ligne(s) {scope} supprimée(s)."


def _bounds(col: Column, method: str) -> tuple[float, float]:
    values = [v for v in col.values if v is not None]
    if len(values) < 4:
        raise CleaningError(f"Trop peu de valeurs dans « {col.name} » pour repérer des aberrants.")
    method = method.lower()
    if method in ("", "iqr"):
        f = stats.iqr_fences(values)
        if f.low == f.high:
            raise CleaningError(
                f"écart interquartile nul dans « {col.name} » (plus de la moitié des valeurs sont "
                "identiques) : la règle de Tukey ramènerait tout à une seule valeur. Utilise "
                "p1-p99 ou p5-p95, ou garde ces valeurs."
            )
        return f.low, f.high
    if method == "p1-p99":
        s = sorted(values)
        return stats.quantile(s, 0.01), stats.quantile(s, 0.99)
    if method == "p5-p95":
        s = sorted(values)
        return stats.quantile(s, 0.05), stats.quantile(s, 0.95)
    raise CleaningError(
        "`valeur` : iqr (défaut), p1-p99 ou p5-p95 ; « mad » pour supprimer_aberrants."
    )


def _number_column(frame: Frame, op: Operation) -> Column:
    col = _need_column(frame, op)
    if col.type != "number":
        raise CleaningError(f"« {col.name} » n'est pas une colonne de nombres.")
    return col


def _cap(frame: Frame, op: Operation) -> str:
    col = _number_column(frame, op)
    lo, hi = _bounds(col, op.valeur or "iqr")
    changed = 0
    out = []
    for v in col.values:
        new = v if v is None else min(hi, max(lo, v))
        changed += new != v
        out.append(new)
    col.values = out
    return f"« {col.name} » : {changed} valeur(s) ramenée(s) dans [{lo:.4g} ; {hi:.4g}] (plafonnement)."


def _drop_outliers(frame: Frame, op: Operation) -> str:
    col = _number_column(frame, op)
    method = (op.valeur or "iqr").lower()
    if method == "mad":
        present = [(i, v) for i, v in enumerate(col.values) if v is not None]
        if len(present) < 4:
            raise CleaningError(
                f"Trop peu de valeurs dans « {col.name} » pour repérer des aberrants."
            )
        ordered = sorted(v for _, v in present)
        med = stats.quantile(ordered, 0.5)
        if stats.quantile(sorted(abs(v - med) for v in ordered), 0.5) == 0:
            raise CleaningError(
                f"écart absolu médian nul dans « {col.name} » (plus de la moitié des valeurs sont "
                "identiques) : toute autre valeur serait déclarée aberrante. Utilise iqr ou p1-p99."
            )
        scores = stats.mad_scores([v for _, v in present])
        bad = {i for (i, _), z in zip(present, scores, strict=True) if abs(z) > 3.5}
        label = "score z robuste > 3,5"
    else:
        lo, hi = _bounds(col, method)
        bad = {i for i, v in enumerate(col.values) if v is not None and not lo <= v <= hi}
        label = f"hors de [{lo:.4g} ; {hi:.4g}]"
    frame.take(i for i in range(frame.rows) if i not in bad)
    return f"« {col.name} » : {len(bad)} ligne(s) aberrante(s) supprimée(s) ({label})."


def _log(frame: Frame, op: Operation) -> str:
    col = _number_column(frame, op)
    values = [v for v in col.values if v is not None]
    if any(v < 0 for v in values):
        raise CleaningError(f"« {col.name} » contient des valeurs négatives : pas de logarithme.")
    use_log1p = any(v == 0 for v in values)
    func = math.log1p if use_log1p else math.log
    target = op.nouvelle_colonne or f"log_{col.name}"
    if target in frame.names():
        raise CleaningError(f"La colonne « {target} » existe déjà : choisis `nouvelle_colonne`.")
    frame.columns.append(
        Column(target, "number", [None if v is None else func(v) for v in col.values])
    )
    return f"Colonne « {target} » = {'log(1 + x)' if use_log1p else 'log(x)'} de « {col.name} »."


def _filter(frame: Frame, op: Operation) -> str:
    col = _need_column(frame, op)
    comp = op.comparateur or "="
    test = _predicate(col, comp, op.valeur)
    keep = [i for i, v in enumerate(col.values) if test(v)]
    removed = frame.rows - len(keep)
    frame.take(keep)
    shown = f" {op.valeur}" if op.valeur is not None and comp not in ("vide", "non_vide") else ""
    return f"Filtre « {col.name} {comp}{shown} » : {len(keep)} ligne(s) gardée(s), {removed} retirée(s)."


def _predicate(col: Column, comp: str, raw: str | None) -> Any:
    if comp == "vide":
        return lambda v: v is None
    if comp == "non_vide":
        return lambda v: v is not None
    if raw is None:
        raise CleaningError(f"Le filtre « {comp} » demande une `valeur`.")
    if comp in ("contient", "ne_contient_pas"):
        needle = raw.lower()
        if comp == "contient":
            return lambda v: v is not None and needle in str(v).lower()
        return lambda v: v is None or needle not in str(v).lower()
    target = _typed(col, raw) if col.type != "string" else raw
    if col.type == "string":
        norm = target.strip().lower()
        if comp == "=":
            return lambda v: isinstance(v, str) and v.strip().lower() == norm
        if comp == "!=":
            return lambda v: not (isinstance(v, str) and v.strip().lower() == norm)
    ops: dict[str, Callable[[Any, Any], bool]] = {
        "=": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }
    cmp = ops[comp]
    if comp == "!=":
        return lambda v: v is None or cmp(v, target)
    return lambda v: v is not None and cmp(v, target)


def _drop_column(frame: Frame, op: Operation) -> str:
    col = _need_column(frame, op)
    frame.columns = [c for c in frame.columns if c is not col]
    if not frame.columns:
        raise CleaningError("Impossible de supprimer la dernière colonne.")
    return f"Colonne « {col.name} » supprimée."


def _rename(frame: Frame, op: Operation) -> str:
    col = _need_column(frame, op)
    new = (op.valeur or op.nouvelle_colonne or "").strip()
    if not new:
        raise CleaningError("« renommer » demande le nouveau nom dans `valeur`.")
    if new in frame.names() and new != col.name:
        raise CleaningError(f"La colonne « {new} » existe déjà.")
    old, col.name = col.name, unique_names([new])[0]
    return f"« {old} » renommée « {col.name} »."


_APPLY = {
    "supprimer_doublons": _duplicates,
    "supprimer_lignes_vides": _empty_rows,
    "supprimer_totaux": _totals,
    "nettoyer_texte": _trim,
    "casse": _case,
    "convertir": _convert,
    "remplir": _fill,
    "supprimer_manquants": _drop_missing,
    "plafonner": _cap,
    "supprimer_aberrants": _drop_outliers,
    "log": _log,
    "filtrer": _filter,
    "supprimer_colonne": _drop_column,
    "renommer": _rename,
}
