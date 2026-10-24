"""Fonctions spéciales pour les valeurs p (sans SciPy).

Bêta incomplète régularisée et gamma incomplète régularisée par fractions continues
(algorithme de Lentz modifié, Numerical Recipes §6.2 et §6.4). Précision ~1e-12, largement
suffisante pour des valeurs p affichées à 3 chiffres.
"""

from __future__ import annotations

import math

_EPS = 1e-15
_TINY = 1e-300
_MAX_ITER = 500


def normal_sf(z: float) -> float:
    """P(Z > z) pour une loi normale centrée réduite."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def normal_two_sided(z: float) -> float:
    return min(1.0, 2.0 * normal_sf(abs(z)))


def _beta_cf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Bêta incomplète régularisée I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_cf(a, b, x) / a
    return 1.0 - front * _beta_cf(b, a, 1.0 - x) / b


def gammainc_upper(a: float, x: float) -> float:
    """Gamma incomplète régularisée supérieure Q(a, x) = 1 - P(a, x)."""
    if x <= 0.0:
        return 1.0
    if x < a + 1.0:  # série pour P, puis complément
        term = total = 1.0 / a
        ap = a
        for _ in range(_MAX_ITER):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        p = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, 1.0 - p)
    # fraction continue pour Q
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = b + an / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def t_two_sided(t: float, df: float) -> float:
    """Valeur p bilatérale d'une statistique t de Student à `df` degrés de liberté."""
    if df <= 0 or not math.isfinite(t):
        return 0.0 if math.isinf(t) else float("nan")
    return min(1.0, betainc(df / 2.0, 0.5, df / (df + t * t)))


def f_sf(f: float, d1: float, d2: float) -> float:
    """P(F > f) pour une loi de Fisher (d1, d2)."""
    if f <= 0:
        return 1.0
    if not math.isfinite(f):
        return 0.0
    return min(1.0, betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f)))


def chi2_sf(x: float, k: float) -> float:
    """P(X > x) pour une loi du khi² à `k` degrés de liberté."""
    if x <= 0:
        return 1.0
    if not math.isfinite(x):
        return 0.0
    return gammainc_upper(k / 2.0, x / 2.0)
