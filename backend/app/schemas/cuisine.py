"""Schémas d'Atelier Cuisine : Supabase (PostgREST `/rest/v1` + Auth `/auth/v1`).

Contrat lu dans le dépôt `Atelier_Cuisine` (backend/supabase/migrations, frontend/src/lib/
supabase.ts) puis vérifié sur le schéma déployé (2026-10-20). Les données du foyer sont
isolées par Row Level Security (`user_id = auth.uid()`) : avec la clé publique et la
session de l'utilisateur, on ne lit QUE ses lignes.

On ne demande à PostgREST que les colonnes utiles (`select=`) : jamais `raw_text` d'un
ticket ni les prix d'achat dans les outils non sensibles.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Location = Literal["frigo", "congelateur", "placard", "corbeille", "maison"]
StockLevel = Literal["plein", "moitie", "un_repas", "fin"]
Slot = Literal["petit_dejeuner", "dejeuner", "gouter", "diner"]
MealType = Literal["recette", "assemblage", "exterieur", "libre"]
MealStatus = Literal["prevu", "cuisine"]
ShoppingSource = Literal["manuel", "planning", "a_racheter", "ticket"]
BudgetScope = Literal["global", "alimentaire", "maison", "sorties"]
BudgetPeriod = Literal["semaine", "mois"]
SessionSource = Literal["liste", "ticket_pdf", "ticket_photo", "ticket_texte", "manuel"]

LOCATION_LABELS: dict[str, str] = {
    "frigo": "Frigo",
    "congelateur": "Congélateur",
    "placard": "Placard",
    "corbeille": "Corbeille",
    "maison": "Maison",
}
LEVEL_LABELS: dict[str, str] = {
    "plein": "Plein",
    "moitie": "Moitié",
    "un_repas": "Assez pour 1 repas",
    "fin": "Presque fini",
}
SLOT_LABELS: dict[str, str] = {
    "petit_dejeuner": "Petit-déjeuner",
    "dejeuner": "Déjeuner",
    "gouter": "Goûter",
    "diner": "Dîner",
}
MEAL_TYPE_LABELS: dict[str, str] = {
    "recette": "recette",
    "assemblage": "assemblage rapide",
    "exterieur": "extérieur",
    "libre": "libre",
}
SOURCE_LABELS: dict[str, str] = {
    "manuel": "ajout manuel",
    "planning": "pour un repas prévu",
    "a_racheter": "à racheter",
    "ticket": "repris d'un ticket",
}
SCOPE_LABELS: dict[str, str] = {
    "global": "Global",
    "alimentaire": "Alimentaire",
    "maison": "Maison & hygiène",
    "sorties": "Sorties / resto",
}


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ─── Supabase Auth ────────────────────────────────────────────────


class AuthUser(_R):
    id: str
    email: str | None = None


class AuthSession(_R):
    """Réponse de `POST /auth/v1/token` (mot de passe ou jeton de rafraîchissement)."""

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    token_type: str = "bearer"
    expires_in: int = Field(gt=0)
    #: Horodatage Unix d'expiration (absent des anciennes versions de GoTrue)
    expires_at: int | None = None
    user: AuthUser


# ─── Tables (lecture) ─────────────────────────────────────────────


class Aisle(_R):
    """Rayon du foyer (table `aisles`, commune) : 1 à 9 alimentaire, 10 et 11 maison."""

    id: str
    position: int
    emoji: str = ""
    name: str
    budget: Literal["alimentaire", "maison"] = "alimentaire"


class PantryItem(_R):
    """Produit du stock (`pantry_items`) : quantité exacte OU niveau rapide."""

    id: str
    name: str
    quantity: float | None = None
    unit: str | None = None
    category: str = "autre"
    location: Location = "frigo"
    expires_on: date | None = None
    stock_level: StockLevel | None = None
    opened_on: date | None = None
    #: Mis dans une boîte (restes) : `opened_on` est alors la date de mise en boîte
    in_container: bool = False
    note: str | None = None
    created_at: datetime


class Meal(_R):
    """Repas du semainier (`meals`) ; `external_cost` n'est lu que par l'outil Budget."""

    id: str
    eaten_on: date
    slot: Slot
    title: str
    servings: int | None = None
    notes: str | None = None
    meal_type: MealType = "libre"
    status: MealStatus = "cuisine"
    external_cost: float | None = None


class ShoppingItem(_R):
    """Article de la liste de courses (`shopping_items`), sans ses prix."""

    id: str
    name: str
    quantity: float | None = None
    unit: str | None = None
    category: str = "autre"
    checked: bool = False
    source: ShoppingSource = "manuel"
    note: str | None = None
    created_at: datetime


class ShoppingSession(_R):
    """Ticket de caisse archivé (`shopping_sessions`), sans le texte brut du ticket."""

    id: str
    purchased_at: datetime
    store_name: str
    total_amount: float
    food_subtotal: float = 0
    home_subtotal: float = 0
    items_count: int = 0
    source: SessionSource = "liste"


class Budget(_R):
    """Plafond par périmètre (`budgets`, un par périmètre et par compte)."""

    scope: BudgetScope
    period: BudgetPeriod = "mois"
    amount: float = Field(gt=0)
