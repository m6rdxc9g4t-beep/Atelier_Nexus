"""Connecteur Atelier Trésorerie — lecture seule, données SENSIBLES.

Règle d'Atelier Trésorerie : « aucune donnée financière ne doit quitter la machine ».
Tous ces outils sont `sensitive` : un agent qui les utilise est verrouillé sur un
modèle local (Ollama), sans repli vers Claude, et ne peut pas être appelé par un
orchestrateur qui tourne sur Claude (voir app/agents/base.py et delegation.py).
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import Field

from app.core.config import Settings
from app.schemas.tresorerie import (
    AccountList,
    BudgetMonth,
    CategoryList,
    Dashboard,
    GoalList,
    HoldingList,
    Ping,
    TransactionPage,
    TxStatus,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import data_artifact, euros, fmt, table_for_model
from app.tools.http import AppClient, AppError, AppRequestError

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
DAY = r"^\d{4}-\d{2}-\d{2}$"


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


def pct(value: float | None) -> str:
    return "∅" if value is None else f"{value:+.1f} %"


class _TresoTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)
    sensitive = True

    def __init__(self, client: TresorerieClient) -> None:
        self.client = client


class DashboardInput(ToolInput):
    months: int = Field(default=6, ge=2, le=24, description="Historique, en mois.")


class DashboardTool(_TresoTool[DashboardInput]):
    name = "tresorerie_dashboard"
    description = (
        "Synthèse financière : patrimoine net, revenus, dépenses et taux d'épargne du mois "
        "(comparés au mois précédent à date), historique mensuel et dépenses par catégorie."
    )
    input_model = DashboardInput

    async def run(self, params: DashboardInput, ctx: ToolContext) -> ToolOutput:
        d = await self.client.dashboard(params.months)
        k = d.kpis
        lines = [
            f"Au {d.today} (mois {d.month}, comparaison au {d.comparison_day} {d.previous_month_label}) :",
            f"- Patrimoine net : {euros(k.net_worth_cents)} (variation {euros(k.net_worth_change_cents)},"
            f" {pct(k.net_worth_change_percent)}), dont placements {euros(k.investments_cents)}.",
            f"- Revenus du mois : {euros(k.income_cents)} ({pct(k.income_change_percent)}).",
            f"- Dépenses du mois : {euros(k.expense_cents)} ({pct(k.expense_change_percent)}).",
            f"- Taux d'épargne : {fmt(k.savings_rate)} %.",
            "",
            "Historique :",
        ]
        lines += [
            f"- {h.label} : patrimoine {euros(h.total_cents)}, revenus {euros(h.income_cents)}, "
            f"dépenses {euros(h.expense_cents)}{' (mois en cours)' if h.partial else ''}"
            for h in d.history
        ]
        lines += ["", f"Dépenses par catégorie ({d.categories.month}) :"]
        lines += [
            f"- {c.name} : {euros(c.amount_cents)} ({c.percent:g} %)" for c in d.categories.items
        ]
        return ToolOutput(content="\n".join(lines))


class AccountsInput(ToolInput):
    include_archived: bool = False


class AccountsTool(_TresoTool[AccountsInput]):
    name = "tresorerie_accounts"
    description = "Comptes : type, établissement, solde, valeur des placements, valeur totale."
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
    account_id: int | None = None
    category_id: int | None = Field(default=None, description="Catégorie (tresorerie_categories).")
    uncategorized: bool = Field(
        default=False, description="Seulement les opérations sans catégorie."
    )
    month: str | None = Field(default=None, pattern=MONTH, description="AAAA-MM")
    start: str | None = Field(default=None, pattern=DAY, description="AAAA-MM-JJ inclus")
    end: str | None = Field(default=None, pattern=DAY, description="AAAA-MM-JJ inclus")
    type: Literal["income", "expense", "transfer"] | None = None
    status: TxStatus | None = None
    query: str | None = Field(
        default=None, max_length=100, description="Texte du libellé ou des notes."
    )
    sort: Literal["date", "amount", "label"] = "date"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=100, ge=1, le=200)


class TransactionsTool(_TresoTool[TransactionsInput]):
    name = "tresorerie_transactions"
    description = (
        "Opérations filtrées (compte, catégorie, mois ou période, revenu / dépense / virement, "
        "statut, texte) avec totaux revenus / dépenses / net sur TOUT le filtre."
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
        text, _ = table_for_model(headers, rows, noun="opération")
        summary = (
            f"{page.total} opération(s) au total ({len(page.items)} renvoyées). Sur tout le filtre : "
            f"revenus {euros(page.income_cents)}, dépenses {euros(page.expense_cents)}, "
            f"net {euros(page.net_cents)}."
        )
        artifact = data_artifact(
            "Opérations", headers, rows, numeric={"montant €"}, metadata={"source": "tresorerie"}
        )
        return ToolOutput(content=f"{summary}\n{text}", artifacts=[artifact])


class NoInput(ToolInput):
    pass


class CategoriesTool(_TresoTool[NoInput]):
    name = "tresorerie_categories"
    description = (
        "Catégories (dépense, revenu, transfert) avec leur identifiant et leur nombre d'opérations."
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
    description = "Budgets d'un mois par catégorie : plafond, dépensé, reste, % et alerte (ok / attention / dépassé)."
    input_model = BudgetsInput

    async def run(self, params: BudgetsInput, ctx: ToolContext) -> ToolOutput:
        b = await self.client.budgets(params.month)
        status = {"ok": "ok", "attention": "attention (≥ 80 %)", "depasse": "DÉPASSÉ"}
        lines = [
            f"Budgets {b.month} : {euros(b.total_spent_cents)} dépensés sur {euros(b.total_limit_cents)}"
            f" ({fmt(b.total_percent)} %)."
        ]
        lines += [
            f"- {i.category_name} : {euros(i.spent_cents)} / {euros(i.amount_limit_cents)}, reste "
            f"{euros(i.remaining_cents)} — {status[i.status]}"
            for i in b.items
        ]
        if b.unbudgeted:
            lines.append(
                "Hors budget : "
                + ", ".join(f"{u.category_name} {euros(u.spent_cents)}" for u in b.unbudgeted)
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
        "Placements : valeur, prix de revient, plus-value, poids dans le portefeuille, totaux."
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
        BudgetsTool(client),
        GoalsTool(client),
        HoldingsTool(client),
    ]
