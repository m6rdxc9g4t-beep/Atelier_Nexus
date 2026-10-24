"""Spécifications des graphiques du panneau Artefacts (artefact `chart`, format `atelier-chart/1`).

Le frontend dessine ces spécifications en SVG (`frontend/src/features/artifacts/charts/`).
Une spécification ne contient que des nombres et des libellés déjà calculés : aucun calcul ni
code côté interface. Volumes bornés (classes, points échantillonnés) pour rester léger.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any, Literal

from app.analysis import stats
from app.tools.base import Artifact

CHART_FORMAT = "atelier-chart/1"
MAX_POINTS = 2000
MAX_OUTLIERS = 60
MAX_CATEGORIES = 40

ChartType = Literal["histogram", "box", "scatter", "bar", "line", "heatmap"]


def _num(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(f"{value:.6g}")


def artifact(
    title: str, spec: dict[str, Any], *, notes: str | None = None, source: str | None = None
) -> Artifact:
    payload = {"format": CHART_FORMAT, "title": title, **spec}
    metadata: dict[str, Any] = {}
    if notes:
        metadata["notes"] = notes
    if source:
        metadata["source"] = source
    return Artifact(
        kind="chart",
        title=title,
        content=json.dumps(payload, ensure_ascii=False, allow_nan=False),
        language="json",
        metadata=metadata,
    )


def histogram(
    values: Sequence[float], *, x_label: str, markers: dict[str, float] | None = None
) -> dict[str, Any]:
    bins = stats.histogram(values)
    return {
        "type": "histogram",
        "x": {"label": x_label},
        "y": {"label": "Effectif"},
        "bins": [{"start": _num(b.start), "end": _num(b.end), "count": b.count} for b in bins],
        "markers": [
            {"label": k, "value": _num(v)}
            for k, v in (markers or {}).items()
            if _num(v) is not None
        ],
    }


def box_groups(groups: Sequence[tuple[str, Sequence[float]]]) -> list[dict[str, Any]]:
    out = []
    for label, values in groups[:MAX_CATEGORIES]:
        if not values:
            continue
        s = sorted(values)
        fences = stats.iqr_fences(s)
        inside = [v for v in s if fences.low <= v <= fences.high] or s
        outliers = [v for v in s if not fences.low <= v <= fences.high]
        if len(outliers) > MAX_OUTLIERS:  # les plus extrêmes de chaque côté
            outliers = outliers[: MAX_OUTLIERS // 2] + outliers[-MAX_OUTLIERS // 2 :]
        out.append(
            {
                "label": label,
                "n": len(s),
                "min": _num(inside[0]),
                "q1": _num(stats.quantile(s, 0.25)),
                "median": _num(stats.quantile(s, 0.5)),
                "q3": _num(stats.quantile(s, 0.75)),
                "max": _num(inside[-1]),
                "mean": _num(stats.mean(s)),
                "outliers": [_num(v) for v in outliers],
            }
        )
    return out


def box(
    groups: Sequence[tuple[str, Sequence[float]]], *, y_label: str, x_label: str = ""
) -> dict[str, Any]:
    return {
        "type": "box",
        "x": {"label": x_label},
        "y": {"label": y_label},
        "groups": box_groups(groups),
    }


def sample_indices(n: int, limit: int = MAX_POINTS) -> list[int]:
    """Indices régulièrement espacés (déterministe) quand il y a trop de points."""
    if n <= limit:
        return list(range(n))
    step = n / limit
    return [int(i * step) for i in range(limit)]


def scatter(
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    x_label: str,
    y_label: str,
    x_kind: Literal["number", "date"] = "number",
    groups: Sequence[str] | None = None,
    trend: stats.Regression | None = None,
) -> dict[str, Any]:
    idx = sample_indices(len(xs))
    spec: dict[str, Any] = {
        "type": "scatter",
        "x": {"label": x_label, "kind": x_kind},
        "y": {"label": y_label},
        "points": [[_num(xs[i]), _num(ys[i])] for i in idx],
        "sampled": len(idx) < len(xs),
        "total": len(xs),
    }
    if groups is not None:
        spec["groups"] = [groups[i] for i in idx]
    if trend is not None:
        spec["trend"] = {
            "slope": _num(trend.slope),
            "intercept": _num(trend.intercept),
            "r2": _num(trend.r2),
        }
    return spec


def categories(
    labels: Sequence[str],
    series: Sequence[tuple[str, Sequence[float | None]]],
    *,
    kind: Literal["bar", "line"],
    x_label: str,
    y_label: str,
    x_kind: Literal["category", "date"] = "category",
) -> dict[str, Any]:
    return {
        "type": kind,
        "x": {"label": x_label, "kind": x_kind},
        "y": {"label": y_label},
        "categories": list(labels),
        "series": [
            {"name": name, "values": [_num(v) if v is not None else None for v in values]}
            for name, values in series
        ],
    }


def heatmap(
    labels: Sequence[str],
    matrix: Sequence[Sequence[float | None]],
    *,
    label: str,
    domain: tuple[float, float] = (-1.0, 1.0),
) -> dict[str, Any]:
    return {
        "type": "heatmap",
        "labels": list(labels),
        "values": [[_num(v) if v is not None else None for v in row] for row in matrix],
        "domain": list(domain),
        "legend": label,
    }
