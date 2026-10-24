"""Analyses d'un jeu de travail : texte concis pour le modèle + artefacts pour l'utilisateur.

Fonctions pures (aucun accès réseau ni état) appelées par les outils `analyse_*`. Le texte rendu
au modèle est borné (≈ 50 lignes de tableau) ; le détail complet part dans les artefacts.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.analysis import charts, stats
from app.analysis.frame import (
    TYPE_LABELS,
    Column,
    ColumnError,
    Frame,
    date_ordinal,
    is_total_row,
    parse_date,
    parse_number,
    row_key_value,
)
from app.tools.base import Artifact
from app.tools.formatting import data_artifact, markdown_table

Period = Literal["annee", "trimestre", "mois", "semaine", "jour"]
AggName = Literal[
    "nombre", "somme", "moyenne", "mediane", "ecart_type", "min", "max", "distinct", "p25", "p75"
]
MAX_GROUPS = 40
MAX_MATRIX = 30


@dataclass
class Result:
    content: str
    artifacts: list[Artifact] = field(default_factory=list)


# ─── Mise en forme ────────────────────────────────────────────────


def num(x: float | None) -> str:
    """Nombre lisible : 1 234 567 · 12.35 · 0.0042 (jamais de notation scientifique courante)."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "∅"
    a = abs(x)
    if a >= 1000:
        text = f"{x:,.0f}" if a >= 100_000 else f"{x:,.2f}".rstrip("0").rstrip(".")
        return text.replace(",", " ")
    if a >= 1 or a == 0:
        return f"{x:.2f}".rstrip("0").rstrip(".")
    if a >= 1e-4:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.2e}"


def pval(p: float) -> str:
    if p != p:
        return "∅"
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "∅"


def _verdict(p: float, alpha: float = 0.05) -> str:
    return "significatif" if p == p and p < alpha else "non significatif"


def _source_line(frame: Frame) -> str:
    return f"Jeu « {frame.name} » ({frame.rows} lignes, {len(frame.columns)} colonnes) — {frame.origin}"


# ─── Profil ───────────────────────────────────────────────────────


def _norm_text(v: str) -> str:
    return " ".join(v.split()).lower()


def duplicate_rows(frame: Frame) -> int:
    seen: set[tuple[Any, ...]] = set()
    dup = 0
    for i in range(frame.rows):
        key = tuple(row_key_value(c.values[i]) for c in frame.columns)
        if key in seen:
            dup += 1
        else:
            seen.add(key)
    return dup


def profile(frame: Frame) -> Result:
    n = frame.rows
    lines = [_source_line(frame)]
    if frame.recipe:
        lines.append(f"Nettoyages appliqués : {len(frame.recipe)} opération(s).")
    rows_for_model: list[list[Any]] = []
    table: list[list[Any]] = []
    issues: list[str] = []
    dup = duplicate_rows(frame)
    if dup:
        issues.append(
            f"{dup} ligne(s) en double ({pct(dup, n)}) → `supprimer_doublons` si ce ne sont pas des "
            "opérations légitimement identiques."
        )
    totals = sum(1 for i in range(n) if is_total_row([c.values[i] for c in frame.columns]))
    if totals:
        issues.append(
            f"{totals} ligne(s) de total ou sous-total → `supprimer_totaux` avant de calculer."
        )
    for col in frame.columns:
        present = [v for v in col.values if v is not None]
        missing = n - len(present)
        distinct = len(set(present))
        summary, stat_row = _column_summary(col, present)
        rows_for_model.append(
            [col.name, TYPE_LABELS[col.type], len(present), pct(missing, n), distinct, summary]
        )
        table.append([col.name, TYPE_LABELS[col.type], len(present), missing, distinct, *stat_row])
        issues += _column_issues(col, present, missing, distinct, n)
    lines.append(
        markdown_table(
            ["Colonne", "Type", "Remplies", "Vides", "Distinctes", "Résumé"], rows_for_model[:60]
        )
    )
    if len(rows_for_model) > 60:
        lines.append(f"[{len(rows_for_model) - 60} colonne(s) de plus dans l'artefact]")
    if frame.notes:
        lines.append("\nChargement :\n" + "\n".join(f"- {x}" for x in frame.notes))
    lines.append(
        "\nPoints d'attention :\n" + "\n".join(f"- {x}" for x in issues)
        if issues
        else "\nAucun problème de qualité repéré."
    )
    headers = [
        "Colonne", "Type", "Remplies", "Vides", "Distinctes", "Moyenne", "Écart-type", "Min", "Q1",
        "Médiane", "Q3", "Max", "Asymétrie", "Aplatissement", "Plus fréquente",
    ]  # fmt: skip
    numeric = {h for h in headers if h not in ("Colonne", "Type", "Plus fréquente")}
    artifacts = [data_artifact(f"Profil — {frame.label}", headers, table, numeric=numeric)]
    sample = [
        [frame.columns[j].values[i] for j in range(len(frame.columns))] for i in range(min(n, 20))
    ]
    if sample:
        artifacts.append(
            data_artifact(
                f"Aperçu — {frame.label}",
                frame.names(),
                sample,
                numeric={c.name for c in frame.columns if c.type == "number"},
            )
        )
    return Result("\n".join(lines), artifacts)


def _column_summary(col: Column, present: list[Any]) -> tuple[str, list[Any]]:
    empty_stats: list[Any] = [None] * 9
    if not present:
        return "vide", [*empty_stats, None]
    top_value, top_count = Counter(present).most_common(1)[0]
    if col.type == "number":
        d = stats.describe(present)
        assert d is not None
        text = (
            f"moy {num(d.mean)} · méd {num(d.median)} · σ {num(d.std)} · [{num(d.min)} ; {num(d.max)}]"
            f" · asym {num(d.skew)}"
        )
        return text, [
            d.mean, d.std, d.min, d.q1, d.median, d.q3, d.max,
            None if d.skew != d.skew else round(d.skew, 3),
            None if d.kurt != d.kurt else round(d.kurt, 3),
            top_value,
        ]  # fmt: skip
    if col.type == "date":
        s = sorted(present)
        return f"du {s[0]} au {s[-1]}", [
            None,
            None,
            s[0],
            None,
            None,
            None,
            s[-1],
            None,
            None,
            top_value,
        ]
    if col.type == "boolean":
        yes = sum(1 for v in present if v)
        return f"oui {pct(yes, len(present))}", [*empty_stats, top_value]
    top = Counter(present).most_common(3)
    text = ", ".join(f"« {_short(v)} » ({pct(c, len(present))})" for v, c in top)
    return text, [*empty_stats, top_value if top_count > 1 else None]


def _short(value: Any, size: int = 30) -> str:
    text = str(value)
    return text if len(text) <= size else text[: size - 1] + "…"


def _column_issues(
    col: Column, present: list[Any], missing: int, distinct: int, n: int
) -> list[str]:
    out: list[str] = []
    name = f"« {col.name} »"
    if not present:
        return [f"{name} est entièrement vide → `supprimer_colonne`."]
    if missing and missing / n >= 0.2:
        out.append(f"{name} : {pct(missing, n)} de valeurs manquantes.")
    if distinct == 1 and n > 1:
        out.append(f"{name} est constante (une seule valeur) : inutile pour l'analyse.")
    if col.type == "string":
        as_number = sum(1 for v in present if parse_number(v) is not None)
        as_date = sum(1 for v in present if parse_date(v) is not None)
        if as_number >= 0.8 * len(present):
            out.append(
                f"{name} contient surtout des nombres écrits en texte → `convertir` en nombre "
                "(sauf s'il s'agit de codes : postal, client…)."
            )
        elif as_date >= 0.8 * len(present):
            out.append(f"{name} contient surtout des dates écrites en texte → `convertir` en date.")
        variants = len({_norm_text(v) for v in present if isinstance(v, str)})
        if variants < distinct:
            out.append(
                f"{name} : {distinct - variants} variante(s) d'écriture d'une même valeur (casse, "
                "espaces) → `nettoyer_texte` puis `casse`."
            )
        if distinct == len(present) and len(present) > 20:
            out.append(
                f"{name} : valeurs toutes différentes (identifiant ?) — ne pas l'utiliser comme catégorie."
            )
        elif distinct > 50 and distinct > 0.5 * len(present):
            out.append(
                f"{name} : {distinct} catégories distinctes, trop pour des comparaisons lisibles."
            )
    if col.type == "number" and len(present) >= 4:
        d = stats.describe(present)
        assert d is not None
        if d.skew == d.skew and abs(d.skew) >= 1:
            out.append(f"{name} : {stats.skew_label(d.skew)} (G1 = {num(d.skew)}).")
        fences = stats.iqr_fences(present)
        outliers = sum(1 for v in present if not fences.low <= v <= fences.high)
        if outliers:
            out.append(
                f"{name} : {outliers} valeur(s) hors des moustaches de Tukey "
                f"([{num(fences.low)} ; {num(fences.high)}])."
            )
    return out


# ─── Distribution ─────────────────────────────────────────────────


def distribution(frame: Frame, column: str, by: str | None = None) -> Result:
    col = frame.column(column)
    if by:
        return _distribution_by(frame, col, frame.column(by))
    if col.type in ("string", "boolean"):
        return _frequencies(frame, col)
    values = frame.numeric(col.name)
    if len(values) < 3:
        raise ColumnError(f"« {col.name} » a moins de 3 valeurs : distribution non calculable.")
    d = stats.describe(values, missing=frame.rows - len(values))
    assert d is not None
    is_date = col.type == "date"
    fmt_v: Callable[[float], str] = _date_str if is_date else num
    s = sorted(values)
    lines = [
        _source_line(frame),
        f"Distribution de « {col.name} » ({d.n} valeurs, {d.missing} vides) :",
    ]
    lines.append(
        f"- Centre : moyenne {fmt_v(d.mean)}, médiane {fmt_v(d.median)}"
        + (
            ""
            if is_date
            else f" ; dispersion : écart-type {num(d.std)}, écart interquartile {num(d.iqr)}"
        )
    )
    lines.append(
        "- Quantiles : "
        + ", ".join(
            f"P{int(q * 100)} {fmt_v(stats.quantile(s, q))}"
            for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
        )
        + f" ; min {fmt_v(d.min)}, max {fmt_v(d.max)}"
    )
    if not is_date:
        lines.append(f"- Forme : asymétrie G1 = {num(d.skew)} → {stats.skew_label(d.skew)}.")
        lines.append(f"- Aplatissement (excès) G2 = {num(d.kurt)} → {stats.kurt_label(d.kurt)}.")
        if d.mean and d.std == d.std:
            lines.append(f"- Coefficient de variation : {num(d.cv * 100)} %.")
        if d.skew == d.skew and abs(d.skew) >= 1:
            lines.append(
                "- Moyenne et médiane s'écartent : pour résumer cette colonne, préférer la médiane."
            )
        norm = stats.normality_test(values)
        if norm is None:
            lines.append("- Normalité : moins de 20 valeurs, test non pertinent.")
        else:
            verdict = (
                "on rejette la normalité"
                if norm.p_value < 0.05
                else "compatible avec une loi normale"
            )
            lines.append(
                f"- Normalité (D'Agostino-Pearson) : K² = {num(norm.statistic)}, p = {pval(norm.p_value)}"
                f" → {verdict}."
                + (
                    " Avec beaucoup de valeurs, le test rejette des écarts minimes : juger aussi sur la forme."
                    if d.n > 2000
                    else ""
                )
            )
        hint = stats.transformation_hint(d, values)
        if hint:
            lines.append(
                f"- Transformation suggérée : {hint[0]} (asymétrie après : {num(hint[1])})"
                + (
                    " → opération `log` de `analyse_nettoyer`."
                    if hint[0] in ("log", "log1p")
                    else "."
                )
            )
        fences = stats.iqr_fences(values)
        out = sum(1 for v in values if not fences.low <= v <= fences.high)
        lines.append(
            f"- Valeurs atypiques (Tukey, 1,5 × EIQ) : {out} ({pct(out, d.n)}), hors de "
            f"[{num(fences.low)} ; {num(fences.high)}]."
        )
        if d.zeros:
            lines.append(f"- Zéros : {d.zeros} ({pct(d.zeros, d.n)}).")
        if d.negatives:
            lines.append(f"- Valeurs négatives : {d.negatives}.")
    spec = charts.histogram(
        values,
        x_label=col.name,
        markers=None if is_date else {"Moyenne": d.mean, "Médiane": d.median},
    )
    if is_date:
        spec["x"]["kind"] = "date"
    note = None if is_date else f"Asymétrie {num(d.skew)} · aplatissement {num(d.kurt)} · n = {d.n}"
    return Result(
        "\n".join(lines),
        [charts.artifact(f"Distribution — {col.name}", spec, notes=note, source=frame.name)],
    )


def _date_str(x: float) -> str:
    return date.fromordinal(int(x)).isoformat()


def _frequencies(frame: Frame, col: Column) -> Result:
    present = [v for v in col.values if v is not None]
    counts = Counter("oui" if v is True else "non" if v is False else v for v in present)
    total = len(present)
    top = counts.most_common(30)
    rest = total - sum(c for _, c in top)
    lines = [
        _source_line(frame),
        f"Répartition de « {col.name} » : {total} valeurs, {len(counts)} modalité(s), "
        f"{frame.rows - total} vide(s).",
    ]
    rows = [[_short(v, 50), c, pct(c, total)] for v, c in top]
    lines.append(markdown_table(["Valeur", "Effectif", "Part"], rows[:25]))
    if rest:
        lines.append(f"Autres modalités : {rest} valeur(s) ({pct(rest, total)}).")
    if top:
        share = top[0][1] / total
        if share > 0.8:
            lines.append(
                f"Très concentrée : « {_short(top[0][0])} » représente {pct(top[0][1], total)}."
            )
        rare = sum(1 for c in counts.values() if c == 1)
        if rare > 5:
            lines.append(
                f"{rare} modalité(s) n'apparaissent qu'une fois (fautes de frappe ? regroupement ?)."
            )
    labels = [_short(v, 40) for v, _ in top[:25]] + (["Autres"] if len(top) > 25 or rest else [])
    values: list[float | None] = [float(c) for _, c in top[:25]]
    if len(labels) > len(values):
        values.append(float(rest + sum(c for _, c in top[25:])))
    spec = charts.categories(
        labels, [("Effectif", values)], kind="bar", x_label=col.name, y_label="Effectif"
    )
    return Result(
        "\n".join(lines), [charts.artifact(f"Répartition — {col.name}", spec, source=frame.name)]
    )


def _groups(
    frame: Frame, value_col: Column, group_col: Column
) -> tuple[list[tuple[str, list[float]]], int]:
    """Valeurs numériques par modalité (les MAX_GROUPS plus fréquentes) ; renvoie aussi le
    nombre de modalités écartées."""
    if value_col.type not in ("number", "date"):
        raise ColumnError(
            f"« {value_col.name} » est de type {TYPE_LABELS[value_col.type]} : il faut une colonne "
            "de nombres (ou de dates) pour la comparer entre groupes."
        )
    if (
        group_col.type in ("number",)
        and len({v for v in group_col.values if v is not None}) > MAX_GROUPS
    ):
        raise ColumnError(
            f"« {group_col.name} » est numérique avec beaucoup de valeurs : ce n'est pas une catégorie. "
            "Utilise `analyse_relation` (nuage de points) ou regroupe-la d'abord."
        )
    to_num = (lambda v: date_ordinal(v)) if value_col.type == "date" else (lambda v: v)
    buckets: dict[str, list[float]] = defaultdict(list)
    for g, v in zip(group_col.values, value_col.values, strict=True):
        if g is None or v is None:
            continue
        buckets[_label(g)].append(to_num(v))
    ordered = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    return ordered[:MAX_GROUPS], max(0, len(ordered) - MAX_GROUPS)


def natural_key(label: Any) -> tuple[int, float, str]:
    """Tri naturel des libellés : nombres dans l'ordre numérique (1, 2, 10), puis le texte."""
    text = str(label)
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, text.lower())


def _label(value: Any) -> str:
    if value is True:
        return "oui"
    if value is False:
        return "non"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _distribution_by(frame: Frame, col: Column, by: Column) -> Result:
    if col.type not in ("number", "date"):
        raise ColumnError(f"« {col.name} » doit être numérique pour une distribution par groupe.")
    groups, dropped = _groups(frame, col, by)
    if len(groups) < 2:
        raise ColumnError(f"« {by.name} » n'a pas au moins deux groupes renseignés.")
    lines = [_source_line(frame), f"« {col.name} » selon « {by.name} » ({len(groups)} groupes) :"]
    rows = []
    for label, values in groups:
        d = stats.describe(values)
        assert d is not None
        rows.append(
            [
                _short(label, 40),
                d.n,
                num(d.mean),
                num(d.median),
                num(d.std),
                num(d.q1),
                num(d.q3),
                num(d.skew),
            ]
        )
    lines.append(
        markdown_table(
            ["Groupe", "n", "Moyenne", "Médiane", "Écart-type", "Q1", "Q3", "Asym."], rows[:30]
        )
    )
    if dropped:
        lines.append(f"{dropped} groupe(s) moins fréquent(s) non affiché(s).")
    lines += _group_tests([v for _, v in groups], col.name, by.name, dropped)
    spec = charts.box(groups, y_label=col.name, x_label=by.name)
    return Result(
        "\n".join(lines), [charts.artifact(f"{col.name} par {by.name}", spec, source=frame.name)]
    )


def _group_tests(groups: list[list[float]], value: str, by: str, dropped: int = 0) -> list[str]:
    usable = [g for g in groups if len(g) >= 2]
    if len(usable) < 2:
        return ["Tests de comparaison : groupes trop petits."]
    out = ["\nComparaison des groupes :"]
    excluded = dropped + len(groups) - len(usable)
    if excluded:
        out.append(
            f"Tests sur {len(usable)} groupe(s) (les {MAX_GROUPS} plus fréquents, au moins 2 valeurs) ; "
            f"{excluded} groupe(s) écarté(s) des tests."
        )
    if len(usable) == 2:
        tests = [stats.welch_t(*usable), stats.mann_whitney(*usable)]
    else:
        tests = [stats.anova(usable), stats.kruskal(usable)]
    for t in tests:
        if t is None:
            continue
        out.append(
            f"- {t.test} : statistique {num(t.statistic)}{f' ({t.detail})' if t.detail else ''}, "
            f"p = {pval(t.p_value)} ({_verdict(t.p_value)}) ; {t.effect_name} = {num(t.effect)} "
            f"({_effect_label(t.effect_name, t.effect)})."
        )
    out.append(
        f"Lecture : un test significatif dit que « {value} » diffère selon « {by} », pas pourquoi. "
        "Le test non paramétrique (rangs) est plus fiable si les distributions sont asymétriques."
    )
    return out


def _effect_label(name: str, value: float) -> str:
    if value != value:
        return "non calculable"
    a = abs(value)
    if name == "d de Cohen":
        cuts = (0.2, 0.5, 0.8)
    elif name in ("η²", "ε²"):
        cuts = (0.01, 0.06, 0.14)
    else:  # corrélations, V de Cramér
        cuts = (0.1, 0.3, 0.5)
    if a < cuts[0]:
        return "effet négligeable"
    if a < cuts[1]:
        return "effet faible"
    if a < cuts[2]:
        return "effet moyen"
    return "effet fort"


# ─── Corrélations ─────────────────────────────────────────────────


Method = Literal["pearson", "spearman", "les_deux"]


def _pairs(a: list[Any], b: list[Any]) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for x, y in zip(a, b, strict=True):
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    return xs, ys


def _numeric_values(col: Column) -> list[float | None]:
    if col.type == "date":
        return [None if v is None else date_ordinal(v) for v in col.values]
    if col.type == "boolean":
        return [None if v is None else float(v) for v in col.values]
    return list(col.values)


def correlations(
    frame: Frame, columns: Sequence[str] | None, method: Method, target: str | None
) -> Result:
    if columns:
        cols = [frame.column(c) for c in columns]
        bad = [c.name for c in cols if c.type not in ("number", "date", "boolean")]
        if bad:
            raise ColumnError(
                f"Colonnes non numériques : {', '.join(bad)}. Pour une catégorie, utilise `analyse_relation`."
            )
    else:
        cols = [c for c in frame.columns if c.type == "number"]
    target_name: str | None = None
    if target:
        t = frame.column(target)
        if t.type not in ("number", "date", "boolean"):
            raise ColumnError(
                f"« {t.name} » est de type {TYPE_LABELS[t.type]} : une corrélation demande une "
                "colonne numérique. Pour une catégorie, utilise `analyse_relation`."
            )
        target_name = t.name
        if t not in cols:
            cols = [t, *cols]
    usable = [c for c in cols if len({v for v in c.values if v is not None}) > 1]
    dropped_constant = len(cols) - len(usable)
    cols = usable[:MAX_MATRIX]
    truncated = len(usable) - len(cols)
    if len(cols) < 2:
        raise ColumnError("Il faut au moins deux colonnes numériques non constantes.")
    values = {c.name: _numeric_values(c) for c in cols}
    names = [c.name for c in cols]
    k = len(names)
    pear: dict[tuple[int, int], stats.Correlation] = {}
    spear: dict[tuple[int, int], stats.Correlation] = {}
    for i in range(k):
        for j in range(i + 1, k):
            if target_name and target_name not in (names[i], names[j]):
                continue
            xs, ys = _pairs(values[names[i]], values[names[j]])
            if method in ("pearson", "les_deux"):
                pear[(i, j)] = stats.pearson(xs, ys)
            if method in ("spearman", "les_deux"):
                spear[(i, j)] = stats.spearman(xs, ys)
    main = spear if method in ("spearman", "les_deux") else pear
    keys = [key for key, c in main.items() if c.r == c.r]
    adjusted = dict(zip(keys, stats.holm([main[key].p_value for key in keys]), strict=True))
    ranked = sorted(keys, key=lambda key: -abs(main[key].r))
    label = {"pearson": "Pearson", "spearman": "Spearman", "les_deux": "Spearman"}[method]
    lines = [
        _source_line(frame),
        f"Corrélations ({'Pearson et Spearman' if method == 'les_deux' else label}) entre {k} colonnes"
        + (f", par rapport à « {target_name} »" if target_name else "")
        + f" ; {len(keys)} paire(s) testée(s), valeurs p corrigées (Holm).",
    ]
    if dropped_constant:
        lines.append(f"{dropped_constant} colonne(s) constante(s) écartée(s).")
    if truncated:
        lines.append(
            f"{truncated} colonne(s) au-delà des {MAX_MATRIX} premières non calculées : précise `colonnes`."
        )
    rows = []
    nonlinear: list[str] = []
    for key in ranked[:20]:
        i, j = key
        c = main[key]
        row: list[Any] = [names[i], names[j]]
        if method == "les_deux":
            p = pear[key]
            row.append(num(p.r))
            if p.r == p.r and abs(p.r - c.r) >= 0.2:
                nonlinear.append(
                    f"« {names[i]} » / « {names[j]} » (Pearson {num(p.r)}, Spearman {num(c.r)})"
                )
        row += [num(c.r), stats.strength_label(c.r), c.n, pval(adjusted[key])]
        rows.append(row)
    headers = ["Variable 1", "Variable 2"] + (["Pearson"] if method == "les_deux" else [])
    headers += [label if method != "les_deux" else "Spearman", "Force", "n", "p (Holm)"]
    lines.append(markdown_table(headers, rows))
    if len(ranked) > 20:
        lines.append(f"[{len(ranked) - 20} paire(s) plus faibles dans la matrice]")
    if nonlinear:
        lines.append(
            "Écart Pearson / Spearman ≥ 0,2 : relation non linéaire (monotone) ou tirée par des valeurs "
            "extrêmes — vérifier avec `analyse_relation` : " + " ; ".join(nonlinear[:5]) + "."
        )
    small = [key for key in keys if main[key].n < 30]
    if small:
        lines.append(
            f"{len(small)} paire(s) calculée(s) sur moins de 30 lignes : à interpréter avec prudence."
        )
    lines.append(
        "Rappel : une corrélation ne prouve pas une causalité (facteur commun, effet de période…)."
    )
    matrix: list[list[float | None]] = [
        [1.0 if i == j else None for j in range(k)] for i in range(k)
    ]
    for (i, j), c in main.items():
        r = c.r if c.r == c.r else None
        matrix[i][j] = matrix[j][i] = r
    spec = charts.heatmap(names, matrix, label=f"Corrélation de {label}")
    art = [charts.artifact(f"Matrice de corrélation ({label})", spec, source=frame.name)]
    detail_rows = [
        [names[i], names[j], *( [round(pear[(i, j)].r, 4)] if method == "les_deux" else []),
         round(main[(i, j)].r, 4), main[(i, j)].n, main[(i, j)].p_value, adjusted[(i, j)]]
        for (i, j) in ranked
    ]  # fmt: skip
    detail_headers = ["Variable 1", "Variable 2"] + (["Pearson"] if method == "les_deux" else [])
    detail_headers += [label, "n", "p", "p (Holm)"]
    art.append(
        data_artifact(
            f"Corrélations — {frame.label}",
            detail_headers,
            detail_rows,
            numeric=set(detail_headers) - {"Variable 1", "Variable 2"},
        )
    )
    return Result("\n".join(lines), art)


# ─── Relation entre deux variables ────────────────────────────────


def relation(frame: Frame, x: str, y: str) -> Result:
    cx, cy = frame.column(x), frame.column(y)
    if cx is cy:
        raise ColumnError("Choisis deux colonnes différentes.")
    num_x = cx.type in ("number",)
    num_y = cy.type in ("number",)
    cat = ("string", "boolean")
    if cx.type == "date" and num_y:
        return _over_time(frame, cx, cy)
    if cy.type == "date" and num_x:
        return _over_time(frame, cy, cx)
    if num_x and num_y:
        return _numeric_pair(frame, cx, cy)
    if num_y and cx.type in cat:
        return _distribution_by(frame, cy, cx)
    if num_x and cy.type in cat:
        return _distribution_by(frame, cx, cy)
    if cx.type in cat and cy.type in cat:
        return _categorical_pair(frame, cx, cy)
    raise ColumnError(
        f"Relation entre « {cx.name} » ({TYPE_LABELS[cx.type]}) et « {cy.name} » "
        f"({TYPE_LABELS[cy.type]}) non prise en charge."
    )


def _numeric_pair(frame: Frame, cx: Column, cy: Column) -> Result:
    xs, ys = _pairs(cx.values, cy.values)
    if len(xs) < 3:
        raise ColumnError("Moins de 3 lignes où les deux colonnes sont renseignées.")
    p, s = stats.pearson(xs, ys), stats.spearman(xs, ys)
    reg = stats.linear_regression(xs, ys)
    lines = [
        _source_line(frame),
        f"Relation entre « {cx.name} » (x) et « {cy.name} » (y), {len(xs)} lignes complètes :",
        f"- Pearson r = {num(p.r)} ({stats.strength_label(p.r)}), p = {pval(p.p_value)} ({_verdict(p.p_value)}).",
        f"- Spearman ρ = {num(s.r)} ({stats.strength_label(s.r)}), p = {pval(s.p_value)}.",
    ]
    if reg:
        lines.append(
            f"- Droite des moindres carrés : y = {num(reg.slope)} × x "
            f"{'−' if reg.intercept < 0 else '+'} {num(abs(reg.intercept))} ; "
            f"R² = {num(reg.r2)} ({num(reg.r2 * 100)} % de la variance de y expliquée linéairement par x)."
        )
    if p.r == p.r and s.r == s.r and abs(p.r - s.r) >= 0.2:
        lines.append(
            "- Pearson et Spearman divergent : relation monotone mais non linéaire, ou portée par "
            "quelques valeurs extrêmes (voir le nuage de points)."
        )
    lines.append("Une corrélation ne prouve pas une causalité.")
    spec = charts.scatter(xs, ys, x_label=cx.name, y_label=cy.name, trend=reg)
    return Result(
        "\n".join(lines),
        [
            charts.artifact(
                f"{cy.name} selon {cx.name}",
                spec,
                notes=f"r = {num(p.r)} · ρ = {num(s.r)}",
                source=frame.name,
            )
        ],
    )


def _categorical_pair(frame: Frame, cx: Column, cy: Column) -> Result:
    a, b = [], []
    for u, v in zip(cx.values, cy.values, strict=True):
        if u is not None and v is not None:
            a.append(_label(u))
            b.append(_label(v))
    if len(set(a)) > 30 or len(set(b)) > 30:
        raise ColumnError(
            "Trop de modalités (> 30) pour un tableau croisé lisible : regroupe-les d'abord."
        )
    t = stats.contingency(a, b)
    lines = [
        _source_line(frame),
        f"Tableau croisé « {cx.name} » × « {cy.name} » ({len(a)} lignes complètes) :",
    ]
    if t.chi2 == t.chi2:
        lines.append(
            f"- Khi² = {num(t.chi2)} ({t.dof} ddl), p = {pval(t.p_value)} ({_verdict(t.p_value)}) ; "
            f"V de Cramér = {num(t.cramers_v)} ({_effect_label('V', t.cramers_v).replace('effet', 'association')})."
        )
        if t.low_expected > 0.2:
            lines.append(
                f"- {pct(round(t.low_expected * 100), 100)} des effectifs attendus sont < 5 : le khi² est "
                "peu fiable, regrouper les petites modalités."
            )
    headers = [cx.name, *t.cols, "Total"]
    rows = []
    for i, label in enumerate(t.rows):
        total = sum(t.counts[i])
        rows.append([label, *(f"{c} ({pct(c, total)})" for c in t.counts[i]), total])
    lines.append(markdown_table(headers, rows[:30]))
    series = [
        (col, [float(t.counts[i][j]) for i in range(len(t.rows))])
        for j, col in enumerate(t.cols[:8])
    ]
    spec = charts.categories(t.rows, series, kind="bar", x_label=cx.name, y_label="Effectif")
    return Result(
        "\n".join(lines),
        [
            charts.artifact(f"{cy.name} selon {cx.name}", spec, source=frame.name),
            data_artifact(
                f"Tableau croisé — {cx.name} × {cy.name}",
                [cx.name, *t.cols],
                [[label, *t.counts[i]] for i, label in enumerate(t.rows)],
                numeric=set(t.cols),
            ),
        ],
    )


def _auto_period(dates: list[str]) -> Period:
    span = date_ordinal(max(dates)) - date_ordinal(min(dates))
    if span > 8 * 366:
        return "trimestre"
    if span > 180:
        return "mois"
    if span > 45:
        return "semaine"
    return "jour"


def _over_time(frame: Frame, cd: Column, cv: Column) -> Result:
    pairs = [
        (d, v) for d, v in zip(cd.values, cv.values, strict=True) if d is not None and v is not None
    ]
    if len(pairs) < 3:
        raise ColumnError("Moins de 3 lignes datées et renseignées.")
    period = _auto_period([d for d, _ in pairs])
    buckets: dict[str, list[float]] = defaultdict(list)
    for d, v in pairs:
        buckets[period_key(d, period)].append(v)
    labels = sorted(buckets)
    sums = [math.fsum(buckets[k]) for k in labels]
    means = [stats.mean(buckets[k]) for k in labels]
    trend = stats.spearman([date_ordinal(d) for d, _ in pairs], [v for _, v in pairs])
    lines = [
        _source_line(frame),
        f"« {cv.name} » dans le temps (« {cd.name} », par {PERIOD_LABELS[period]}, {len(labels)} périodes) :",
        f"- Tendance (Spearman entre date et valeur) : ρ = {num(trend.r)}, p = {pval(trend.p_value)} → "
        + (
            "pas de tendance monotone nette."
            if trend.p_value != trend.p_value or trend.p_value >= 0.05
            else f"tendance {'à la hausse' if trend.r > 0 else 'à la baisse'}."
        ),
    ]
    if len(labels) >= 2:
        best = max(range(len(labels)), key=lambda i: sums[i])
        worst = min(range(len(labels)), key=lambda i: sums[i])
        lines.append(
            f"- Total le plus haut : {labels[best]} ({num(sums[best])}) ; le plus bas : "
            f"{labels[worst]} ({num(sums[worst])})."
        )
    rows = [
        [k, len(buckets[k]), num(s), num(m)] for k, s, m in zip(labels, sums, means, strict=True)
    ]
    lines.append(markdown_table(["Période", "n", "Somme", "Moyenne"], rows[-30:]))
    # Une seule série : la moyenne serait écrasée par l'échelle de la somme. Courbe de la
    # moyenne : `analyse_graphique` (courbe, agregation = moyenne).
    spec = charts.categories(
        labels,
        [("Somme", sums)],
        kind="line",
        x_label=cd.name,
        y_label=f"Somme de {cv.name}",
        x_kind="date",
    )
    return Result(
        "\n".join(lines),
        [charts.artifact(f"{cv.name} par {PERIOD_LABELS[period]}", spec, source=frame.name)],
    )


# ─── Valeurs aberrantes ───────────────────────────────────────────


def outliers(frame: Frame, columns: Sequence[str] | None, method: Literal["iqr", "mad"]) -> Result:
    cols = (
        [frame.column(c) for c in columns]
        if columns
        else [c for c in frame.columns if c.type == "number"]
    )
    cols = [c for c in cols if c.type == "number"]
    if not cols:
        raise ColumnError("Aucune colonne de nombres à examiner.")
    lines = [
        _source_line(frame),
        "Valeurs aberrantes "
        + ("(moustaches de Tukey : hors de Q1 − 1,5 × EIQ et Q3 + 1,5 × EIQ ; « extrêmes » au-delà de 3 × EIQ)"
           if method == "iqr" else "(score z robuste de la médiane et du MAD, seuil 3,5)")
        + " :",
    ]  # fmt: skip
    rows: list[list[Any]] = []
    flagged: list[tuple[int, str, float, str]] = []
    warnings: list[str] = []
    for col in cols:
        idx = [i for i, v in enumerate(col.values) if v is not None]
        values = [col.values[i] for i in idx]
        if len(values) < 4:
            continue
        degenerate = (
            stats.iqr_fences(values).low == stats.iqr_fences(values).high
            if method == "iqr"
            else stats.quantile(
                sorted(abs(v - stats.quantile(sorted(values), 0.5)) for v in values), 0.5
            )
            == 0
        )
        if degenerate:
            rows.append([col.name, len(values), "—", "—", "—", "dispersion nulle", "—", "—"])
            warnings.append(
                f"« {col.name} » : plus de la moitié des valeurs sont identiques, la règle "
                f"{'de Tukey' if method == 'iqr' else 'du MAD'} n'a pas de sens (toute autre valeur "
                "serait atypique) ; regarder `analyse_distribution`."
            )
            continue
        if method == "iqr":
            f = stats.iqr_fences(values)
            bad = [(i, v) for i, v in zip(idx, values, strict=True) if not f.low <= v <= f.high]
            extreme = sum(1 for _, v in bad if not f.extreme_low <= v <= f.extreme_high)
            bounds = f"[{num(f.low)} ; {num(f.high)}]"
            for i, v in bad:
                flagged.append(
                    (
                        i,
                        col.name,
                        v,
                        "extrême" if not f.extreme_low <= v <= f.extreme_high else "modérée",
                    )
                )
        else:
            scores = stats.mad_scores(values)
            bad = [
                (i, v)
                for (i, v), z in zip(zip(idx, values, strict=True), scores, strict=True)
                if abs(z) > 3.5
            ]
            extreme = sum(1 for z in scores if abs(z) > 7)
            bounds = "|z| > 3,5"
            flagged += [(i, col.name, v, "robuste") for i, v in bad]
        med = stats.quantile(sorted(values), 0.5)
        low = sorted(v for _, v in bad if v < med)[:3]
        high = sorted((v for _, v in bad if v > med), reverse=True)[:3]
        rows.append(
            [col.name, len(values), len(bad), pct(len(bad), len(values)), extreme, bounds,
             ", ".join(num(v) for v in low) or "—", ", ".join(num(v) for v in high) or "—"]
        )  # fmt: skip
    headers = ["Colonne", "n", "Atypiques", "Part", "Extrêmes", "Bornes", "Côté bas", "Côté haut"]
    lines.append(markdown_table(headers, rows))
    lines += warnings
    lines.append(
        "Une valeur atypique n'est pas forcément une erreur (grosse commande, saisonnalité) : "
        "vérifier avant de `plafonner` ou `supprimer_aberrants`. Sur une distribution très asymétrique, "
        "la règle de Tukey signale beaucoup de valeurs : regarder d'abord `analyse_distribution`."
    )
    artifacts: list[Artifact] = []
    if flagged:
        flagged.sort(key=lambda t: (t[1], -abs(t[2])))
        headers = ["Ligne", "Colonne signalée", "Valeur", "Niveau", *frame.names()]
        detail = [
            [i + 1, name, v, level, *[c.values[i] for c in frame.columns]]
            for i, name, v, level in flagged[:500]
        ]
        artifacts.append(
            data_artifact(
                f"Valeurs atypiques — {frame.label}",
                headers,
                detail,
                numeric={"Ligne", "Valeur", *(c.name for c in frame.columns if c.type == "number")},
            )
        )
    groups = [(c.name, [v for v in c.values if v is not None]) for c in cols[:12]]
    if len(groups) == 1:
        artifacts.insert(
            0,
            charts.artifact(
                f"Boîte à moustaches — {groups[0][0]}",
                charts.box(groups, y_label=groups[0][0]),
                source=frame.name,
            ),
        )
    return Result("\n".join(lines), artifacts)


# ─── Agrégation ───────────────────────────────────────────────────

PERIOD_LABELS: dict[str, str] = {
    "annee": "année", "trimestre": "trimestre", "mois": "mois", "semaine": "semaine", "jour": "jour",
}  # fmt: skip


def period_key(iso: str, period: Period) -> str:
    d = date.fromisoformat(iso[:10])
    if period == "annee":
        return f"{d.year}"
    if period == "trimestre":
        return f"{d.year}-T{(d.month - 1) // 3 + 1}"
    if period == "mois":
        return f"{d.year}-{d.month:02d}"
    if period == "semaine":
        y, w, _ = d.isocalendar()
        return f"{y}-S{w:02d}"
    return d.isoformat()


_AGG: dict[str, Callable[[list[Any]], float | None]] = {
    "nombre": lambda vs: float(len(vs)),
    "somme": lambda vs: math.fsum(vs) if vs else 0.0,
    "moyenne": lambda vs: stats.mean(vs) if vs else None,
    "mediane": lambda vs: stats.quantile(sorted(vs), 0.5) if vs else None,
    "ecart_type": lambda vs: stats.std(vs) if len(vs) > 1 else None,
    "min": lambda vs: min(vs) if vs else None,
    "max": lambda vs: max(vs) if vs else None,
    "distinct": lambda vs: float(len(set(vs))),
    "p25": lambda vs: stats.quantile(sorted(vs), 0.25) if vs else None,
    "p75": lambda vs: stats.quantile(sorted(vs), 0.75) if vs else None,
}
_NEEDS_NUMBER = {"somme", "moyenne", "mediane", "ecart_type", "p25", "p75"}


@dataclass(frozen=True)
class MeasureSpec:
    fonction: AggName
    colonne: str | None = None

    @property
    def key(self) -> str:
        return f"{self.fonction}({self.colonne or '*'})"


def group_by(
    frame: Frame, by: Sequence[str], measures: Sequence[MeasureSpec], period: Period | None
) -> tuple[list[str], list[list[Any]]]:
    dims = [frame.column(b) for b in by]
    cols: list[Column | None] = []
    for m in measures:
        if m.colonne is None:
            if m.fonction not in ("nombre",):
                raise ColumnError(f"« {m.fonction} » demande une colonne.")
            cols.append(None)
            continue
        c = frame.column(m.colonne)
        if m.fonction in _NEEDS_NUMBER and c.type != "number":
            raise ColumnError(
                f"« {m.fonction} » demande une colonne de nombres ; « {c.name} » est {TYPE_LABELS[c.type]}."
            )
        cols.append(c)
    buckets: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for i in range(frame.rows):
        key = []
        for d in dims:
            v = d.values[i]
            if v is not None and d.type == "date" and period:
                v = period_key(v, period)
            key.append("∅" if v is None else _label(v))
        buckets[tuple(key)].append(i)
    headers = [
        (f"{d.name} ({PERIOD_LABELS[period]})" if d.type == "date" and period else d.name)
        for d in dims
    ] + [m.key for m in measures]
    rows: list[list[Any]] = []
    for bucket_key, idx in buckets.items():
        row: list[Any] = list(bucket_key)
        for m, mcol in zip(measures, cols, strict=True):
            vs = (
                [i for i in idx]
                if mcol is None
                else [mcol.values[i] for i in idx if mcol.values[i] is not None]
            )
            row.append(_AGG[m.fonction](vs))
        rows.append(row)
    if not dims:
        return headers, rows
    rows.sort(key=lambda r: tuple(natural_key(x) for x in r[: len(dims)]))
    return headers, rows


def aggregate(
    frame: Frame,
    by: Sequence[str],
    measures: Sequence[MeasureSpec],
    period: Period | None,
    sort: str | None,
    descending: bool,
    limit: int,
) -> Result:
    headers, rows = group_by(frame, by, measures, period)
    if sort:
        if sort not in headers:
            raise ColumnError(f"Tri sur « {sort} » impossible ; clés : {', '.join(headers)}.")
        j = headers.index(sort)
        present = sorted(
            (r for r in rows if r[j] is not None), key=lambda r: r[j], reverse=descending
        )
        rows = present + [r for r in rows if r[j] is None]  # les vides restent en fin
    total = len(rows)
    rows = rows[:limit]
    lines = [
        _source_line(frame),
        f"{total} groupe(s){f' ; {limit} premiers' if total > limit else ''} :",
    ]
    lines.append(
        markdown_table(
            headers, [[num(v) if isinstance(v, float) else v for v in r] for r in rows[:50]]
        )
    )
    if len(rows) > 50:
        lines.append("[suite dans l'artefact]")
    numeric = {m.key for m in measures}
    return Result(
        "\n".join(lines),
        [data_artifact(f"Agrégation — {frame.label}", headers, rows, numeric=numeric)],
    )


# ─── Graphique libre ──────────────────────────────────────────────

ChartKind = Literal["histogramme", "boite", "nuage", "barres", "courbe"]


def chart(
    frame: Frame,
    kind: ChartKind,
    x: str | None,
    y: str | None,
    agg: AggName | None,
    group: str | None,
    period: Period | None,
    title: str | None,
) -> Result:
    if kind == "histogramme":
        col = frame.column(x or y or "")
        values = frame.numeric(col.name)
        d = stats.describe(values)
        if d is None:
            raise ColumnError(f"« {col.name} » est vide.")
        spec = charts.histogram(
            values, x_label=col.name, markers={"Moyenne": d.mean, "Médiane": d.median}
        )
        name = title or f"Distribution — {col.name}"
        return Result(
            f"Histogramme de « {col.name} » publié ({d.n} valeurs).",
            [charts.artifact(name, spec, source=frame.name)],
        )
    if kind == "boite":
        value_col = frame.column(y or x or "")
        values_name = value_col.name
        if group or (x and y):
            gcol = frame.column(group or x or "")
            groups, _ = _groups(frame, value_col, gcol)
            spec = charts.box(groups, y_label=values_name, x_label=gcol.name)
        else:
            spec = charts.box([(values_name, frame.numeric(values_name))], y_label=values_name)
        name = title or f"Boîtes à moustaches — {values_name}"
        return Result(
            f"Boîte(s) à moustaches de « {values_name} » publiée(s).",
            [charts.artifact(name, spec, source=frame.name)],
        )
    if kind == "nuage":
        if not x or not y:
            raise ColumnError("Un nuage de points demande `x` et `y`.")
        cx, cy = frame.column(x), frame.column(y)
        for c in (cx, cy):
            if c.type not in ("number", "date", "boolean"):
                raise ColumnError(
                    f"« {c.name} » est de type {TYPE_LABELS[c.type]} : un nuage de points demande "
                    "deux colonnes numériques (ou une date)."
                )
        vx, vy = _numeric_values(cx), _numeric_values(cy)
        color_col = frame.column(group) if group else None
        xs: list[float] = []
        ys: list[float] = []
        gs: list[str] = []
        for i, (a, b) in enumerate(zip(vx, vy, strict=True)):
            if a is None or b is None:
                continue
            xs.append(a)
            ys.append(b)
            if color_col is not None:
                value = color_col.values[i]
                gs.append(_label(value) if value is not None else "∅")
        if len(xs) < 2:
            raise ColumnError("Moins de 2 points complets.")
        reg = stats.linear_regression(xs, ys) if color_col is None else None
        spec = charts.scatter(
            xs, ys, x_label=cx.name, y_label=cy.name, x_kind="date" if cx.type == "date" else "number",
            groups=gs if color_col is not None else None, trend=reg,
        )  # fmt: skip
        name = title or f"{cy.name} selon {cx.name}"
        return Result(
            f"Nuage de points publié ({len(xs)} points).",
            [charts.artifact(name, spec, source=frame.name)],
        )
    # barres / courbe : x = catégorie ou date, y agrégé
    if not x:
        raise ColumnError(f"Un graphique en {kind} demande `x`.")
    cx = frame.column(x)
    fn: AggName = agg or ("somme" if y else "nombre")
    if y and fn not in ("nombre", "distinct") and frame.column(y).type != "number":
        raise ColumnError(
            f"« {fn} » de « {frame.column(y).name} » ne donne pas un nombre : choisis une colonne de "
            "nombres, ou l'agrégation « nombre » / « distinct »."
        )
    measure = MeasureSpec(fn, y)
    by = [cx.name] + ([group] if group else [])
    p = period or (
        _auto_period([v for v in cx.values if v is not None]) if cx.type == "date" else None
    )
    headers, rows = group_by(frame, by, [measure], p)
    notes: list[str] = []
    if group:
        totals: dict[str, float] = defaultdict(float)
        for r in rows:
            totals[r[1]] += abs(r[2]) if isinstance(r[2], int | float) else 0
        series_names = sorted(totals, key=lambda k: -totals[k])[:8]
        if len(totals) > 8:
            notes.append(f"{len(totals) - 8} série(s) moins importante(s) non affichée(s).")
        labels = sorted({r[0] for r in rows}, key=natural_key)
        table = {(r[0], r[1]): r[2] for r in rows}
        series = [(s, [table.get((lab, s)) for lab in labels]) for s in series_names]
    else:
        labels = [r[0] for r in rows]
        series = [(measure.key, [r[1] for r in rows])]
        if kind == "barres" and cx.type != "date":
            order = sorted(range(len(labels)), key=lambda i: -(series[0][1][i] or 0))[:30]
            labels = [labels[i] for i in order]
            series = [(measure.key, [rows[i][1] for i in order])]
    if len(labels) > charts.MAX_CATEGORIES and not (kind == "courbe" and cx.type == "date"):
        notes.append(
            f"{len(labels) - charts.MAX_CATEGORIES} catégorie(s) au-delà des "
            f"{charts.MAX_CATEGORIES} premières non affichée(s)."
        )
        labels = labels[: charts.MAX_CATEGORIES]
        series = [(name, values[: charts.MAX_CATEGORIES]) for name, values in series]
    elif len(labels) > 400:  # courbe temporelle : période plus large conseillée
        notes.append(
            f"{len(labels) - 400} période(s) les plus anciennes non affichées : choisis une `periode` plus large."
        )
        labels = labels[-400:]
        series = [(name, values[-400:]) for name, values in series]
    chart_kind: Literal["bar", "line"] = "bar" if kind == "barres" else "line"
    y_label = f"{_AGG_LABELS[fn]}{f' de {y}' if y else ''}"
    spec = charts.categories(
        labels, series, kind=chart_kind, x_label=headers[0], y_label=y_label,
        x_kind="date" if cx.type == "date" else "category",
    )  # fmt: skip
    name = title or f"{y_label} par {headers[0]}"
    return Result(
        f"Graphique « {name} » publié ({len(labels)} catégorie(s), {len(series)} série(s))."
        + "".join(f" {n}" for n in notes),
        [charts.artifact(name, spec, source=frame.name)],
    )


_AGG_LABELS: dict[str, str] = {
    "nombre": "Nombre", "somme": "Somme", "moyenne": "Moyenne", "mediane": "Médiane",
    "ecart_type": "Écart-type", "min": "Minimum", "max": "Maximum", "distinct": "Valeurs distinctes",
    "p25": "1er quartile", "p75": "3e quartile",
}  # fmt: skip


# ─── Export ───────────────────────────────────────────────────────


def export(frame: Frame, limit: int) -> Result:
    rows = [[c.values[i] for c in frame.columns] for i in range(min(frame.rows, limit))]
    lines = [
        _source_line(frame),
        f"Jeu publié dans le panneau Artefacts ({len(rows)} ligne(s)) : l'utilisateur peut le "
        "télécharger en CSV (séparateur « ; »).",
    ]
    if frame.rows > limit:
        lines.append(f"Seules les {limit} premières lignes sont dans l'artefact.")
    if frame.recipe:
        lines.append(f"Recette de nettoyage : {len(frame.recipe)} opération(s).")
    return Result(
        "\n".join(lines),
        [
            data_artifact(
                f"Jeu — {frame.label}",
                frame.names(),
                rows,
                numeric={c.name for c in frame.columns if c.type == "number"},
                metadata={"recipe": frame.recipe} if frame.recipe else None,
            )
        ],
    )
