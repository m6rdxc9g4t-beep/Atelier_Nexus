"""Doubles d'Atelier Wiki et d'Atelier Formulaire pour httpx.MockTransport.

Manifestes et réponses recopiés des dépôts (`Atelier_Wiki/backend/src/services/atelier-manifest.ts`,
`atelier-node.ts`, `routes/atelier.ts`, `routes/wiki.ts` ; `Atelier_Formulaire/backend/src/services/
atelier-manifest.ts`, `routes/atelier.ts`, `routes/forms.ts`, `domain/questions.ts`) : mêmes chemins,
mêmes formes, même idempotence par en-tête.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import httpx

ID = {"type": "string", "pattern": "^[0-9]+$"}
TABLE = {"format": "atelier-table/1", "schema": {"type": "object"}}


def _action(
    action_id: str, kind: str, method: str, path: str, schema: dict[str, Any], idem: str
) -> dict[str, Any]:
    return {
        "id": action_id, "label": action_id, "description": "", "kind": kind,
        "http": {"method": method, "path": path}, "mcp_tool": None,
        "input_schema": {"type": "object", "additionalProperties": False, **schema},
        "output": TABLE, "idempotency": idem,
    }  # fmt: skip


WIKI_MANIFEST = {
    "contract": "atelier-node/1", "app": "wiki", "name": "Atelier Wiki", "version": "0.4.0",
    "transport": "http",
    "actions": [
        _action("spaces.list", "read", "GET", "/api/atelier/spaces", {"properties": {}}, "natural"),
        _action("pages.search", "read", "POST", "/api/atelier/search", {
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 500},
                           "space_id": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "required": ["query"]}, "natural"),
        _action("pages.list", "read", "GET", "/api/atelier/pages", {
            "properties": {"space_id": ID, "updated_since": {"type": "string"},
                           "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}}, "natural"),
        _action("pages.get", "read", "GET", "/api/atelier/pages/{page_id}", {
            "properties": {"page_id": ID}, "required": ["page_id"]}, "natural"),
        _action("pages.create", "write", "POST", "/api/atelier/pages", {
            "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 200},
                           "content": {"type": "string"}, "space_id": ID, "parent_id": ID,
                           "icon": {"type": "string"}},
            "required": ["title"]}, "header"),
        _action("pages.append", "write", "POST", "/api/atelier/pages/{page_id}/append", {
            "properties": {"page_id": ID, "content": {"type": "string", "minLength": 1},
                           "heading": {"type": "string", "maxLength": 200}},
            "required": ["page_id", "content"]}, "header"),
        _action("pages.replace", "destructive", "PUT", "/api/atelier/pages/{page_id}", {
            "properties": {"page_id": ID, "content": {"type": "string"},
                           "title": {"type": "string", "minLength": 1}},
            "required": ["page_id", "content"]}, "natural"),
    ],
    "events": [{"type": "wiki.page.created", "label": "Page créée", "data_schema": {"type": "object"}}],
}  # fmt: skip


def normalize(title: str) -> str:
    """domain/markdown.ts normalizeTitle."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", title) if unicodedata.category(c) != "Mn"
    )
    return " ".join(plain.lower().split())


def slug_keys(questions: list[dict[str, Any]]) -> dict[str, str]:
    """domain/questions.ts columnKeys : clé de colonne tirée du libellé."""
    used, keys = {"id", "recu_le", "repondant", "source"}, {}
    for q in questions:
        if q["type"] == "section":
            continue
        base = re.sub(r"[^a-z0-9]+", "_", normalize(q.get("label") or q["id"])).strip("_")[:40]
        if not re.match(r"[a-z]", base):
            base = f"q_{base}".rstrip("_")
        key, i = base, 2
        while key in used:
            key, i = f"{base}_{i}", i + 1
        used.add(key)
        keys[q["id"]] = key
    return keys


def table(
    name: str, label: str, columns: list[tuple[str, str, str]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "format": "atelier-table/1", "name": name, "label": label,
        "columns": [{"key": k, "label": lbl, "type": t} for k, lbl, t in columns],
        "rows": rows, "total": len(rows), "truncated": False,
    }  # fmt: skip


class FakeWiki:
    """Espaces et pages en mémoire ; Idempotency-Key rejoué comme `runIdempotent`."""

    def __init__(self) -> None:
        self.spaces: list[dict[str, Any]] = [
            {"id": 1, "name": "Général", "slug": "general", "description": "", "icon": ""}
        ]
        self.pages: dict[int, dict[str, Any]] = {
            1: {"id": 1, "title": "Accueil", "content": "Bienvenue. Voir [[Procédures]].",
                "space_id": 1, "parent_id": None, "version": 1},
        }  # fmt: skip
        self.requests: list[httpx.Request] = []
        self.replays: dict[str, tuple[str, int, Any]] = {}
        self.clock = 0  # ordre de modification (pages.list : plus récentes d'abord)

    def page_json(self, page: dict[str, Any]) -> dict[str, Any]:
        space = next(s for s in self.spaces if s["id"] == page["space_id"])
        return {
            "id": str(page["id"]), "title": page["title"], "icon": "", "content": page["content"],
            "space_id": str(page["space_id"]), "space": space["name"],
            "parent_id": None if page["parent_id"] is None else str(page["parent_id"]),
            "version": page["version"], "created_at": "2026-10-20T08:00:00.000Z",
            "created_by": "moi", "updated_at": "2026-10-24T09:00:00.000Z", "updated_by": "Atelier Nexus",
            "path": f"/p/{page['id']}-page", "url": None, "backlinks": [],
        }  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else {}
        key = request.headers.get("idempotency-key")
        print_ = f"{method} {path} {json.dumps(body, sort_keys=True)}"
        if key and key in self.replays:
            fingerprint, status, payload = self.replays[key]
            if fingerprint != print_:  # services/idempotency.ts
                return httpx.Response(
                    409, json={"detail": "Clé déjà utilisée.", "code": "IDEMPOTENCY_KEY_REUSED"}
                )
            return httpx.Response(status, json=payload, headers={"Idempotency-Replayed": "true"})
        status, payload = self.route(method, path, request, body)
        if key and status < 300:
            self.replays[key] = (print_, status, payload)
        return httpx.Response(status, json=payload)

    def touch(self, page: dict[str, Any]) -> None:
        self.clock += 1
        page["updated"] = self.clock

    def live(self) -> list[dict[str, Any]]:
        return [p for p in self.pages.values() if not p.get("deleted")]

    def route(self, method: str, path: str, request: httpx.Request, body: Any) -> tuple[int, Any]:
        if path == "/api/atelier/manifest":
            return 200, WIKI_MANIFEST
        if path == "/api/atelier/spaces":
            rows = [
                {"id": str(s["id"]), "nom": s["name"], "slug": s["slug"], "description": s["description"],
                 "pages": sum(1 for p in self.pages.values() if p["space_id"] == s["id"])}
                for s in self.spaces
            ]  # fmt: skip
            return 200, table("spaces", "Espaces du wiki", [("id", "Id", "string"), ("nom", "Nom", "string"),
                              ("slug", "Identifiant", "string"), ("description", "Description", "string"),
                              ("pages", "Pages", "number")], rows)  # fmt: skip
        if path == "/api/atelier/search" and method == "POST":
            q = body["query"].lower()
            hits = [p for p in self.live() if q in (p["title"] + " " + p["content"]).lower()]
            space_id = body.get("space_id")
            hits = [p for p in hits if not space_id or str(p["space_id"]) == space_id]
            rows = [{"id": str(p["id"]), "titre": p["title"], "espace": "Général", "extrait": p["content"][:80],
                     "maj_le": "2026-10-24T09:00:00.000Z", "chemin": f"/p/{p['id']}", "url": None} for p in hits]  # fmt: skip
            out = table("search", f"Recherche « {body['query']} »", [("id", "Id", "string"), ("titre", "Titre", "string"),
                        ("espace", "Espace", "string"), ("extrait", "Extrait", "string"),
                        ("maj_le", "Modifiée le", "datetime"), ("chemin", "Chemin", "string"),
                        ("url", "Adresse", "string")], rows)  # fmt: skip
            out["total"] = None
            return 200, out
        if path == "/api/atelier/pages" and method == "GET":
            # pagesTable : hors corbeille, filtre d'espace, plus récentes d'abord, limite
            space_id = request.url.params.get("space_id")
            limit = int(request.url.params.get("limit") or 200)
            chosen = [p for p in self.live() if not space_id or str(p["space_id"]) == space_id]
            chosen.sort(key=lambda p: (p.get("updated", 0), p["id"]), reverse=True)
            rows = [{"id": str(p["id"]), "titre": p["title"], "espace_id": str(p["space_id"]), "espace": "Général",
                     "parent_id": None if p["parent_id"] is None else str(p["parent_id"]),
                     "version": p["version"], "maj_le": "2026-10-24T09:00:00.000Z", "maj_par": "moi",
                     "chemin": f"/p/{p['id']}", "url": None} for p in chosen[:limit]]  # fmt: skip
            out = table("pages", "Pages du wiki", [("id", "Id", "string"), ("titre", "Titre", "string"),
                        ("espace", "Espace", "string"), ("version", "Version", "number")], rows)  # fmt: skip
            out["total"], out["truncated"] = len(chosen), len(rows) < len(chosen)
            return 200, out
        if path == "/api/atelier/pages" and method == "POST":
            pid = max(self.pages) + 1
            space_id = int(body.get("space_id") or 1)
            if not any(s["id"] == space_id for s in self.spaces):
                return 404, {"detail": "Espace introuvable.", "code": "NOT_FOUND"}
            self.pages[pid] = {"id": pid, "title": body["title"], "content": body.get("content", ""),
                               "space_id": space_id, "parent_id": int(body["parent_id"]) if body.get("parent_id") else None,
                               "version": 1}  # fmt: skip
            self.touch(self.pages[pid])
            return 201, self.page_json(self.pages[pid])
        m = re.fullmatch(r"/api/atelier/pages/(\d+)(/append)?", path)
        if m:
            page = self.pages.get(int(m[1]))
            if page is None or page.get("deleted"):
                return 404, {"detail": "Page introuvable.", "code": "NOT_FOUND"}
            if method != "GET":
                self.touch(page)
            if method == "GET":
                return 200, self.page_json(page)
            if m[2] and method == "POST":
                # domain/markdown.ts appendSection
                block = (
                    f"## {body['heading'].strip()}\n\n{body['content'].strip()}"
                    if body.get("heading")
                    else body["content"].strip()
                )
                base = page["content"].rstrip()
                page["content"] = f"{base}\n\n{block}\n" if base else f"{block}\n"
                page["version"] += 1
                return 200, self.page_json(page)
            if method == "PUT":
                page["content"] = body["content"]
                page["title"] = body.get("title") or page["title"]
                page["version"] += 1
                return 200, self.page_json(page)
        if path == "/api/spaces" and method == "POST":
            name = " ".join(str(body.get("name") or "").split())
            if not name or len(name) > 80:  # services/spaces.ts cleanName
                return 422, {"detail": "Nom d'espace invalide.", "code": "INPUT_INVALID"}
            if any(normalize(s["name"]) == normalize(name) for s in self.spaces):
                return 409, {"detail": f"Un espace « {name} » existe déjà.", "code": "CONFLICT"}
            sid = max(s["id"] for s in self.spaces) + 1
            self.spaces.append({"id": sid, "name": body["name"], "slug": body["name"].lower(),
                                "description": body.get("description", ""), "icon": body.get("icon", "")})  # fmt: skip
            return 201, {"id": sid, "slug": body["name"].lower(), "name": body["name"], "icon": "",
                         "description": body.get("description", ""), "position": sid, "pageCount": 0,
                         "createdAt": "2026-10-24T09:00:00.000Z", "updatedAt": "2026-10-24T09:00:00.000Z"}  # fmt: skip
        return 404, {"detail": "Route inconnue.", "code": "NOT_FOUND"}


FORM_MANIFEST = {
    "contract": "atelier-node/1", "app": "formulaire", "name": "Atelier Formulaire", "version": "0.3.0",
    "transport": "http",
    "actions": [
        _action("forms.list", "read", "GET", "/api/atelier/forms", {"properties": {}}, "natural"),
        _action("forms.get", "read", "GET", "/api/atelier/forms/{form_id}", {
            "properties": {"form_id": ID}, "required": ["form_id"]}, "natural"),
        _action("responses.list", "read", "GET", "/api/atelier/forms/{form_id}/responses", {
            "properties": {"form_id": ID, "since_id": ID,
                           "limit": {"type": "integer", "minimum": 1, "maximum": 5000}},
            "required": ["form_id"]}, "natural"),
        _action("responses.submit", "write", "POST", "/api/atelier/forms/{form_id}/responses", {
            "properties": {"form_id": ID, "answers": {"type": "object"}},
            "required": ["form_id", "answers"]}, "header"),
    ],
    "events": [{"type": "formulaire.response.submitted", "label": "Réponse reçue", "data_schema": {"type": "object"}}],
}  # fmt: skip

QUESTION_TYPES = {
    "short_text", "long_text", "email", "number", "date", "single", "multiple", "dropdown",
    "scale", "yes_no", "section",
}  # fmt: skip


class FakeFormulaire:
    def __init__(self) -> None:
        self.forms: dict[int, dict[str, Any]] = {
            1: {"id": 1, "title": "Satisfaction atelier", "description": "", "status": "open", "access": "suite",
                "publicToken": None, "version": 1,
                "questions": [
                    {"id": "q1", "type": "scale", "label": "Note globale", "required": True, "min": 1, "max": 5},
                    {"id": "q2", "type": "single", "label": "Reviendrez-vous ?", "options": ["Oui", "Peut-être", "Non"]},
                    {"id": "q3", "type": "email", "label": "Votre e-mail"},
                ]},
        }  # fmt: skip
        self.responses: dict[int, list[dict[str, Any]]] = {
            1: [
                {"id": 1, "respondent": "Alice", "answers": {"q1": 5, "q2": "Oui", "q3": "alice@exemple.fr"}},
                {"id": 2, "respondent": "Bruno", "answers": {"q1": 3, "q2": "Peut-être", "q3": "bruno@exemple.fr"}},
                {"id": 3, "respondent": "Chloé", "answers": {"q1": 4, "q2": "Oui", "q3": "chloe@exemple.fr"}},
                {"id": 4, "respondent": "Damien", "answers": {"q1": 4, "q2": "Non", "q3": "damien@exemple.fr"}},
                {"id": 5, "respondent": "Emma", "answers": {"q1": 2, "q2": "Oui", "q3": "emma@exemple.fr"}},
            ]
        }  # fmt: skip
        self.requests: list[httpx.Request] = []

    def form_json(self, form: dict[str, Any]) -> dict[str, Any]:
        return {
            **form,
            "accepting": form["status"] == "open",
            "responseCount": len(self.responses.get(form["id"], [])),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self.route(request)
        return httpx.Response(status, json=payload)

    def route(self, request: httpx.Request) -> tuple[int, Any]:
        path, method = request.url.path, request.method
        body: Any = json.loads(request.content) if request.content else {}
        if path == "/api/atelier/manifest":
            return 200, FORM_MANIFEST
        if path == "/api/atelier/forms":
            rows = [{"id": str(f["id"]), "titre": f["title"], "statut": {"open": "Ouvert", "draft": "En préparation", "closed": "Fermé"}[f["status"]],
                     "accepte_reponses": f["status"] == "open", "acces": "Suite",
                     "questions": len(f["questions"]), "reponses": len(self.responses.get(f["id"], [])),
                     "derniere_reponse": None, "maj_le": "2026-10-24T09:00:00.000Z"} for f in self.forms.values()]  # fmt: skip
            return 200, table("forms", "Formulaires", [("id", "Id", "string"), ("titre", "Titre", "string"),
                              ("statut", "Statut", "string"), ("reponses", "Réponses", "number")], rows)  # fmt: skip
        m = re.fullmatch(r"/api/atelier/forms/(\d+)(/responses)?", path)
        if m:
            form = self.forms.get(int(m[1]))
            if form is None:
                return 404, {"detail": "Formulaire introuvable.", "code": "NOT_FOUND"}
            questions = [q for q in form["questions"] if q["type"] != "section"]
            if m[2]:
                # services/responses.ts responsesTable : plus anciennes d'abord, since_id, limit
                keys = slug_keys(questions)
                since = int(request.url.params.get("since_id") or 0)
                limit = int(request.url.params.get("limit") or 1000)
                items = [r for r in self.responses.get(form["id"], []) if r["id"] > since]
                rows = [{"id": str(r["id"]), "recu_le": r.get("at", "2026-10-24T09:00:00.000Z"),
                         "repondant": r["respondent"], "source": "suite",
                         **{keys[q["id"]]: _cell(r["answers"].get(q["id"])) for q in questions}}
                        for r in items[:limit]]  # fmt: skip
                cols = [("id", "Réponse", "string"), ("recu_le", "Reçue le", "datetime"),
                        ("repondant", "Répondant", "string"), ("source", "Origine", "string")] + [
                    (keys[q["id"]], q["label"], "string") for q in questions
                ]  # fmt: skip
                out = table(f"form-{form['id']}", form["title"], cols, rows)
                out["total"], out["truncated"] = len(items), len(rows) < len(items)
                return 200, out
            reduced = [
                {k: q[k] for k in ("id", "type", "label", "options", "min", "max") if k in q}
                | {"required": bool(q.get("required"))}
                for q in questions
            ]
            return 200, {
                "id": str(form["id"]), "title": form["title"], "description": form["description"],
                "status": form["status"], "accepting": form["status"] == "open",
                "response_count": len(self.responses.get(form["id"], [])),
                "questions": reduced,
            }  # fmt: skip
        m = re.fullmatch(r"/api/forms/(\d+)/(summary|status|access)", path)
        if m:
            form = self.forms.get(int(m[1]))
            if form is None:
                return 404, {"detail": "Formulaire introuvable.", "code": "NOT_FOUND"}
            if m[2] == "summary":
                items = self.responses.get(form["id"], [])
                questions = [
                    _summarize(q, [r["answers"].get(q["id"]) for r in items])
                    for q in form["questions"]
                    if q["type"] != "section"
                ]
                return 200, {"total": len(items), "questions": questions}
            if m[2] == "status":
                form["status"] = body["status"]
            else:
                form["access"] = body["access"]
                form["publicToken"] = "jeton-public" if body["access"] == "public" else None
            return 200, self.form_json(form)
        if path == "/api/forms" and method == "POST":
            ids = set()
            for n, q in enumerate(body.get("questions", []), start=1):
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(q.get("id", ""))) or q["id"] in ids:
                    return 422, {
                        "detail": f"Question {n} : identifiant invalide.",
                        "code": "INPUT_INVALID",
                    }
                if q.get("type") not in QUESTION_TYPES:
                    return 422, {"detail": f"Question {n} : type inconnu.", "code": "INPUT_INVALID"}
                ids.add(q["id"])
            fid = max(self.forms) + 1
            self.forms[fid] = {"id": fid, "title": body["title"], "description": body.get("description", ""),
                               "status": "draft", "access": "suite", "publicToken": None, "version": 1,
                               "questions": body.get("questions", [])}  # fmt: skip
            return 201, self.form_json(self.forms[fid])
        return 404, {"detail": "Route inconnue.", "code": "NOT_FOUND"}


def _cell(value: Any) -> Any:
    return ", ".join(value) if isinstance(value, list) else value


def _summarize(q: dict[str, Any], raw: list[Any]) -> dict[str, Any]:
    """domain/questions.ts summarize."""
    values = [v for v in raw if v not in (None, "", [])]
    base = {"id": q["id"], "type": q["type"], "label": q["label"], "answered": len(values)}
    if q["type"] in ("single", "multiple", "dropdown", "yes_no"):
        options = ["Oui", "Non"] if q["type"] == "yes_no" else q.get("options", [])
        counts = dict.fromkeys(options, 0)
        for v in values:
            for item in (
                v
                if isinstance(v, list)
                else [("Oui" if v else "Non") if isinstance(v, bool) else str(v)]
            ):
                counts[item] = counts.get(item, 0) + 1
        return {
            **base,
            "kind": "choices",
            "counts": [{"option": o, "count": c} for o, c in counts.items()],
        }
    if q["type"] in ("number", "scale"):
        nums = [v for v in values if isinstance(v, (int, float))]
        out = {**base, "kind": "numbers", "min": min(nums) if nums else None,
               "max": max(nums) if nums else None,
               "average": round(sum(nums) / len(nums), 2) if nums else None}  # fmt: skip
        if q["type"] == "scale":
            out["distribution"] = [
                {"value": v, "count": nums.count(v)}
                for v in range(q.get("min", 1), q.get("max", 5) + 1)
            ]
        return out
    return {**base, "kind": "texts", "latest": [str(v) for v in reversed(values)][:5]}
