"""Statistiques descriptives et tests, sur des listes de nombres (valeurs manquantes retirées).

Conventions (identiques à SciPy / pandas, vérifiées par les tests) :
- écart-type et variance d'échantillon (ddof = 1) ;
- quantiles par interpolation linéaire (type 7, défaut de pandas et numpy) ;
- asymétrie G1 et aplatissement en excès G2 corrigés du biais (pandas `skew()` / `kurt()`) ;
- normalité : test K² de D'Agostino et Pearson (`scipy.stats.normaltest`), à partir de 20 valeurs ;
- Spearman = Pearson sur les rangs moyens ; valeurs p par la loi t (n - 2 ddl).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.analysis.special import chi2_sf, f_sf, normal_two_sided, t_two_sided

Number = float


# ─── Descriptives ─────────────────────────────────────────────────


def mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs)


def variance(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    m = mean(xs)
    return math.fsum((x - m) ** 2 for x in xs) / (n - 1)


def std(xs: Sequence[float]) -> float:
    v = variance(xs)
    return math.sqrt(v) if v == v else v


def quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Quantile d'une liste TRIÉE (interpolation linéaire, type 7)."""
    n = len(sorted_xs)
    if n == 0:
        return float("nan")
    pos = (n - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def _central_moments(xs: Sequence[float]) -> tuple[float, float, float]:
    m = mean(xs)
    n = len(xs)
    m2 = math.fsum((x - m) ** 2 for x in xs) / n
    m3 = math.fsum((x - m) ** 3 for x in xs) / n
    m4 = math.fsum((x - m) ** 4 for x in xs) / n
    return m2, m3, m4


def skewness(xs: Sequence[float]) -> float:
    """Asymétrie corrigée G1 (pandas `skew`). NaN si moins de 3 valeurs ou variance nulle."""
    n = len(xs)
    if n < 3:
        return float("nan")
    m2, m3, _ = _central_moments(xs)
    if m2 <= 0:
        return float("nan")
    g1 = m3 / math.pow(m2, 1.5)
    return float(g1 * math.sqrt(n * (n - 1)) / (n - 2))


def kurtosis(xs: Sequence[float]) -> float:
    """Aplatissement en excès corrigé G2 (pandas `kurt`) : 0 pour une loi normale."""
    n = len(xs)
    if n < 4:
        return float("nan")
    m2, _, m4 = _central_moments(xs)
    if m2 <= 0:
        return float("nan")
    g2 = m4 / m2**2 - 3.0
    return ((n + 1) * g2 + 6.0) * (n - 1) / ((n - 2) * (n - 3))


@dataclass(frozen=True)
class Normality:
    statistic: float
    p_value: float
    z_skew: float
    z_kurt: float


def normality_test(xs: Sequence[float]) -> Normality | None:
    """Test K² de D'Agostino-Pearson (comme `scipy.stats.normaltest`). None si n < 20."""
    n = len(xs)
    if n < 20:
        return None
    m2, m3, m4 = _central_moments(xs)
    if m2 <= 0:
        return None
    b1 = m3 / m2**1.5  # asymétrie non corrigée
    # Test de l'asymétrie
    y = b1 * math.sqrt(((n + 1) * (n + 3)) / (6.0 * (n - 2)))
    beta2 = (
        3.0 * (n * n + 27 * n - 70) * (n + 1) * (n + 3) / ((n - 2.0) * (n + 5) * (n + 7) * (n + 9))
    )
    w2 = -1.0 + math.sqrt(2.0 * (beta2 - 1.0))
    delta = 1.0 / math.sqrt(0.5 * math.log(w2))
    alpha = math.sqrt(2.0 / (w2 - 1.0))
    y = y if y != 0 else 1.0
    z_skew = delta * math.log(y / alpha + math.sqrt((y / alpha) ** 2 + 1.0))
    # Test de l'aplatissement
    b2 = m4 / m2**2
    e = 3.0 * (n - 1) / (n + 1)
    var_b2 = 24.0 * n * (n - 2) * (n - 3) / ((n + 1) * (n + 1.0) * (n + 3) * (n + 5))
    x = (b2 - e) / math.sqrt(var_b2)
    sqrt_beta1 = (
        6.0
        * (n * n - 5 * n + 2)
        / ((n + 7) * (n + 9))
        * math.sqrt((6.0 * (n + 3) * (n + 5)) / (n * (n - 2) * (n - 3)))
    )
    a = 6.0 + 8.0 / sqrt_beta1 * (2.0 / sqrt_beta1 + math.sqrt(1 + 4.0 / sqrt_beta1**2))
    term1 = 1 - 2 / (9.0 * a)
    denom = 1 + x * math.sqrt(2 / (a - 4.0))
    if denom == 0:
        return None
    term2 = math.copysign(1.0, denom) * ((1 - 2.0 / a) / abs(denom)) ** (1 / 3.0)
    z_kurt = (term1 - term2) / math.sqrt(2 / (9.0 * a))
    k2 = z_skew**2 + z_kurt**2
    return Normality(statistic=k2, p_value=chi2_sf(k2, 2), z_skew=z_skew, z_kurt=z_kurt)


@dataclass(frozen=True)
class Describe:
    n: int
    missing: int
    mean: float
    std: float
    min: float
    q1: float
    median: float
    q3: float
    max: float
    skew: float
    kurt: float
    distinct: int
    zeros: int
    negatives: int

    @property
    def iqr(self) -> float:
        return self.q3 - self.q1

    @property
    def cv(self) -> float:
        """Coefficient de variation (écart-type / moyenne), NaN si moyenne nulle."""
        return self.std / abs(self.mean) if self.mean else float("nan")


def describe(xs: Sequence[float], missing: int = 0) -> Describe | None:
    if not xs:
        return None
    s = sorted(xs)
    return Describe(
        n=len(s),
        missing=missing,
        mean=mean(s),
        std=std(s),
        min=s[0],
        q1=quantile(s, 0.25),
        median=quantile(s, 0.5),
        q3=quantile(s, 0.75),
        max=s[-1],
        skew=skewness(s),
        kurt=kurtosis(s),
        distinct=len(set(s)),
        zeros=sum(1 for x in s if x == 0),
        negatives=sum(1 for x in s if x < 0),
    )


# ─── Lecture des indicateurs ──────────────────────────────────────


def skew_label(g1: float) -> str:
    if g1 != g1:
        return "asymétrie non calculable"
    a = abs(g1)
    if a < 0.5:
        return "quasi symétrique"
    side = (
        "à droite (longue traîne vers les grandes valeurs)"
        if g1 > 0
        else ("à gauche (longue traîne vers les petites valeurs)")
    )
    return f"asymétrie {'modérée' if a < 1 else 'forte'} {side}"


def kurt_label(g2: float) -> str:
    if g2 != g2:
        return "aplatissement non calculable"
    if g2 > 1:
        return "queues épaisses (plus de valeurs extrêmes qu'une loi normale)"
    if g2 < -1:
        return "distribution aplatie (moins de valeurs extrêmes qu'une loi normale)"
    return "queues proches d'une loi normale"


def strength_label(r: float) -> str:
    if r != r:
        return "non calculable (variance nulle ou trop peu de lignes)"
    a = abs(r)
    if a < 0.1:
        word = "négligeable"
    elif a < 0.3:
        word = "faible"
    elif a < 0.5:
        word = "modérée"
    elif a < 0.7:
        word = "forte"
    else:
        word = "très forte"
    return word if a < 0.1 else f"{word} {'positive' if r > 0 else 'négative'}"


def transformation_hint(d: Describe, values: Sequence[float]) -> tuple[str, float] | None:
    """Transformation qui réduit une asymétrie forte : (nom, asymétrie après)."""
    if d.skew != d.skew or abs(d.skew) < 1:
        return None
    if d.skew > 0 and d.min > 0:
        name, out = "log", [math.log(x) for x in values]
    elif d.skew > 0 and d.min >= 0:
        name, out = "log1p", [math.log1p(x) for x in values]
    elif d.skew > 0:
        name, out = "racine signée", [math.copysign(math.sqrt(abs(x)), x) for x in values]
    else:
        top = d.max
        name, out = "log du reflet (max + 1 - x)", [math.log(top + 1 - x) for x in values]
    after = skewness(out)
    return (name, after) if after == after and abs(after) < abs(d.skew) else None


# ─── Histogramme ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Bin:
    start: float
    end: float
    count: int


def histogram(xs: Sequence[float], max_bins: int = 50) -> list[Bin]:
    """Classes de Freedman-Diaconis (Sturges si l'écart interquartile est nul) ; une classe
    par valeur pour des entiers peu nombreux (notes, quantités…)."""
    if not xs:
        return []
    s = sorted(xs)
    lo, hi = s[0], s[-1]
    distinct = sorted(set(s))
    if all(float(x).is_integer() for x in distinct) and len(distinct) <= 30 and hi - lo <= 60:
        counts = Counter(s)
        return [Bin(v - 0.5, v + 0.5, counts.get(v, 0)) for v in _int_range(lo, hi)]
    if hi == lo:
        return [Bin(lo, hi, len(s))]
    iqr = quantile(s, 0.75) - quantile(s, 0.25)
    n = len(s)
    if iqr > 0:
        width = 2 * iqr * n ** (-1 / 3)
        bins = math.ceil((hi - lo) / width)
    else:
        bins = math.ceil(math.log2(n) + 1)
    bins = max(5, min(max_bins, bins))
    width = (hi - lo) / bins
    counts_list = [0] * bins
    for x in s:
        i = min(bins - 1, int((x - lo) / width))
        counts_list[i] += 1
    return [Bin(lo + i * width, lo + (i + 1) * width, c) for i, c in enumerate(counts_list)]


def _int_range(lo: float, hi: float) -> list[float]:
    return [float(v) for v in range(int(lo), int(hi) + 1)]


# ─── Valeurs aberrantes ───────────────────────────────────────────


@dataclass(frozen=True)
class Fences:
    low: float
    high: float
    extreme_low: float
    extreme_high: float


def iqr_fences(xs: Sequence[float]) -> Fences:
    s = sorted(xs)
    q1, q3 = quantile(s, 0.25), quantile(s, 0.75)
    iqr = q3 - q1
    return Fences(q1 - 1.5 * iqr, q3 + 1.5 * iqr, q1 - 3 * iqr, q3 + 3 * iqr)


def mad_scores(xs: Sequence[float]) -> list[float]:
    """Score z robuste (Iglewicz et Hoaglin) : 0,6745 (x - médiane) / MAD ; > 3,5 = aberrant."""
    s = sorted(xs)
    med = quantile(s, 0.5)
    mad = quantile(sorted(abs(x - med) for x in s), 0.5)
    if mad == 0:
        return [0.0 if x == med else math.inf for x in xs]
    return [0.6745 * (x - med) / mad for x in xs]


# ─── Corrélations ─────────────────────────────────────────────────


def ranks(xs: Sequence[float]) -> list[float]:
    """Rangs moyens (1 = plus petite valeur), ex aequo au rang moyen."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


@dataclass(frozen=True)
class Correlation:
    r: float
    p_value: float
    n: int


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Correlation:
    n = len(xs)
    if n < 3:
        return Correlation(float("nan"), float("nan"), n)
    mx, my = mean(xs), mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    syy = math.fsum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return Correlation(float("nan"), float("nan"), n)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    r = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    return Correlation(r, _r_p_value(r, n), n)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Correlation:
    if len(xs) < 3:
        return Correlation(float("nan"), float("nan"), len(xs))
    c = pearson(ranks(xs), ranks(ys))
    return Correlation(c.r, c.p_value, c.n)


def _r_p_value(r: float, n: int) -> float:
    if abs(r) >= 1.0:
        return 0.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return t_two_sided(t, n - 2)


def holm(p_values: Sequence[float]) -> list[float]:
    """Valeurs p ajustées de Holm-Bonferroni (comparaisons multiples)."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


# ─── Régression linéaire simple ───────────────────────────────────


@dataclass(frozen=True)
class Regression:
    slope: float
    intercept: float
    r2: float
    p_value: float
    n: int


def linear_regression(xs: Sequence[float], ys: Sequence[float]) -> Regression | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    c = pearson(xs, ys)
    r2 = c.r**2 if c.r == c.r else 0.0
    return Regression(slope, my - slope * mx, r2, c.p_value, n)


# ─── Groupes : variable numérique selon une catégorie ─────────────


@dataclass(frozen=True)
class GroupTest:
    test: str
    statistic: float
    p_value: float
    effect: float
    effect_name: str
    detail: str = ""


def welch_t(a: Sequence[float], b: Sequence[float]) -> GroupTest | None:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = variance(a), variance(b)
    se2 = va / na + vb / nb
    if se2 == 0:
        return None
    t = (mean(a) - mean(b)) / math.sqrt(se2)
    df = se2**2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    d = (mean(a) - mean(b)) / pooled if pooled else float("nan")
    return GroupTest("t de Welch", t, t_two_sided(t, df), d, "d de Cohen", f"{df:.1f} ddl")


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> GroupTest | None:
    """U de Mann-Whitney, approximation normale avec correction des ex aequo et de continuité."""
    na, nb = len(a), len(b)
    if na < 1 or nb < 1:
        return None
    r = ranks(list(a) + list(b))
    ra = math.fsum(r[:na])
    u1 = ra - na * (na + 1) / 2.0
    u = min(u1, na * nb - u1)
    n = na + nb
    ties = Counter(r).values()
    tie_term = math.fsum(t**3 - t for t in ties) / (n * (n - 1)) if n > 1 else 0.0
    sigma = math.sqrt(na * nb / 12.0 * ((n + 1) - tie_term))
    if sigma == 0:
        return None
    z = (u - na * nb / 2.0 + 0.5) / sigma
    rank_biserial = 1 - 2 * u1 / (na * nb)
    return GroupTest(
        "U de Mann-Whitney",
        u1,
        normal_two_sided(z),
        -rank_biserial,
        "corrélation bisériale de rang",
    )


def anova(groups: Sequence[Sequence[float]]) -> GroupTest | None:
    """ANOVA à un facteur ; effet = η² (part de la variance expliquée par le groupe)."""
    groups = [g for g in groups if len(g) > 0]
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n - k < 1:
        return None
    grand = mean([x for g in groups for x in g])
    ss_between = math.fsum(len(g) * (mean(g) - grand) ** 2 for g in groups)
    ss_within = math.fsum((x - mean(g)) ** 2 for g in groups for x in g)
    ss_total = ss_between + ss_within
    if ss_within == 0:
        return None
    f = (ss_between / (k - 1)) / (ss_within / (n - k))
    eta2 = ss_between / ss_total if ss_total else float("nan")
    return GroupTest("ANOVA", f, f_sf(f, k - 1, n - k), eta2, "η²", f"F({k - 1}, {n - k})")


def kruskal(groups: Sequence[Sequence[float]]) -> GroupTest | None:
    """H de Kruskal-Wallis avec correction des ex aequo (comme `scipy.stats.kruskal`)."""
    groups = [g for g in groups if len(g) > 0]
    k = len(groups)
    if k < 2:
        return None
    pooled = [x for g in groups for x in g]
    n = len(pooled)
    r = ranks(pooled)
    h = 0.0
    start = 0
    for g in groups:
        rs = math.fsum(r[start : start + len(g)])
        h += rs * rs / len(g)
        start += len(g)
    h = 12.0 / (n * (n + 1)) * h - 3 * (n + 1)
    ties = Counter(r).values()
    correction = 1 - math.fsum(t**3 - t for t in ties) / (n**3 - n)
    if correction == 0:
        return None
    h /= correction
    epsilon2 = h / ((n * n - 1) / (n + 1)) if n > 1 else float("nan")
    return GroupTest("H de Kruskal-Wallis", h, chi2_sf(h, k - 1), epsilon2, "ε²", f"{k - 1} ddl")


# ─── Deux catégories ──────────────────────────────────────────────


@dataclass
class Contingency:
    rows: list[str]
    cols: list[str]
    counts: list[list[int]]
    chi2: float = float("nan")
    dof: int = 0
    p_value: float = float("nan")
    cramers_v: float = float("nan")
    low_expected: float = 0.0  # part des effectifs attendus < 5
    notes: list[str] = field(default_factory=list)


def contingency(a: Sequence[str], b: Sequence[str]) -> Contingency:
    rows = sorted(set(a))
    cols = sorted(set(b))
    ri = {v: i for i, v in enumerate(rows)}
    ci = {v: i for i, v in enumerate(cols)}
    counts = [[0] * len(cols) for _ in rows]
    for x, y in zip(a, b, strict=True):
        counts[ri[x]][ci[y]] += 1
    table = Contingency(rows, cols, counts)
    n = len(a)
    if len(rows) < 2 or len(cols) < 2 or n == 0:
        return table
    row_tot = [sum(r) for r in counts]
    col_tot = [sum(counts[i][j] for i in range(len(rows))) for j in range(len(cols))]
    chi2 = 0.0
    low = 0
    for i, rt in enumerate(row_tot):
        for j, ct in enumerate(col_tot):
            expected = rt * ct / n
            if expected < 5:
                low += 1
            if expected > 0:
                chi2 += (counts[i][j] - expected) ** 2 / expected
    dof = (len(rows) - 1) * (len(cols) - 1)
    table.chi2, table.dof = chi2, dof
    table.p_value = chi2_sf(chi2, dof)
    table.cramers_v = math.sqrt(chi2 / (n * (min(len(rows), len(cols)) - 1)))
    table.low_expected = low / (len(rows) * len(cols))
    return table
