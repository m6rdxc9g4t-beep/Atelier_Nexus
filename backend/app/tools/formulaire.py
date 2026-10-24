"""Connecteur Atelier Formulaire (contrat `atelier-node/1`, API sur 3300).

Routes appelées, lues dans le dépôt `Atelier_Formulaire` :
- actions du manifeste (`backend/src/services/atelier-manifest.ts`, `routes/atelier.ts`) :
  `forms.list` (GET /api/atelier/forms), `forms.get` (GET /api/atelier/forms/{form_id}),
  `responses.list` (GET /api/atelier/forms/{form_id}/responses) ;
- hors manifeste (`routes/forms.ts`) : GET /api/forms/{id}/summary (synthèse par question),
  POST /api/forms (création : {title, description, questions}), POST /api/forms/{id}/status
  ({status: draft | open | closed}), POST /api/forms/{id}/access ({access: suite | public}).

Confidentialité : les réponses (nom du répondant, e-mails, textes libres) sont des données
personnelles. `formulaire_responses` est `sensitive` (boîte `formulaire_reponses`) : l'agent qui
l'utilise tourne uniquement sur le modèle local. La synthèse ne garde que des agrégats (effectifs
par choix, minimum, moyenne, maximum) : les textes libres des réponses n'en sortent jamais.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.environment import ToolEnvironment
from app.tools.formatting import markdown_table
from app.tools.suite_node import NodeTool, NoInput, as_data, rows_of, table_output

QuestionType = Literal[
    "short_text", "long_text", "email", "number", "date", "single", "multiple", "dropdown",
    "scale", "yes_no", "section",
]  # fmt: skip
STATUS_LABELS = {"draft": "en préparation", "open": "ouvert", "closed": "fermé"}


class _FormTool[InputT: ToolInput](NodeTool[InputT]):
    app = "formulaire"


# ─── Lecture ──────────────────────────────────────────────────────


class FormsTool(_FormTool[NoInput]):
    name = "formulaire_forms"
    description = (
        "Formulaires d'Atelier Formulaire : statut, accès, nombre de questions et de réponses."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        return table_output(self.app, await self.action("forms.list", {}), noun="formulaire")


class FormInput(ToolInput):
    form_id: str = Field(
        description="Identifiant du formulaire (formulaire_forms).",
        pattern=r"^[0-9]+$",
        max_length=12,
    )


class FormTool(_FormTool[FormInput]):
    name = "formulaire_form"
    description = "Questions d'un formulaire (identifiants, types, choix proposés, bornes)."
    input_model = FormInput

    async def run(self, params: FormInput, ctx: ToolContext) -> ToolOutput:
        form = await self.action("forms.get", {"form_id": params.form_id})
        rows = [
            [
                q.get("id"),
                q.get("type"),
                q.get("label"),
                "oui" if q.get("required") else "non",
                ", ".join(map(str, q.get("options") or [])) or _bounds(q),
            ]
            for q in form.get("questions") or []
        ]
        lines = [
            f"Formulaire {form.get('id')} : "
            f"{STATUS_LABELS.get(str(form.get('status')), form.get('status'))}, "
            f"{'accepte' if form.get('accepting') else "n'accepte pas"} de réponses, "
            f"{form.get('response_count')} réponse(s).",
        ]
        text = [f"Titre : {form.get('title')}"]
        if form.get("description"):
            text.append(f"Description : {str(form['description'])[:2000]}")
        text.append(
            markdown_table(["Id", "Type", "Question", "Obligatoire", "Choix / bornes"], rows)
        )
        lines.append(as_data("\n".join(text), kind="formulaire", limit=30_000))
        return ToolOutput(content="\n".join(lines), data=form)


def _bounds(q: dict[str, Any]) -> str:
    if "min" in q or "max" in q:
        return f"{q.get('min', '…')} à {q.get('max', '…')}"
    return ""


class SummaryTool(_FormTool[FormInput]):
    name = "formulaire_summary"
    description = (
        "Synthèse AGRÉGÉE des réponses d'un formulaire : effectifs par choix, moyenne / min / max "
        "des nombres et échelles. Sans aucune réponse individuelle ni texte libre."
    )
    input_model = FormInput

    async def run(self, params: FormInput, ctx: ToolContext) -> ToolOutput:
        summary = await self.http("GET", f"/api/forms/{params.form_id}/summary")
        return ToolOutput(content=summary_text(summary), data=aggregate_only(summary))


#: En dessous de ce nombre de réponses, le détail d'une question n'est pas montré : avec une ou
#: deux personnes, un minimum, un maximum ou un effectif par choix désigne quelqu'un. Les nombres
#: et échelles ont un seuil plus haut : moyenne + minimum + maximum + distribution permettent de
#: reconstituer chaque valeur d'un petit groupe.
MIN_GROUP = 3
MIN_GROUP_NUMBERS = 5


def aggregate_only(summary: dict[str, Any]) -> dict[str, Any]:
    """Synthèse sans texte libre (données personnelles possibles) et sans détail d'une question
    à laquelle moins de `MIN_GROUP` personnes ont répondu."""
    questions = []
    for q in summary.get("questions") or []:
        if not isinstance(q, dict):
            continue
        item = {k: v for k, v in q.items() if k != "latest"}
        floor = MIN_GROUP_NUMBERS if item.get("kind") == "numbers" else MIN_GROUP
        if (item.get("answered") or 0) < floor:
            item = {k: item.get(k) for k in ("id", "label", "type", "kind", "answered")}
            item["masked"] = floor
        questions.append(item)
    return {"total": summary.get("total"), "questions": questions}


def _num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def summary_markdown(summary: dict[str, Any]) -> str:
    """Synthèse agrégée en Markdown (texte brut, à délimiter avant de l'envoyer au modèle)."""
    data = aggregate_only(summary)
    total = data.get("total") or 0
    lines = [f"{total} réponse(s) au total."]
    for q in data["questions"]:
        label = str(q.get("label") or q.get("id"))[:200]
        answered = q.get("answered") or 0
        head = f"\n**{label}** ({answered} réponse(s))"
        kind = q.get("kind")
        if q.get("masked"):
            detail = "aucune réponse" if not answered else f"moins de {q['masked']} réponses"
            lines.append(f"{head} : {detail}, détail non montré.")
        elif kind == "choices":
            counts = q.get("counts") or []
            rows = [
                [
                    c.get("option"),
                    c.get("count"),
                    f"{100 * (c.get('count') or 0) / answered:.0f} %",
                ]
                for c in counts
                if isinstance(c, dict)
            ]
            lines += [head, markdown_table(["Choix", "Effectif", "Part"], rows)]
        elif kind == "numbers":
            lines.append(
                f"{head} : moyenne {_num(q.get('average'))}, minimum {_num(q.get('min'))}, "
                f"maximum {_num(q.get('max'))}."
            )
            dist = q.get("distribution")
            if dist:
                lines.append(
                    markdown_table(
                        ["Note", "Effectif"],
                        [[d.get("value"), d.get("count")] for d in dist if isinstance(d, dict)],
                    )
                )
        else:
            lines.append(
                f"{head} : réponses libres, non reprises dans la synthèse (données personnelles possibles)."
            )
    return "\n".join(lines)


def summary_text(summary: dict[str, Any]) -> str:
    return as_data(summary_markdown(summary), kind="synthèse du formulaire", limit=20_000)


# ─── Réponses individuelles (sensible) ────────────────────────────


class ResponsesInput(ToolInput):
    form_id: str = Field(
        description="Identifiant du formulaire.", pattern=r"^[0-9]+$", max_length=12
    )
    nombre: int = Field(
        default=20, ge=1, le=100, description="Nombre de réponses à lire (les plus récentes)."
    )
    avant_id: str | None = Field(
        default=None,
        description="Lire les réponses arrivées AVANT celle-ci (pour remonter dans le temps).",
        pattern=r"^[0-9]+$",
        max_length=12,
    )


#: Taille maximale d'une réponse libre montrée, et de l'ensemble montré au modèle
ANSWER_CHARS = 2_000
RESPONSES_CHARS = 40_000
FETCH_LIMIT = 5_000  # maximum de `responses.list` (manifeste de Formulaire)


class ResponsesTool(_FormTool[ResponsesInput]):
    name = "formulaire_responses"
    description = (
        "Réponses individuelles d'un formulaire, les plus récentes d'abord, chaque réponse en "
        "entier (répondant, date, réponse à chaque question). Données personnelles : modèle local "
        "uniquement."
    )
    input_model = ResponsesInput
    sensitive = True

    async def run(self, params: ResponsesInput, ctx: ToolContext) -> ToolOutput:
        rows, data, total = await self._latest(params)
        if params.avant_id:
            rows = [r for r in rows if _int(r.get("id")) < int(params.avant_id)]
        if not rows:
            empty = (
                f"Aucune réponse avant la réponse {params.avant_id}."
                if params.avant_id
                else "Aucune réponse pour l'instant."
            )
            return ToolOutput(content=empty, data=data)
        columns = [c for c in data["columns"] if isinstance(c, dict) and "key" in c]
        # On ne montre que ce qui tient dans le budget : l'en-tête et `avant_id` portent sur ce
        # qui est réellement affiché (jamais une réponse coupée sans moyen d'y revenir)
        blocks: list[str] = []
        shown: list[dict[str, Any]] = []
        used = 0
        for row in reversed(rows[-params.nombre :]):
            block = _response_block(row, columns)
            if blocks and used + len(block) > RESPONSES_CHARS:
                break
            blocks.append(block)
            shown.append(row)
            used += len(block) + 2
        older = len(rows) - len(shown)
        head = (
            f"{len(shown)} réponse(s), de la plus récente à la plus ancienne"
            + (f" (sur {total})" if isinstance(total, int) else "")
            + (
                f" ; {older} plus ancienne(s) : rappeler avec avant_id={shown[-1].get('id')}"
                if older
                else ""
            )
            + "."
        )
        return ToolOutput(
            content=head
            + "\n"
            + as_data(
                "\n\n".join(blocks), kind="réponses au formulaire", limit=RESPONSES_CHARS + 1000
            ),
            data=data,
        )

    async def _latest(
        self, params: ResponsesInput
    ) -> tuple[list[dict[str, Any]], dict[str, Any], Any]:
        """Les dernières réponses : la route les rend de la plus ancienne à la plus récente, par
        pages de 5 000 au plus (`since_id`). On avance jusqu'à la fin et on garde la fenêtre
        utile (les 5 000 dernières, ou celles d'avant `avant_id`)."""
        since: str | None = None
        window: list[dict[str, Any]] = []
        data: dict[str, Any] = {}
        total: Any = None
        for _ in range(MAX_PAGES):
            payload: dict[str, Any] = {"form_id": params.form_id, "limit": FETCH_LIMIT}
            if since:
                payload["since_id"] = since
            data = await self.action("responses.list", payload)
            if total is None:
                total = data.get("total")  # première page (since_id absent) : total du formulaire
            page = rows_of(self.app, data)
            if params.avant_id:
                page = [r for r in page if _int(r.get("id")) < int(params.avant_id)]
            window = (window + page)[-FETCH_LIMIT:]
            last = rows_of(self.app, data)
            if not data.get("truncated") or not last:
                break
            since = str(last[-1].get("id"))
            if params.avant_id and _int(since) >= int(params.avant_id):
                break
        return window, data, total


MAX_PAGES = 20  # 100 000 réponses au plus


def _int(value: Any) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def _response_block(row: dict[str, Any], columns: list[dict[str, Any]]) -> str:
    meta = {"id", "recu_le", "repondant", "source"}
    lines = [
        f"### Réponse {row.get('id')} — {row.get('recu_le') or '?'} — "
        f"{row.get('repondant') or 'anonyme'} ({row.get('source') or '?'})"
    ]
    for c in columns:
        if c["key"] in meta:
            continue
        value = row.get(c["key"])
        if value is None or value == "":
            continue
        text = str(value)
        if len(text) > ANSWER_CHARS:
            text = text[:ANSWER_CHARS] + f" [… {len(text) - ANSWER_CHARS} caractères de plus]"
        lines.append(f"- {c.get('label') or c['key']} : {text}")
    return "\n".join(lines)


# ─── Écriture (validation) ────────────────────────────────────────


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: QuestionType = Field(
        description=(
            "short_text, long_text, email, number, date, single (un choix), multiple (cases), "
            "dropdown, scale (échelle), yes_no, section (titre de partie)."
        )
    )
    label: str = Field(min_length=1, max_length=300, description="Intitulé de la question.")
    required: bool = Field(default=False, description="Réponse obligatoire.")
    help: str | None = Field(
        default=None, max_length=600, description="Aide affichée sous la question."
    )
    options: list[str] | None = Field(
        default=None, max_length=50, description="Choix proposés (single, multiple, dropdown)."
    )
    min: float | None = Field(default=None, description="Borne basse (number ; scale : 0 ou 1).")
    max: float | None = Field(
        default=None, description="Borne haute (number ; scale : jusqu'à 10)."
    )
    min_label: str | None = Field(
        default=None, max_length=100, description="Libellé du bas de l'échelle."
    )
    max_label: str | None = Field(
        default=None, max_length=100, description="Libellé du haut de l'échelle."
    )


class CreateFormInput(ToolInput):
    title: str = Field(min_length=1, max_length=200, description="Titre du formulaire.")
    description: str = Field(default="", max_length=4000, description="Texte d'introduction.")
    questions: list[QuestionInput] = Field(
        min_length=1, max_length=100, description="Questions, dans l'ordre."
    )


def to_questions(items: list[QuestionInput]) -> list[dict[str, Any]]:
    out = []
    for n, q in enumerate(items, start=1):
        item: dict[str, Any] = {"id": f"q{n}", "type": q.type, "label": q.label}
        if q.required and q.type != "section":
            item["required"] = True
        for key, value in (
            ("help", q.help), ("options", q.options), ("min", q.min), ("max", q.max),
            ("minLabel", q.min_label), ("maxLabel", q.max_label),
        ):  # fmt: skip
            if value is not None:
                item[key] = value
        out.append(item)
    return out


class CreateFormTool(_FormTool[CreateFormInput]):
    name = "formulaire_create_form"
    description = (
        "Crée un formulaire (en préparation) dans Atelier Formulaire : sondage, inscription, "
        "retours. Il n'accepte des réponses qu'une fois ouvert (formulaire_set_status)."
    )
    input_model = CreateFormInput
    requires_approval = True

    def approval_summary(self, params: CreateFormInput) -> str:
        labels = ", ".join(f"« {q.label[:40]} »" for q in params.questions[:4])
        more = f" (+{len(params.questions) - 4})" if len(params.questions) > 4 else ""
        return (
            f"Créer le formulaire « {params.title} » dans Atelier Formulaire, "
            f"{len(params.questions)} question(s) : {labels}{more}"
        )

    async def run(self, params: CreateFormInput, ctx: ToolContext) -> ToolOutput:
        body = {
            "title": params.title,
            "description": params.description,
            "questions": to_questions(params.questions),
        }
        form = await self.http("POST", "/api/forms", body)
        return ToolOutput(
            content=(
                f"Formulaire « {form.get('title')} » créé (id {form.get('id')}), en préparation : "
                "l'ouvrir aux réponses avec formulaire_set_status quand l'utilisateur l'a relu."
            ),
            data={"id": str(form.get("id")), "title": form.get("title")},
        )


class StatusInput(ToolInput):
    form_id: str = Field(
        description="Identifiant du formulaire.", pattern=r"^[0-9]+$", max_length=12
    )
    status: Literal["open", "closed", "draft"] = Field(
        description="open = ouvert aux réponses, closed = fermé, draft = en préparation."
    )


class StatusTool(_FormTool[StatusInput]):
    name = "formulaire_set_status"
    description = "Ouvre un formulaire aux réponses, le ferme, ou le remet en préparation."
    input_model = StatusInput
    requires_approval = True

    def approval_summary(self, params: StatusInput) -> str:
        verb = {
            "open": "Ouvrir aux réponses",
            "closed": "Fermer",
            "draft": "Remettre en préparation",
        }
        return f"{verb[params.status]} le formulaire {params.form_id} d'Atelier Formulaire"

    async def run(self, params: StatusInput, ctx: ToolContext) -> ToolOutput:
        form = await self.http(
            "POST", f"/api/forms/{params.form_id}/status", {"status": params.status}
        )
        return ToolOutput(
            content=f"Formulaire {form.get('id')} : {STATUS_LABELS.get(params.status)}.",
            data={"id": str(form.get("id")), "status": form.get("status")},
        )


class AccessInput(ToolInput):
    form_id: str = Field(
        description="Identifiant du formulaire.", pattern=r"^[0-9]+$", max_length=12
    )
    access: Literal["suite", "public"] = Field(
        description="suite = personnes connectées à la suite ; public = toute personne qui a le lien."
    )


class AccessTool(_FormTool[AccessInput]):
    name = "formulaire_set_access"
    description = (
        "Choisit qui peut répondre : les personnes connectées à la suite, ou toute personne qui a "
        "le lien public (personnes extérieures)."
    )
    input_model = AccessInput
    requires_approval = True

    def approval_summary(self, params: AccessInput) -> str:
        who = (
            "TOUTE personne qui a le lien"
            if params.access == "public"
            else "les personnes connectées à la suite"
        )
        return f"Ouvrir le formulaire {params.form_id} à {who}"

    async def run(self, params: AccessInput, ctx: ToolContext) -> ToolOutput:
        form = await self.http(
            "POST", f"/api/forms/{params.form_id}/access", {"access": params.access}
        )
        token = form.get("publicToken")
        link = (
            f" Lien de réponse : /r/{token} (à préfixer par l'adresse publique de Formulaire)."
            if token and params.access == "public"
            else ""
        )
        return ToolOutput(
            content=f"Accès du formulaire {form.get('id')} : {params.access}.{link}",
            data={"id": str(form.get("id")), "access": form.get("access")},
        )


def formulaire_read_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [FormsTool(env), FormTool(env), SummaryTool(env)]


def formulaire_write_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [CreateFormTool(env), StatusTool(env), AccessTool(env)]


def formulaire_responses_tools(env: ToolEnvironment) -> list[BaseTool[Any]]:
    return [ResponsesTool(env)]
