"""Connecteur Atelier Trésorerie — lecture seule, données SENSIBLES.

Règle d'Atelier Trésorerie : « aucune donnée financière ne doit quitter la machine ».
Tous ces outils sont `sensitive` : un agent qui les utilise est verrouillé sur un
modèle local (Ollama), sans repli vers Claude, et ne peut pas être appelé par un
orchestrateur qui tourne sur Claude (voir app/agents/base.py et delegation.py).

Convention de signe (la même dans tous les outils, docs/apps/tresorerie.md) : le montant d'une
opération est signé (négatif = dépense, positif = revenu) ; un total de dépenses est écrit en
valeur positive, toujours avec le mot « dépenses » ; une évolution est dite en clair (« en
hausse de 5.3 % »).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Annotated, Any, Literal

import httpx
from pydantic import BeforeValidator, Field, model_validator

from app.core.config import Settings
from app.schemas.tresorerie import (
    AccountList,
    BudgetMonth,
    CategoryList,
    Dashboard,
    GoalList,
    HoldingList,
    Ping,
    Transaction,
    TransactionPage,
    TxStatus,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import (
    TableType,
    atelier_table,
    data_artifact,
    euros,
    fmt,
    markdown_table,
    table_for_model,
    table_hint,
)
from app.tools.http import AppClient, AppError, AppNotFoundError, AppRequestError

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
DAY = r"^\d{4}-\d{2}-\d{2}$"
#: Plafond de Trésorerie pour `per_page` (services/transactions.py : MAX_PER_PAGE)
MAX_PER_PAGE = 200
#: Pages lues au plus pour un total par catégorie (10 000 opérations)
MAX_PAGES = 50


class TresorerieClient(AppClient):
    app = "tresorerie"
    label = "Atelier Trésorerie"
    error_keys = ("error", "message")

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> TresorerieClient | None:
        if not settings.tresorerie_base_url:
            return None
        return cls(settings.tresorerie_base_url, timeout=settings.apps_timeout, transport=transport)

    def _unavailable_hint(self) -> str:
        return (
            "lancez-le (app Mac Atelier Trésorerie, ou `python app.py` dans son dossier ; port "
            "5050 par défaut), puis réessayez."
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return await super().request(method, path, **kwargs)
        except AppNotFoundError:
            # Les routes lues ici existent toujours chez Trésorerie : un 404 signale plutôt un
            # autre service sur le port (Atelier Savoir écoute aussi sur 5050 par défaut)
            if path != "ping":
                await self._check_identity()
            raise

    async def _check_identity(self) -> None:
        try:
            await self.ping()
        except (AppNotFoundError, AppRequestError) as exc:
            raise AppRequestError(
                f"Le service sur {self.base_url} ne répond pas comme Atelier Trésorerie : Atelier "
                "Savoir occupe peut-être le port 5050 (lancez Savoir avec ATELIER_PORT=5051), ou "
                "TRESORERIE_BASE_URL désigne une autre application.",
                app=self.app,
            ) from exc

    async def ping(self) -> Ping:
        ping = self.parse(Ping, await self.request("GET", "ping"))
        if ping.app != "atelier-tresorerie":
            raise AppRequestError(
                f"Le service sur {self.base_url} n'est pas Atelier Trésorerie ({ping.app}).",
                app=self.app,
            )
        return ping

    async def dashboard(self, months: int = 6) -> Dashboard:
        return self.parse(
            Dashboard, await self.request("GET", "dashboard", params={"months": months})
        )

    async def accounts(self, include_archived: bool = False) -> AccountList:
        params = {"archived": "1"} if include_archived else None
        return self.parse(AccountList, await self.request("GET", "accounts", params=params))

    async def categories(self) -> CategoryList:
        return self.parse(CategoryList, await self.request("GET", "categories"))

    async def transactions(self, **filters: str | int) -> TransactionPage:
        return self.parse(
            TransactionPage, await self.request("GET", "transactions", params=filters)
        )

    async def budgets(self, month: str | None = None) -> BudgetMonth:
        params = {"month": month} if month else None
        return self.parse(BudgetMonth, await self.request("GET", "budgets", params=params))

    async def goals(self) -> GoalList:
        return self.parse(GoalList, await self.request("GET", "goals"))

    async def holdings(self) -> HoldingList:
        return self.parse(HoldingList, await self.request("GET", "holdings"))


# ─── Mise en forme (fonctions pures, testées) ─────────────────────


def pct(value: float | None) -> str:
    return "∅" if value is None else f"{value:+.1f} %"


def trend(value: float | None) -> str:
    """Évolution en clair : « en hausse de 7.5 % », « en baisse de 5.3 % », « stable »."""
    if value is None:
        return "sans comparaison possible"
    if abs(value) < 0.05:
        return "stable"
    return f"en {'hausse' if value > 0 else 'baisse'} de {abs(value):.1f} %"


def signed(cents: int | None) -> str:
    """Variation en centimes → « +1531.67 € » (le signe est le sens de la variation)."""
    return "∅" if cents is None else f"{cents / 100:+.2f} €"


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


#: Types d'opération en français (vus dans tresorerie_categories) → valeurs de l'API
TYPE_ALIASES = {
    "revenu": "income",
    "revenus": "income",
    "recette": "income",
    "recettes": "income",
    "depense": "expense",
    "depenses": "expense",
    "transfert": "transfer",
    "transferts": "transfer",
    "virement": "transfer",
    "virements": "transfer",
}
TYPE_LABELS = {"income": "revenus", "expense": "dépenses", "transfer": "virements internes"}
STATUS_LABELS = {"valide": "validées", "en_attente": "en attente", "rapproche": "rapprochées"}


def _tx_type(value: object) -> object:
    """« Dépenses », « EXPENSE », « virement » → valeur de l'API ; le reste est laissé au refus."""
    if not isinstance(value, str):
        return value
    plain = _plain(value)
    return TYPE_ALIASES.get(plain, plain if plain in TYPE_LABELS else value)


TxType = Annotated[Literal["income", "expense", "transfer"], BeforeValidator(_tx_type)]
FlowType = Annotated[Literal["income", "expense"], BeforeValidator(_tx_type)]


def period_label(month: str | None, start: str | None, end: str | None) -> str:
    if month:
        return month
    if start and end:
        return f"du {start} au {end}"
    if start:
        return f"depuis le {start}"
    if end:
        return f"jusqu'au {end}"
    return "toute la période"


def months_between(start: str, end: str, *, cap: int = 13) -> list[str]:
    """Mois AAAA-MM de `start` à `end` inclus, `cap` au plus (un mois sans opération garde sa
    colonne dans un récapitulatif mois par mois)."""
    y, m = int(start[:4]), int(start[5:7])
    last = (int(end[:4]), int(end[5:7]))
    out: list[str] = []
    while (y, m) <= last and len(out) < cap:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def unset_blanks(data: object) -> object:
    """Champ envoyé vide (« "" » : un petit modèle remplit souvent tous les champs) = champ non
    renseigné, avec sa valeur par défaut, plutôt qu'un refus (motif AAAA-MM, choix…)."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
    return data


def _check_period(month: str | None, start: str | None, end: str | None) -> None:
    if month and (start or end):
        raise ValueError("Indique month (un mois) OU start / end (une période), pas les deux.")
    if start and end and start > end:
        raise ValueError("start doit précéder end.")


class _TresoTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)
    sensitive = True

    def __init__(self, client: TresorerieClient) -> None:
        self.client = client


class DashboardInput(ToolInput):
    months: int = Field(default=6, ge=2, le=24, description="Historique, en mois (2 à 24).")


class DashboardTool(_TresoTool[DashboardInput]):
    name = "tresorerie_dashboard"
    description = (
        "Synthèse financière : patrimoine net, revenus, dépenses et taux d'épargne du mois "
        "(comparés au mois précédent à date), historique mensuel et dépenses par catégorie "
        "du mois en cours."
    )
    input_model = DashboardInput

    async def run(self, params: DashboardInput, ctx: ToolContext) -> ToolOutput:
        d = await self.client.dashboard(params.months)
        k = d.kpis
        lines = [
            f"Au {d.today} (mois {d.month}) ; évolutions comparées au {d.comparison_day} "
            f"{d.previous_month_label}, à date. Dépenses écrites en valeur positive.",
            f"- Patrimoine net : {euros(k.net_worth_cents)} ({trend(k.net_worth_change_percent)},"
            f" soit {signed(k.net_worth_change_cents)}), dont placements {euros(k.investments_cents)}.",
            f"- Revenus du mois : {euros(k.income_cents)} ({trend(k.income_change_percent)}).",
            f"- Dépenses du mois : {euros(abs(k.expense_cents))} ({trend(k.expense_change_percent)}).",
            f"- Taux d'épargne : {fmt(k.savings_rate)} %.",
            "",
            "Historique :",
        ]
        lines += [
            f"- {h.label} : patrimoine {euros(h.total_cents)}, revenus {euros(h.income_cents)}, "
            f"dépenses {euros(abs(h.expense_cents))}{' (mois en cours)' if h.partial else ''}"
            for h in d.history
        ]
        lines += ["", f"Dépenses par catégorie ({d.categories.month}) :"]
        lines += [
            f"- {c.name} : {euros(abs(c.amount_cents))} ({c.percent:g} %)"
            for c in d.categories.items
        ]
        return ToolOutput(content="\n".join(lines))


class AccountsInput(ToolInput):
    include_archived: bool = Field(default=False, description="Inclure les comptes archivés.")


class AccountsTool(_TresoTool[AccountsInput]):
    name = "tresorerie_accounts"
    description = (
        "Comptes (avec leur identifiant) : type, établissement, solde, valeur des placements, "
        "valeur totale. Un solde négatif est un découvert ou un crédit."
    )
    input_model = AccountsInput

    async def run(self, params: AccountsInput, ctx: ToolContext) -> ToolOutput:
        data = await self.client.accounts(params.include_archived)
        rows = [
            [
                a.id,
                a.name,
                a.type_label,
                a.institution,
                a.balance_cents / 100,
                a.holdings_value_cents / 100,
                a.total_value_cents / 100,
                a.last_transaction_date,
            ]  # fmt: skip
            for a in data.items
        ]
        text, _ = table_for_model(
            ["id", "compte", "type", "établissement", "solde €", "placements €", "total €",
             "dernière opération"], rows, noun="compte",
        )  # fmt: skip
        return ToolOutput(
            content=f"Total (hors archivés) : {euros(data.total_balance_cents)}.\n{text}"
        )


class TransactionsInput(ToolInput):
    account_id: int | None = Field(
        default=None,
        gt=0,
        description="Un seul compte : identifiant donné par tresorerie_accounts.",
    )
    category_id: int | None = Field(
        default=None,
        gt=0,
        description="Une seule catégorie : identifiant donné par tresorerie_categories.",
    )
    uncategorized: bool = Field(
        default=False, description="true = seulement les opérations sans catégorie."
    )
    month: str | None = Field(
        default=None,
        pattern=MONTH,
        description="Un mois AAAA-MM. Pour une autre période, start / end à la place (pas les deux).",
    )
    start: str | None = Field(
        default=None, pattern=DAY, description="Premier jour inclus, AAAA-MM-JJ."
    )
    end: str | None = Field(
        default=None, pattern=DAY, description="Dernier jour inclus, AAAA-MM-JJ."
    )
    type: TxType | None = Field(
        default=None,
        description="income = revenus, expense = dépenses, transfer = virements internes "
        "(ni revenu ni dépense).",
    )
    status: TxStatus | None = Field(
        default=None,
        description="valide, en_attente (pas encore passée) ou rapproche (pointée sur le relevé).",
    )
    query: str | None = Field(
        default=None, max_length=100, description="Mot cherché dans le libellé ou les notes."
    )
    sort: Literal["date", "amount", "label"] = Field(
        default="date", description="Tri : date, amount (montant) ou label (libellé)."
    )
    order: Literal["asc", "desc"] = Field(
        default="desc", description="desc = plus récent ou plus grand d'abord ; asc = l'inverse."
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=MAX_PER_PAGE,
        description="Opérations renvoyées (1 à 200 ; 50 montrées dans la réponse). Les totaux "
        "portent toujours sur tout le filtre.",
    )

    @model_validator(mode="before")
    @classmethod
    def _blanks(cls, data: object) -> object:
        return unset_blanks(data)

    @model_validator(mode="after")
    def _period(self) -> TransactionsInput:
        _check_period(self.month, self.start, self.end)
        return self


class TransactionsTool(_TresoTool[TransactionsInput]):
    name = "tresorerie_transactions"
    description = (
        "Opérations filtrées (compte, catégorie, mois ou période, revenu / dépense / virement, "
        "statut, texte) avec totaux revenus / dépenses / net sur TOUT le filtre. Pour des "
        "totaux par catégorie, tresorerie_category_totals."
    )
    input_model = TransactionsInput

    async def run(self, params: TransactionsInput, ctx: ToolContext) -> ToolOutput:
        filters: dict[str, str | int] = {
            "per_page": params.limit,
            "sort": params.sort,
            "order": params.order,
        }
        if params.account_id:
            filters["account_id"] = params.account_id
        if params.uncategorized:
            filters["category_id"] = "none"
        elif params.category_id:
            filters["category_id"] = params.category_id
        for key in ("month", "start", "end", "type", "status"):
            value = getattr(params, key)
            if value:
                filters[key] = value
        if params.query:
            filters["q"] = params.query
        page = await self.client.transactions(**filters)
        rows = [
            [t.date, t.label, t.amount_cents / 100, t.category_name, t.account_name, t.status]
            for t in page.items
        ]
        headers = ["date", "libellé", "montant €", "catégorie", "compte", "statut"]
        text, truncated = table_for_model(headers, rows, noun="opération")
        summary = (
            f"{page.total} opération(s) sur ce filtre ({len(page.items)} renvoyées). Sur tout le "
            f"filtre : revenus {euros(page.income_cents)}, dépenses "
            f"{euros(abs(page.expense_cents))}, net {euros(page.net_cents)} (toutes les "
            "opérations, virements internes compris). Colonne « montant € » : négatif = dépense, "
            "positif = revenu."
        )
        # Panneau des artefacts : seulement si la réponse ne montre pas tout (comme Ciné)
        artifacts = []
        if truncated or page.total > len(page.items):
            title = "Opérations — " + self._filter_label(params, page.items)
            if page.total > len(rows):
                title += f" ({len(rows)} sur {page.total})"
            artifacts.append(
                data_artifact(
                    title, headers, rows, numeric={"montant €"}, metadata={"source": "tresorerie"}
                )
            )
        return ToolOutput(content=f"{summary}\n{text}", artifacts=artifacts)

    @staticmethod
    def _filter_label(params: TransactionsInput, items: list[Transaction]) -> str:
        parts = [period_label(params.month, params.start, params.end)]
        if params.type:
            parts.append(TYPE_LABELS[params.type])
        if params.uncategorized:
            parts.append("non catégorisées")
        elif params.category_id:
            parts.append((items[0].category_name or "catégorie") if items else "catégorie")
        if params.account_id:
            parts.append(items[0].account_name if items else f"compte #{params.account_id}")
        if params.status:
            parts.append(STATUS_LABELS[params.status])
        if params.query:
            parts.append(f"« {params.query} »")
        return ", ".join(parts)


class CategoryTotalsInput(ToolInput):
    month: str | None = Field(
        default=None,
        pattern=MONTH,
        description="Un mois AAAA-MM. Pour un trimestre ou une année, start / end à la place.",
    )
    start: str | None = Field(
        default=None, pattern=DAY, description="Premier jour inclus, AAAA-MM-JJ."
    )
    end: str | None = Field(
        default=None, pattern=DAY, description="Dernier jour inclus, AAAA-MM-JJ."
    )
    type: FlowType = Field(
        default="expense", description="expense = dépenses (défaut), income = revenus."
    )
    account_id: int | None = Field(
        default=None,
        gt=0,
        description="Un seul compte (identifiant de tresorerie_accounts) ; par défaut tous.",
    )
    by_month: bool = Field(
        default=False, description="true = une colonne par mois (période de plusieurs mois)."
    )

    @model_validator(mode="before")
    @classmethod
    def _blanks(cls, data: object) -> object:
        return unset_blanks(data)

    @model_validator(mode="after")
    def _period(self) -> CategoryTotalsInput:
        _check_period(self.month, self.start, self.end)
        return self


#: Colonnes fixes de la table `atelier-table/1` (les mois s'ajoutent avec by_month)
TOTALS_COLUMNS: tuple[tuple[str, str, TableType], ...] = (
    ("categorie", "Catégorie", "string"),
    ("operations", "Opérations", "number"),
    ("total", "Total €", "number"),
    ("part", "Part %", "number"),
)
UNCATEGORIZED = "Sans catégorie"


class CategoryTotalsTool(_TresoTool[CategoryTotalsInput]):
    name = "tresorerie_category_totals"
    description = (
        "Totaux par catégorie sur un mois ou une période (trimestre, année) : nombre "
        "d'opérations, montant et part du total, éventuellement mois par mois. Additionne "
        "TOUTES les opérations du filtre (toutes les pages), virements internes exclus. Pour "
        "un récapitulatif de dépenses ou de revenus par catégorie."
    )
    input_model = CategoryTotalsInput
    output_format = "atelier-table/1"
    output_hint = table_hint(*TOTALS_COLUMNS)

    async def run(self, params: CategoryTotalsInput, ctx: ToolContext) -> ToolOutput:
        filters: dict[str, str | int] = {
            "type": params.type,
            "per_page": MAX_PER_PAGE,
            "sort": "date",
            "order": "asc",
        }
        for key in ("month", "start", "end", "account_id"):
            value = getattr(params, key)
            if value:
                filters[key] = value
        first = await self.client.transactions(**filters, page=1)
        seen: dict[int, Transaction] = {t.id: t for t in first.items}
        pages = min(first.pages, MAX_PAGES)
        for number in range(2, pages + 1):
            page = await self.client.transactions(**filters, page=number)
            fresh = [t for t in page.items if t.id not in seen]
            if not fresh:
                break  # page vide ou déjà lue : pagination incohérente, on s'arrête
            seen.update((t.id, t) for t in fresh)
        items = list(seen.values())
        expected = abs(first.expense_cents if params.type == "expense" else first.income_cents)

        totals: dict[str, int] = defaultdict(int)
        counts: dict[str, int] = defaultdict(int)
        by_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for t in items:
            name = t.category_name or UNCATEGORIZED
            totals[name] += abs(t.amount_cents)
            counts[name] += 1
            by_month[name][t.date[:7]] += abs(t.amount_cents)
        grand = sum(totals.values())
        seen_months = {t.date[:7] for t in items}
        if params.start and params.end:
            seen_months |= set(months_between(params.start, params.end))
        months = sorted(seen_months)
        pivot = params.by_month and 1 < len(months) <= 12

        noun = TYPE_LABELS[params.type]
        where = period_label(params.month, params.start, params.end)
        if params.account_id:
            where += f", {items[0].account_name if items else f'compte #{params.account_id}'}"
        order = sorted(totals, key=lambda n: (-totals[n], n))
        headers = ["catégorie", *(months if pivot else []), "opérations", f"{noun} €", "part %"]
        rows = [
            [
                name,
                *([by_month[name].get(m, 0) / 100 for m in months] if pivot else []),
                counts[name],
                totals[name] / 100,
                round(totals[name] * 100 / grand, 1) if grand else 0,
            ]
            for name in order
        ]

        lines = [
            f"{noun.capitalize()} par catégorie ({where}) : {len(items)} opération(s), total "
            f"{euros(grand)} (en valeur positive, virements internes exclus)."
        ]
        if not items:
            lines.append("Aucune opération sur ce filtre.")
        else:
            lines.append(markdown_table(headers, rows))
            if pivot:
                lines.append(
                    "Mois par mois : "
                    + ", ".join(
                        f"{m} {euros(sum(by_month[n].get(m, 0) for n in order))}" for m in months
                    )
                    + "."
                )
            elif params.by_month and len(months) > 12:
                lines.append("Colonnes par mois omises : plus de 12 mois (réduire la période).")
        if UNCATEGORIZED in totals:
            lines.append(
                f"{counts[UNCATEGORIZED]} opération(s) sans catégorie : à catégoriser "
                "(tresorerie_transactions avec uncategorized) pour un récapitulatif juste."
            )
        complete = len(items) >= first.total and grand == expected
        if not complete:
            lines.append(
                f"Attention : Trésorerie annonce {first.total} opération(s) pour "
                f"{euros(expected)} sur ce filtre, {len(items)} lue(s) ici pour {euros(grand)} "
                "(trop d'opérations ou pagination incomplète) : présenter ces totaux comme partiels."
            )
        elif items:
            lines.append("Contrôle : total identique à celui calculé par Trésorerie sur ce filtre.")

        # Un tableau partiel le dit dans son titre : il peut être relu hors de la conversation
        title = f"{noun.capitalize()} par catégorie — {where}" + ("" if complete else " (partiel)")
        artifacts = []
        if items:
            numeric = {h for h in headers if h != "catégorie"}
            artifacts.append(
                data_artifact(
                    title, headers, rows, numeric=numeric, metadata={"source": "tresorerie"}
                )
            )
            lines.append("Tableau publié dans le panneau des artefacts.")
        columns: list[tuple[str, str, TableType]] = [
            TOTALS_COLUMNS[0],
            *((m, m, "number") for m in (months if pivot else [])),
            *TOTALS_COLUMNS[1:],
        ]
        data = atelier_table(
            "tresorerie-totaux-categories",
            title,
            columns,
            rows,
            total=len(rows),
            truncated=not complete,
        )
        return ToolOutput(content="\n".join(lines), artifacts=artifacts, data=data)


class NoInput(ToolInput):
    pass


class CategoriesTool(_TresoTool[NoInput]):
    name = "tresorerie_categories"
    description = (
        "Catégories (depense, revenu, transfert) avec leur identifiant et leur nombre "
        "d'opérations. Dans les autres outils, type expense = depense, income = revenu, "
        "transfer = transfert."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        cats = await self.client.categories()
        lines = [f"- {c.id} : {c.name} ({c.kind}, {c.transaction_count} op.)" for c in cats.items]
        return ToolOutput(content="\n".join(lines) or "Aucune catégorie.")


class BudgetsInput(ToolInput):
    month: str | None = Field(
        default=None, pattern=MONTH, description="AAAA-MM (défaut : mois en cours)"
    )


class BudgetsTool(_TresoTool[BudgetsInput]):
    name = "tresorerie_budgets"
    description = (
        "Budgets d'un mois par catégorie : plafond, dépensé, reste ou dépassement, % et alerte "
        "(ok / attention / dépassé), et dépenses des catégories sans budget."
    )
    input_model = BudgetsInput

    async def run(self, params: BudgetsInput, ctx: ToolContext) -> ToolOutput:
        b = await self.client.budgets(params.month)
        status = {"ok": "ok", "attention": "attention (≥ 80 %)", "depasse": "DÉPASSÉ"}
        lines = [
            f"Budgets {b.month} : {euros(abs(b.total_spent_cents))} dépensés sur "
            f"{euros(b.total_limit_cents)} budgétés ({fmt(b.total_percent)} %)."
        ]
        for i in b.items:
            rest = (
                f"reste {euros(i.remaining_cents)}"
                if i.remaining_cents >= 0
                else f"dépassement de {euros(-i.remaining_cents)}"
            )
            lines.append(
                f"- {i.category_name} : {euros(abs(i.spent_cents))} dépensés sur "
                f"{euros(i.amount_limit_cents)}, {rest} ({fmt(i.percent)} %) — {status[i.status]}"
            )
        if b.unbudgeted:
            lines.append(
                "Dépenses hors budget (catégories sans plafond) : "
                + ", ".join(f"{u.category_name} {euros(abs(u.spent_cents))}" for u in b.unbudgeted)
            )
        return ToolOutput(content="\n".join(lines))


class GoalsTool(_TresoTool[NoInput]):
    name = "tresorerie_goals"
    description = (
        "Objectifs d'épargne : cible, progression, reste, échéance et effort mensuel nécessaire."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        goals = await self.client.goals()
        lines = [
            f"- {g.name} : {euros(g.progress_cents)} / {euros(g.target_amount_cents)} ({g.percent:g} %), "
            f"reste {euros(g.remaining_cents)}"
            + (f", échéance {g.deadline} ({g.months_left} mois)" if g.deadline else "")
            + (f", {euros(g.monthly_needed_cents)} par mois" if g.monthly_needed_cents else "")
            for g in goals.items
        ]
        return ToolOutput(content="\n".join(lines) or "Aucun objectif.")


class HoldingsTool(_TresoTool[NoInput]):
    name = "tresorerie_holdings"
    description = (
        "Placements : valeur, prix de revient, plus-value (négative = moins-value), poids dans "
        "le portefeuille, totaux."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        h = await self.client.holdings()
        t = h.totals
        rows = [
            [
                x.name,
                x.asset_label,
                x.account_name,
                x.quantity,
                x.value_cents / 100,
                x.gain_cents / 100,
                x.gain_percent,
                x.weight_percent,
            ]  # fmt: skip
            for x in h.items
        ]
        text, _ = table_for_model(
            ["placement", "type", "compte", "quantité", "valeur €", "plus-value €", "plus-value %", "poids %"],
            rows, noun="placement",
        )  # fmt: skip
        return ToolOutput(
            content=f"Portefeuille : {euros(t.value_cents)}, plus-value {euros(t.gain_cents)} "
            f"({pct(t.gain_percent)}).\n{text}"
        )


def tresorerie_tools(client: TresorerieClient) -> list[BaseTool[Any]]:
    return [
        DashboardTool(client),
        AccountsTool(client),
        CategoriesTool(client),
        TransactionsTool(client),
        CategoryTotalsTool(client),
        BudgetsTool(client),
        GoalsTool(client),
        HoldingsTool(client),
    ]
