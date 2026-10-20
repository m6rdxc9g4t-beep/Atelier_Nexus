"""Schémas de l'API d'Atelier Trésorerie (Flask, `http://127.0.0.1:5050/api`).

Contrat de référence : `Atelier_Tr-sorerie/api.py` et `services/`. Montants en centimes
entiers (`*_cents`) ; positif = entrée, négatif = sortie. Réponses : champs inconnus ignorés.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["courant", "epargne", "investissement", "credit", "especes"]
CategoryKind = Literal["depense", "revenu", "transfert"]
TxStatus = Literal["valide", "en_attente", "rapproche"]
BudgetStatus = Literal["ok", "attention", "depasse"]


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Ping(_R):
    app: str


class Account(_R):
    id: int
    name: str
    type: AccountType
    type_label: str
    institution: str | None = None
    currency: str = "EUR"
    archived: bool
    balance_cents: int
    holdings_value_cents: int = 0
    total_value_cents: int
    transaction_count: int = 0
    last_transaction_date: str | None = None


class AccountList(_R):
    items: list[Account]
    total_balance_cents: int


class Category(_R):
    id: int
    name: str
    kind: CategoryKind
    transaction_count: int = 0


class CategoryList(_R):
    items: list[Category]


class Transaction(_R):
    id: int
    account_id: int
    account_name: str
    category_id: int | None = None
    category_name: str | None = None
    category_kind: CategoryKind | None = None
    date: str
    label: str
    amount_cents: int
    status: TxStatus
    notes: str | None = None
    transfer_group: str | None = None


class TransactionPage(_R):
    items: list[Transaction]
    total: int
    page: int
    per_page: int
    pages: int
    income_cents: int
    expense_cents: int
    net_cents: int


class BudgetItem(_R):
    category_name: str
    amount_limit_cents: int
    spent_cents: int
    remaining_cents: int
    percent: float | None = None
    status: BudgetStatus


class Unbudgeted(_R):
    category_name: str
    spent_cents: int


class BudgetMonth(_R):
    month: str
    items: list[BudgetItem]
    unbudgeted: list[Unbudgeted] = Field(default_factory=list)
    total_limit_cents: int
    total_spent_cents: int
    total_percent: float | None = None


class Goal(_R):
    id: int
    name: str
    target_amount_cents: int
    progress_cents: int
    percent: float
    remaining_cents: int
    deadline: str | None = None
    months_left: int | None = None
    monthly_needed_cents: int | None = None
    account_name: str | None = None


class GoalList(_R):
    items: list[Goal]


class Holding(_R):
    id: int
    account_name: str
    name: str
    asset_type: str
    asset_label: str
    symbol: str | None = None
    quantity: float
    value_cents: int
    cost_basis_cents: int
    gain_cents: int
    gain_percent: float | None = None
    weight_percent: float | None = None
    closed: bool = False


class HoldingTotals(_R):
    value_cents: int
    cost_cents: int
    gain_cents: int
    gain_percent: float | None = None


class HoldingList(_R):
    items: list[Holding]
    totals: HoldingTotals


class Kpis(_R):
    net_worth_cents: int
    net_worth_change_cents: int | None = None
    net_worth_change_percent: float | None = None
    investments_cents: int = 0
    income_cents: int
    income_change_percent: float | None = None
    expense_cents: int
    expense_change_percent: float | None = None
    savings_rate: float | None = None


class HistoryPoint(_R):
    month: str
    label: str
    total_cents: int
    income_cents: int
    expense_cents: int
    partial: bool = False


class CategorySpend(_R):
    name: str
    amount_cents: int
    percent: float


class CategoryBreakdown(_R):
    month: str
    total_cents: int
    items: list[CategorySpend]


class Dashboard(_R):
    today: str
    month: str
    previous_month_label: str
    comparison_day: int
    kpis: Kpis
    history: list[HistoryPoint]
    categories: CategoryBreakdown
