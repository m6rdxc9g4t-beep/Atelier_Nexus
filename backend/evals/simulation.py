"""Applications simulées pour les évaluations : résultats reproductibles, sans rien lancer.

- **Data Via (Atelier Viz)** : un vrai petit moteur d'agrégation sur un jeu de ventes généré
  (graine fixe). Les chiffres renvoyés à l'agent sont exacts : on peut vérifier ensuite qu'il
  ne les a pas inventés.
- **Atelier Projets** et **Atelier Trésorerie** : les réponses réelles enregistrées dans
  `tests/fixtures/` (démo « App E-Commerce v2 », six mois fictifs de Trésorerie).

Les écritures ne sont jamais exécutées pendant une évaluation (aucune validation n'est donnée) ;
la simulation de Projets accepte tout de même une création, pour les tests.
"""

from __future__ import annotations

import ast
import json
import random
import re
import statistics
from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.tools.environment import ToolEnvironment

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

#: Applications disponibles en mode simulé (identifiants des cas d'évaluation)
SIMULATED_APPS = ("data_via", "projets", "tresorerie")

# ─── Data Via ─────────────────────────────────────────────────────

DATASET_ID = "ventes_2026"
REGIONS = ("Bretagne", "Occitanie", "Île-de-France", "Normandie", "Grand Est")
PRODUCTS = {"Logiciel": (900.0, 0.45), "Support": (300.0, 0.30), "Formation": (650.0, 0.55)}
COLUMNS: dict[str, str] = {
    "date": "date",
    "region": "string",
    "produit": "string",
    "chiffre_affaires": "number",
    "quantite": "number",
    "cout": "number",
}
MEASURES = {"marge": "SUM(chiffre_affaires) - SUM(cout)"}


def sales_rows() -> list[dict[str, Any]]:
    """240 ventes de janvier à septembre 2026, toujours les mêmes."""
    rng = random.Random(2026)
    start = date(2026, 1, 2)
    rows = []
    for i in range(240):
        day = start + timedelta(days=rng.randint(0, 271))
        product = rng.choice(list(PRODUCTS))
        price, cost_ratio = PRODUCTS[product]
        quantity = rng.randint(1, 6)
        revenue = round(quantity * price * rng.uniform(0.85, 1.15), 2)
        rows.append(
            {
                "date": day.isoformat(),
                "region": REGIONS[(i * 7 + rng.randint(0, 4)) % len(REGIONS)],
                "produit": product,
                "chiffre_affaires": revenue,
                "quantite": quantity,
                "cout": round(revenue * cost_ratio, 2),
            }
        )
    return sorted(rows, key=lambda r: str(r["date"]))


def _period(value: str, bin_: str | None) -> str:
    day = date.fromisoformat(value)
    if bin_ == "year":
        return f"{day.year}"
    if bin_ == "quarter":
        return f"{day.year}-T{(day.month - 1) // 3 + 1}"
    if bin_ == "month":
        return f"{day.year}-{day.month:02d}"
    if bin_ == "week":
        iso = day.isocalendar()
        return f"{iso.year}-S{iso.week:02d}"
    return day.isoformat()


def _aggregate(agg: str, field: str | None, rows: list[dict[str, Any]]) -> float | int | None:
    if agg == "count":
        return len(rows) if field is None else sum(1 for r in rows if r.get(field) is not None)
    if agg == "calc":
        if field not in MEASURES:
            raise KeyError(field)
        revenue = sum(float(r["chiffre_affaires"]) for r in rows)
        return round(revenue - sum(float(r["cout"]) for r in rows), 2)
    values = [r[field] for r in rows if field and r.get(field) is not None]
    if agg == "count_distinct":
        return len(set(values))
    if not values:
        return None
    numbers = [float(v) for v in values]
    result: float = {
        "sum": sum(numbers),
        "avg": statistics.fmean(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "median": statistics.median(numbers),
    }[agg]
    return round(result, 2)


def _matches(row: dict[str, Any], flt: dict[str, Any]) -> bool:
    value = row.get(flt["field"])
    if flt.get("bin") and value is not None:
        value = _period(value, flt["bin"])
    op, values = flt.get("op", "in"), flt.get("values", [])
    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    if op == "in":
        return value in values
    if op == "not_in":
        return value not in values
    if op == "contains":
        return str(values[0]).lower() in str(value).lower()
    if op == "between":
        return bool(values[0] <= value <= values[1])
    comparisons: dict[str, Callable[[Any, Any], bool]] = {
        "eq": lambda a, b: a == b,
        "neq": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
    }
    return comparisons[op](value, values[0])


def run_query(body: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrégation façon Atelier Viz (clés `champ`, `champ|période`, `agg(champ)`)."""
    for item in [*body.get("dimensions", []), *body.get("filters", [])]:
        if item["field"] not in COLUMNS:
            raise ValueError(f"Champ inconnu : {item['field']}")
    kept = [r for r in rows if all(_matches(r, f) for f in body.get("filters", []))]
    dims = body.get("dimensions", [])
    measures = body.get("measures", [])
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in kept:
        key = tuple(
            _period(row[d["field"]], d["bin"]) if d.get("bin") else row[d["field"]] for d in dims
        )
        groups[key].append(row)
    columns = [
        {
            "key": f"{d['field']}|{d['bin']}" if d.get("bin") else d["field"],
            "field": d["field"],
            "role": "dimension",
            "type": "string" if d.get("bin") else COLUMNS[d["field"]],
        }
        for d in dims
    ] + [
        {
            "key": f"{m.get('agg', 'sum')}({m.get('field') or '*'})",
            "field": m.get("field"),
            "role": "measure",
            "type": "number",
        }
        for m in measures
    ]
    out_rows = [
        [*key, *(_aggregate(m.get("agg", "sum"), m.get("field"), members) for m in measures)]
        for key, members in sorted(groups.items(), key=lambda kv: [str(k) for k in kv[0]])
    ]
    keys = [c["key"] for c in columns]
    for sort in reversed(body.get("sort", [])):
        index = keys.index(sort["key"])
        out_rows.sort(
            key=lambda r: (r[index] is None, r[index] if r[index] is not None else 0),
            reverse=bool(sort.get("desc")),
        )
    limit = int(body.get("limit", 5000))
    return {"columns": columns, "rows": out_rows[:limit], "truncated": len(out_rows) > limit}


_AGG_CALL = re.compile(
    r"\b(SUM|AVG|MIN|MAX|COUNT|MEDIAN|SOMME|MOYENNE)\s*\(\s*\[?([\w ']*?)\]?\s*\)", re.I
)


def _arithmetic(node: ast.expr) -> float | None:
    """Évalue + - * / sur des nombres et `_divide(a, b)` ; tout le reste est refusé."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        operand = _arithmetic(node.operand)
        if operand is None:
            return None
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub | ast.Mult | ast.Div):
        left, right = _arithmetic(node.left), _arithmetic(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_divide"
        and len(node.args) == 2
    ):
        num, den = _arithmetic(node.args[0]), _arithmetic(node.args[1])
        return None if num is None or not den else num / den
    raise ValueError("Fonction ou colonne non reconnue")


def check_expression(expression: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Vérifie une mesure simple (agrégats, DIVIDE, + - * /) et en calcule la valeur."""
    names = {"SOMME": "sum", "MOYENNE": "avg"}

    def replace(match: re.Match[str]) -> str:
        func, field = match.group(1).upper(), match.group(2).strip()
        agg = names.get(func, func.lower())
        if field in ("", "*") and agg == "count":
            return str(len(rows))
        if field not in COLUMNS:
            raise ValueError(f"Colonne inconnue : {field}")
        value = _aggregate(agg, field, rows)
        return repr(float(value or 0))

    try:
        text = _AGG_CALL.sub(replace, expression)
        text = re.sub(r"\b(?:DIVIDE|DIVISER)\s*\(", "_divide(", text, flags=re.I)
        value = _arithmetic(ast.parse(text, mode="eval").body)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "position": 0}
    except (SyntaxError, ZeroDivisionError, TypeError):
        return {"ok": False, "error": "Expression invalide", "position": 0}
    preview = [round(value, 4)] if isinstance(value, int | float) else [None]
    return {"ok": True, "type": "number", "preview": preview}


class SimulatedDataVia:
    """Atelier Viz simulé : un jeu de ventes, le langage de requête et la vérification d'expression."""

    def __init__(self) -> None:
        self.rows = sales_rows()
        self.requests: list[httpx.Request] = []

    def profile(self) -> dict[str, Any]:
        columns = []
        for name, kind in COLUMNS.items():
            values = [r[name] for r in self.rows]
            column: dict[str, Any] = {
                "name": name,
                "type": kind,
                "nulls": 0,
                "distinct": len(set(values)),
                "top_values": [],
            }
            if kind in {"number", "date"}:
                column["min"], column["max"] = min(values), max(values)
            if kind == "number":
                column["mean"] = round(statistics.fmean(values), 2)
            if kind == "string":
                counts: dict[str, int] = defaultdict(int)
                for v in values:
                    counts[v] += 1
                column["top_values"] = [
                    {"value": v, "count": c} for v, c in sorted(counts.items(), key=lambda x: -x[1])
                ]
            columns.append(column)
        return {
            **self.summary(),
            "columns": columns,
            "sample": self.rows[:5],
            "model": {
                "columns": [],
                "measures": [{"name": n, "expression": e} for n, e in MEASURES.items()],
            },
        }

    def summary(self) -> dict[str, Any]:
        return {
            "id": DATASET_ID,
            "name": "ventes_2026.csv",
            "format": "csv",
            "rows": len(self.rows),
            "columns_count": len(COLUMNS),
            "created_at": "2026-10-20T08:00:00Z",
            "origin": None,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api")
        method = request.method
        if (method, path) == ("GET", "/health"):
            return httpx.Response(
                200, json={"status": "ok", "version": "simule", "environment": "eval"}
            )
        if (method, path) == ("GET", "/datasets"):
            return httpx.Response(200, json=[self.summary()])
        if path.startswith("/datasets/") and not path.startswith(f"/datasets/{DATASET_ID}"):
            return httpx.Response(404, json={"detail": "Jeu de données introuvable."})
        if (method, path) == ("GET", f"/datasets/{DATASET_ID}"):
            return httpx.Response(200, json=self.profile())
        if (method, path) == ("GET", f"/datasets/{DATASET_ID}/rows"):
            offset = int(request.url.params.get("offset", "0"))
            limit = int(request.url.params.get("limit", "100"))
            return httpx.Response(
                200,
                json={
                    "columns": list(COLUMNS),
                    "rows": self.rows[offset : offset + limit],
                    "total": len(self.rows),
                    "offset": offset,
                    "limit": limit,
                },
            )
        if (method, path) == ("POST", "/query"):
            try:
                return httpx.Response(200, json=run_query(json.loads(request.content), self.rows))
            except (ValueError, KeyError) as exc:
                return httpx.Response(422, json={"detail": str(exc)})
        if (method, path) == ("POST", f"/datasets/{DATASET_ID}/model/check"):
            body = json.loads(request.content)
            return httpx.Response(200, json=check_expression(body["expression"], self.rows))
        return httpx.Response(404, json={"detail": "Route inconnue de la simulation."})


# ─── Projets et Trésorerie (réponses réelles enregistrées) ────────


def _fixture(app: str, name: str) -> Any:
    return json.loads((FIXTURES / app / f"{name}.json").read_text(encoding="utf-8"))


PROJETS_ROUTES = {
    "/api/health": "health",
    "/api/projects": "projects",
    "/api/projects/1/dashboard": "dashboard",
    "/api/projects/1/tree": "tree",
    "/api/projects/1/work-items": "work_items",
    "/api/work-items/12345": "work_item_12345",
    "/api/projects/1/timesheet": "timesheet",
    "/api/projects/1/milestones": "milestones",
}


class SimulatedProjets:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path in PROJETS_ROUTES:
            return httpx.Response(200, json=_fixture("projets", PROJETS_ROUTES[path]))
        if request.method == "POST" and re.fullmatch(r"/api/stories/\d+/work-items", path):
            body = json.loads(request.content)
            created = _fixture("projets", "work_item_12345") | {
                "id": 20001,
                "title": body.get("title", ""),
                "type": body.get("type", "TASK"),
                "status": "OPEN",
            }
            return httpx.Response(201, json=created)
        return httpx.Response(404, json={"statusCode": 404, "message": "Ressource introuvable"})


class SimulatedTresorerie:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "GET":
            return httpx.Response(405, json={"error": "Lecture seule"})
        name = request.url.path.removeprefix("/api/")
        try:
            return httpx.Response(200, json=_fixture("tresorerie", name))
        except (FileNotFoundError, ValueError):
            return httpx.Response(404, json={"error": "Ressource introuvable"})


# ─── Environnement ────────────────────────────────────────────────


def simulated_settings() -> Settings:
    """Seules les applications simulées sont configurées ; les autres boîtes sont écartées."""
    return Settings(
        _env_file=None,
        data_via_base_url="http://viz.simule/api",
        projets_base_url="http://projets.simule/api",
        tresorerie_base_url="http://tresorerie.simule/api",
        cine_base_url=None,
        savoir_base_url=None,
        tab_exports_dir=None,
        tab_mcp_command=None,
        github_repo=None,
        github_allowed_repos="",
        cuisine_supabase_url=None,
    )


def simulated_environment() -> ToolEnvironment:
    return ToolEnvironment(
        simulated_settings(),
        transports={
            "data_via": httpx.MockTransport(SimulatedDataVia()),
            "projets": httpx.MockTransport(SimulatedProjets()),
            "tresorerie": httpx.MockTransport(SimulatedTresorerie()),
        },
    )
