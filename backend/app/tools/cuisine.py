"""Connecteur Atelier Cuisine — stock, planning des repas, liste de courses, budget du foyer.

Atelier Cuisine est une app EN LIGNE : ses données sont dans Supabase (Postgres + Row Level
Security par `user_id`). Nexus lit l'API REST du projet (PostgREST, `/rest/v1`) avec :

- la clé PUBLIQUE du projet (anon / publishable), comme l'app elle-même ; une clé
  `service_role` / `sb_secret_…` est refusée (elle contournerait RLS) ;
- la session du foyer, ouverte par Supabase Auth (`/auth/v1/token`) avec l'e-mail et le mot de
  passe, ou un jeton de rafraîchissement. RLS fait le reste : seules les lignes du compte
  connecté sont lisibles.

Supabase fait tourner les jetons de rafraîchissement (un jeton ne sert qu'une fois) : la session
en cours est gardée en mémoire et dans un fichier 600 à côté du `.env` (`cuisine-session.json`),
jamais dans le dépôt ni dans une réponse d'outil.

LECTURE SEULE dans ce lot. Le budget et les tickets (données financières du foyer) sont dans une
boîte à part, `sensitive` : l'agent qui l'utilise est verrouillé sur le modèle local.
Les outils non sensibles ne demandent jamais les prix (`select=` explicite).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import calendar
import hashlib
import json
import logging
import os
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr

from app.core.config import Settings
from app.schemas.cuisine import (
    LEVEL_LABELS,
    LOCATION_LABELS,
    MEAL_TYPE_LABELS,
    SCOPE_LABELS,
    SLOT_LABELS,
    SOURCE_LABELS,
    Aisle,
    AuthSession,
    Budget,
    BudgetScope,
    Location,
    Meal,
    PantryItem,
    ShoppingItem,
    ShoppingSession,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import euros, fmt, markdown_table
from app.tools.http import AppClient, AppError, AppNotConfiguredError, AppRequestError

logger = logging.getLogger(__name__)

#: Marge avant expiration du jeton d'accès (s)
REFRESH_MARGIN = 60
SESSION_FILE_NAME = "cuisine-session.json"
_LOCAL_HOSTS = {"127.0.0.1", "localhost"}

DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip
SLOT_ORDER = {"petit_dejeuner": 0, "dejeuner": 1, "gouter": 2, "diner": 3}


# ─── Contrôles de configuration ───────────────────────────────────


def supabase_url_problem(url: str) -> str | None:
    """Adresse du projet : HTTPS (HTTP seulement pour un Supabase local de développement)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "adresse invalide"
    if not parts.hostname or parts.scheme not in {"http", "https"}:
        return "adresse attendue : https://<projet>.supabase.co"
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        return "HTTPS obligatoire (HTTP seulement pour un Supabase local)"
    if parts.path.strip("/") or parts.query:
        return "indiquez l'adresse du projet seule (sans /rest/v1)"
    return None


def anon_key_problem(key: str) -> str | None:
    """Refuse une clé qui contournerait RLS (`service_role`, `sb_secret_…`)."""
    key = key.strip()
    if key.startswith("sb_secret_"):
        return "clé secrète refusée : utilisez la clé publique (sb_publishable_… ou anon)"
    parts = key.split(".")
    if len(parts) == 3:  # ancienne clé JWT : le rôle est dans la charge utile
        try:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except (binascii.Error, ValueError):
            return "clé JWT illisible"
        role = payload.get("role") if isinstance(payload, dict) else None
        if role != "anon":
            return f"clé de rôle « {role} » refusée : utilisez la clé publique (anon)"
    return None


# ─── Session Supabase (jetons tournants) ──────────────────────────


@dataclass
class StoredSession:
    access_token: str
    refresh_token: str
    #: Expiration du jeton d'accès (horodatage Unix)
    expires_at: float
    user_id: str


class SessionStore:
    """Session en cours, par compte : mémoire du processus + fichier 600 (survit au redémarrage).

    Clé = empreinte de (adresse, e-mail ou jeton initial) : changer d'identifiants dans les
    Réglages repart d'une session neuve. Les jetons ne sont jamais journalisés.
    """

    _memory: ClassVar[dict[str, StoredSession]] = {}

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def _read_file(self) -> dict[str, Any]:
        if self.path is None:
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        sessions = data.get("sessions") if isinstance(data, dict) else None
        return sessions if isinstance(sessions, dict) else {}

    def get(self, key: str) -> StoredSession | None:
        if key in self._memory:
            return self._memory[key]
        raw = self._read_file().get(key)
        if not isinstance(raw, dict):
            return None
        try:
            session = StoredSession(
                access_token=str(raw["access_token"]),
                refresh_token=str(raw["refresh_token"]),
                expires_at=float(raw["expires_at"]),
                user_id=str(raw["user_id"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        self._memory[key] = session
        return session

    def put(self, key: str, session: StoredSession | None) -> None:
        if session is None:
            self._memory.pop(key, None)
        else:
            self._memory[key] = session
        if self.path is None:
            return
        sessions = self._read_file()
        if session is None:
            sessions.pop(key, None)
        else:
            sessions[key] = asdict(session)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".cuisine-session.", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"version": 1, "sessions": sessions}, fh)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:  # la session reste en mémoire
            logger.warning("Session Atelier Cuisine non enregistrée : %s", exc.strerror)

    @classmethod
    def clear_memory(cls) -> None:
        cls._memory.clear()


_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}


def _lock(key: str) -> asyncio.Lock:
    """Un renouvellement à la fois par compte (dans la boucle courante)."""
    loop_id = id(asyncio.get_running_loop())
    return _LOCKS.setdefault((key, loop_id), asyncio.Lock())


def default_session_file(settings: Settings) -> Path:
    if settings.cuisine_session_file:
        return Path(settings.cuisine_session_file).expanduser()
    from app.core.settings_editor import env_file_path

    return env_file_path().parent / SESSION_FILE_NAME


# ─── Client ───────────────────────────────────────────────────────


class CuisineClient(AppClient):
    app = "cuisine"
    label = "Atelier Cuisine"
    # GoTrue : msg / error_description ; PostgREST : message
    error_keys = ("msg", "message", "error_description", "error", "hint")

    def __init__(
        self,
        base_url: str,
        *,
        anon_key: str,
        email: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
        sessions: SessionStore | None = None,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        today: Callable[[], date] = date.today,
    ) -> None:
        if problem := supabase_url_problem(base_url):
            raise AppNotConfiguredError(f"CUISINE_SUPABASE_URL : {problem}.", app="cuisine")
        if problem := anon_key_problem(anon_key):
            raise AppNotConfiguredError(f"CUISINE_SUPABASE_ANON_KEY : {problem}.", app="cuisine")
        if not ((email and password) or refresh_token):
            raise AppNotConfiguredError(
                "Atelier Cuisine : renseignez l'e-mail et le mot de passe du foyer, "
                "ou un jeton de rafraîchissement.",
                app="cuisine",
            )
        super().__init__(
            base_url, headers={"apikey": anon_key.strip()}, timeout=timeout, transport=transport
        )
        self._email = email
        self._password = password
        self._initial_refresh = refresh_token
        self._sessions = sessions or SessionStore(None)
        self._clock = clock
        self.today = today
        identity = email.lower() if email and password else "rt:" + _digest(refresh_token or "")
        self._key = _digest(f"{self.base_url}|{identity}")

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> CuisineClient | None:
        if not settings.cuisine_configured:
            return None
        assert settings.cuisine_supabase_url and settings.cuisine_supabase_anon_key

        def secret(value: SecretStr | None) -> str | None:
            return value.get_secret_value() if value else None

        return cls(
            settings.cuisine_supabase_url,
            anon_key=settings.cuisine_supabase_anon_key.get_secret_value(),
            email=settings.cuisine_email,
            password=secret(settings.cuisine_password),
            refresh_token=secret(settings.cuisine_refresh_token),
            sessions=SessionStore(default_session_file(settings)),
            timeout=settings.apps_timeout,
            transport=transport,
        )

    def _unavailable_hint(self) -> str:
        return "app en ligne, vérifiez la connexion Internet de cette machine."

    # ── Authentification ──

    async def _grant(self, grant: str, body: dict[str, str]) -> StoredSession:
        try:
            data = await self.request(
                "POST", "auth/v1/token", params={"grant_type": grant}, json_body=body
            )
        except AppRequestError as exc:
            if self.last_status == 429:
                message = "Supabase limite les connexions : réessayez dans quelques minutes."
            elif grant == "password":
                message = (
                    "Connexion à Atelier Cuisine refusée (e-mail ou mot de passe, ou adresse non "
                    "confirmée) : vérifiez CUISINE_EMAIL et CUISINE_PASSWORD dans les Réglages."
                )
            else:
                message = (
                    "Session Atelier Cuisine expirée ou révoquée : renseignez le mot de passe du "
                    "foyer (ou un nouveau jeton de rafraîchissement) dans les Réglages."
                )
            raise AppRequestError(message, app=self.app) from exc
        auth = self.parse(AuthSession, data)
        expires = auth.expires_at or (self._clock() + auth.expires_in)
        return StoredSession(auth.access_token, auth.refresh_token, float(expires), auth.user.id)

    async def _sign_in(self) -> StoredSession:
        if self._email and self._password:
            return await self._grant("password", {"email": self._email, "password": self._password})
        assert self._initial_refresh
        return await self._grant("refresh_token", {"refresh_token": self._initial_refresh})

    async def access_token(self, *, force_refresh: bool = False) -> str:
        """Jeton d'accès valide : session gardée, renouvelée, ou nouvelle connexion."""
        async with _lock(self._key):
            current = self._sessions.get(self._key)
            if (
                current
                and not force_refresh
                and current.expires_at - REFRESH_MARGIN > self._clock()
            ):
                return current.access_token
            fresh: StoredSession | None = None
            if current:
                try:
                    fresh = await self._grant(
                        "refresh_token", {"refresh_token": current.refresh_token}
                    )
                except AppRequestError:
                    self._sessions.put(self._key, None)  # jeton usé : nouvelle connexion
                    if not (self._email and self._password):
                        raise
            if fresh is None:
                fresh = await self._sign_in()
            self._sessions.put(self._key, fresh)
            return fresh.access_token

    # ── Lecture (PostgREST) ──

    async def select(self, table: str, params: list[tuple[str, str]]) -> Any:
        """`GET /rest/v1/<table>` avec la session du foyer ; un 401 renouvelle une fois."""
        for attempt in (0, 1):
            token = await self.access_token(force_refresh=attempt == 1)
            try:
                return await self.request(
                    "GET",
                    f"rest/v1/{table}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except AppRequestError:
                if self.last_status != 401 or attempt == 1:
                    raise
        raise AssertionError("inaccessible")  # pragma: no cover

    async def aisles(self) -> list[Aisle]:
        data = await self.select(
            "aisles", [("select", "id,position,emoji,name,budget"), ("order", "position.asc")]
        )
        return self.parse_list(Aisle, data)

    async def pantry(self) -> list[PantryItem]:
        data = await self.select(
            "pantry_items",
            [
                (
                    "select",
                    "id,name,quantity,unit,category,location,expires_on,stock_level,"
                    "opened_on,in_container,note,created_at",
                ),
                ("order", "expires_on.asc.nullslast,name.asc"),
            ],
        )
        return self.parse_list(PantryItem, data)

    async def meals(self, start: date, end: date, *, with_cost: bool = False) -> list[Meal]:
        columns = "id,eaten_on,slot,title,servings,notes,meal_type,status"
        data = await self.select(
            "meals",
            [
                ("select", columns + (",external_cost" if with_cost else "")),
                ("eaten_on", f"gte.{start.isoformat()}"),
                ("eaten_on", f"lte.{end.isoformat()}"),
                ("order", "eaten_on.asc"),
            ],
        )
        return self.parse_list(Meal, data)

    async def shopping(self, *, include_checked: bool) -> list[ShoppingItem]:
        params = [
            ("select", "id,name,quantity,unit,category,checked,source,note,created_at"),
            ("order", "created_at.asc"),
        ]
        if not include_checked:
            params.append(("checked", "is.false"))
        return self.parse_list(ShoppingItem, await self.select("shopping_items", params))

    async def tickets(self, start: date, end: date) -> list[ShoppingSession]:
        """Tickets dont la date LOCALE est dans [start, end] (jamais le texte brut du ticket)."""
        since = datetime.combine(start, datetime.min.time()).astimezone()
        until = datetime.combine(end + timedelta(days=1), datetime.min.time()).astimezone()
        data = await self.select(
            "shopping_sessions",
            [
                (
                    "select",
                    "id,purchased_at,store_name,total_amount,food_subtotal,home_subtotal,"
                    "items_count,source",
                ),
                ("purchased_at", f"gte.{since.isoformat()}"),
                ("purchased_at", f"lt.{until.isoformat()}"),
                ("order", "purchased_at.desc"),
            ],
        )
        return self.parse_list(ShoppingSession, data)

    async def budgets(self) -> list[Budget]:
        return self.parse_list(
            Budget, await self.select("budgets", [("select", "scope,period,amount")])
        )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


# ─── Mise en forme ────────────────────────────────────────────────


def day_label(d: date, today: date) -> str:
    text = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
    delta = (d - today).days
    extra = {0: " (aujourd'hui)", 1: " (demain)", -1: " (hier)"}.get(delta, "")
    return text[0].upper() + text[1:] + extra


def expiry_label(expires_on: date | None, today: date) -> str:
    """Libellé d'échéance d'Atelier Cuisine (frontend/src/lib/dates.ts)."""
    if expires_on is None:
        return "sans date"
    days = (expires_on - today).days
    if days < -1:
        return f"périmé depuis {-days} jours"
    if days == -1:
        return "périmé depuis hier"
    if days == 0:
        return "à consommer aujourd'hui"
    if days == 1:
        return "demain"
    if days < 14:
        return f"dans {days} jours"
    return f"le {expires_on:%d/%m/%Y}"


def amount(item: PantryItem | ShoppingItem) -> str:
    if item.quantity is not None:
        return f"{fmt(item.quantity)} {item.unit or ''}".strip()
    level = getattr(item, "stock_level", None)
    return LEVEL_LABELS[level] if level else "—"


def money(value: float) -> str:
    return euros(round(value * 100))


def clip(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def aisle_names(aisles: list[Aisle]) -> dict[str, str]:
    return {a.id: f"{a.emoji} {a.name}".strip() for a in aisles}


# ─── Budget (mêmes règles que frontend/src/lib/budget.ts) ─────────


@dataclass(frozen=True)
class Spending:
    alimentaire: float
    maison: float
    sorties: float
    tickets: int
    cooked_meals: int
    average_basket: float | None
    cost_per_meal: float | None

    @property
    def global_(self) -> float:
        return round(self.alimentaire + self.maison + self.sorties, 2)

    def of(self, scope: BudgetScope) -> float:
        return self.global_ if scope == "global" else float(getattr(self, scope))


def local_day(moment: datetime) -> date:
    return moment.astimezone().date()


def spending(tickets: list[ShoppingSession], meals: list[Meal], start: date, end: date) -> Spending:
    """Alimentaire = rayons 1 à 9 des tickets, Maison = rayons 10-11, Sorties = repas extérieurs."""
    s = [t for t in tickets if start <= local_day(t.purchased_at) <= end]
    m = [x for x in meals if start <= x.eaten_on <= end]
    food = round(sum(t.food_subtotal for t in s), 2)
    home = round(sum(t.home_subtotal for t in s), 2)
    out = round(sum(x.external_cost or 0 for x in m), 2)
    cooked = sum(1 for x in m if x.status == "cuisine" and x.meal_type != "exterieur")
    with_food = sum(1 for t in s if t.food_subtotal > 0)
    return Spending(
        alimentaire=food,
        maison=home,
        sorties=out,
        tickets=len(s),
        cooked_meals=cooked,
        average_basket=round(food / with_food, 2) if with_food else None,
        cost_per_meal=round(food / cooked, 2) if cooked else None,
    )


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


# ─── Outils ───────────────────────────────────────────────────────


class _CuisineTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)

    def __init__(self, client: CuisineClient) -> None:
        self.client = client


class StockInput(ToolInput):
    location: Location | None = Field(
        default=None, description="frigo, congelateur, placard, corbeille ou maison."
    )
    urgent_days: int = Field(
        default=3,
        ge=0,
        le=14,
        description="« À finir en premier » : périmés et produits qui arrivent à échéance d'ici N jours.",
    )
    limit: int = Field(
        default=80,
        ge=1,
        le=300,
        description="Lignes de l'inventaire affichées (ce qui presse est toujours listé en entier).",
    )


class StockTool(_CuisineTool[StockInput]):
    name = "cuisine_stock"
    description = (
        "Stock du foyer dans Atelier Cuisine (frigo, congélateur, placard, corbeille, maison) : "
        "ce qui presse d'abord (périmé ou date proche, restes mis en boîte), les produits presque "
        "finis, puis l'inventaire par emplacement (quantité ou niveau, rayon, échéance)."
    )
    input_model = StockInput

    async def run(self, params: StockInput, ctx: ToolContext) -> ToolOutput:
        today = self.client.today()
        items = await self.client.pantry()
        rayons = aisle_names(await self.client.aisles())
        if params.location:
            items = [i for i in items if i.location == params.location]
        if not items:
            where = f" ({LOCATION_LABELS[params.location]})" if params.location else ""
            return ToolOutput(content=f"Stock vide{where}.")

        by_place = Counter(LOCATION_LABELS[i.location] for i in items)
        lines = [
            f"{len(items)} produit(s) en stock au {today:%d/%m/%Y} : "
            + ", ".join(f"{place.lower()} {n}" for place, n in by_place.most_common())
            + "."
        ]

        def remark(i: PantryItem) -> str:
            bits = []
            if i.in_container:
                bits.append(
                    f"mis en boîte le {i.opened_on:%d/%m}" if i.opened_on else "mis en boîte"
                )
            elif i.opened_on:
                bits.append(f"ouvert le {i.opened_on:%d/%m}")
            if i.note:
                bits.append(clip(i.note, 80))
            return " ; ".join(bits)

        urgent = [
            i for i in items if i.expires_on and (i.expires_on - today).days <= params.urgent_days
        ]
        urgent.sort(key=lambda i: (i.expires_on or today, not i.in_container, i.name))
        expired = sum(1 for i in urgent if i.expires_on and i.expires_on < today)
        if urgent:
            lines.append(
                f"\nÀ finir en premier ({len(urgent)}, dont {expired} périmé(s)) :"
                if expired
                else f"\nÀ finir en premier ({len(urgent)}) :"
            )
            for i in urgent:
                extra = remark(i)
                lines.append(
                    f"- {i.name} ({LOCATION_LABELS[i.location]}, {amount(i)}) : "
                    f"{expiry_label(i.expires_on, today)}" + (f" — {extra}" if extra else "")
                )
        else:
            lines.append(f"\nRien n'arrive à échéance d'ici {params.urgent_days} jour(s).")

        low = [i for i in items if i.stock_level in ("fin", "un_repas")]
        if low:
            lines.append(
                "\nPresque finis (à racheter ?) : "
                + ", ".join(
                    f"{i.name} ({LEVEL_LABELS[i.stock_level or 'fin'].lower()})" for i in low
                )
                + "."
            )

        order = list(LOCATION_LABELS)
        ordered = sorted(
            items,
            key=lambda i: (order.index(i.location), i.expires_on or date.max, i.name.lower()),
        )
        shown = ordered[: params.limit]
        rows = [
            [
                i.name,
                LOCATION_LABELS[i.location],
                rayons.get(i.category, i.category),
                amount(i),
                expiry_label(i.expires_on, today),
                remark(i),
            ]
            for i in shown
        ]
        lines.append(
            "\nInventaire"
            + (f" ({len(shown)} premiers sur {len(items)})" if len(shown) < len(items) else "")
            + " :\n"
            + markdown_table(
                ["produit", "emplacement", "rayon", "quantité", "échéance", "remarque"], rows
            )
        )
        return ToolOutput(content="\n".join(lines))


class MealPlanInput(ToolInput):
    start: date | None = Field(
        default=None,
        description="Premier jour (AAAA-MM-JJ) ; par défaut le lundi de cette semaine.",
    )
    days: int = Field(default=7, ge=1, le=31, description="Nombre de jours affichés (1 à 31).")


class MealPlanTool(_CuisineTool[MealPlanInput]):
    name = "cuisine_meal_plan"
    description = (
        "Planning des repas d'Atelier Cuisine (semainier) : pour chaque jour, les repas par "
        "créneau avec leur type (recette, assemblage rapide, extérieur) et leur statut (prévu ou "
        "déjà cuisiné). Par défaut la semaine en cours, du lundi au dimanche."
    )
    input_model = MealPlanInput

    async def run(self, params: MealPlanInput, ctx: ToolContext) -> ToolOutput:
        today = self.client.today()
        start = params.start or week_bounds(today)[0]
        end = start + timedelta(days=params.days - 1)
        meals = await self.client.meals(start, end)
        by_day: dict[date, list[Meal]] = {}
        for meal in meals:
            by_day.setdefault(meal.eaten_on, []).append(meal)

        planned = sum(1 for m in meals if m.status == "prevu" and m.meal_type != "exterieur")
        cooked = sum(1 for m in meals if m.status == "cuisine" and m.meal_type != "exterieur")
        outside = sum(1 for m in meals if m.meal_type == "exterieur")
        lines = [
            f"Repas du {start:%d/%m/%Y} au {end:%d/%m/%Y} : {len(meals)} au planning "
            f"({planned} à cuisiner, {cooked} cuisiné(s), {outside} à l'extérieur)."
        ]
        empty: list[str] = []
        for offset in range(params.days):
            day = start + timedelta(days=offset)
            todays = sorted(by_day.get(day, []), key=lambda m: SLOT_ORDER[m.slot])
            if not todays:
                empty.append(day_label(day, today))
                continue
            lines.append(f"\n{day_label(day, today)} :")
            for m in todays:
                detail = [MEAL_TYPE_LABELS[m.meal_type]]
                if m.servings:
                    detail.append(f"{m.servings} pers.")
                detail.append("cuisiné" if m.status == "cuisine" else "prévu")
                line = f"- {SLOT_LABELS[m.slot]} : {m.title} ({', '.join(detail)})"
                if m.notes:
                    line += f" — {clip(m.notes, 100)}"
                lines.append(line)
        if empty:
            lines.append("\nRien de prévu : " + ", ".join(empty) + ".")
        return ToolOutput(content="\n".join(lines))


class ShoppingInput(ToolInput):
    include_checked: bool = Field(
        default=False, description="Inclure les articles déjà cochés (pris en magasin)."
    )


class ShoppingListTool(_CuisineTool[ShoppingInput]):
    name = "cuisine_shopping_list"
    description = (
        "Liste de courses d'Atelier Cuisine, rangée par rayon du foyer : article, quantité, "
        "origine (repas prévu, à racheter, ticket, ajout manuel) et note. Sans les prix."
    )
    input_model = ShoppingInput

    async def run(self, params: ShoppingInput, ctx: ToolContext) -> ToolOutput:
        items = await self.client.shopping(include_checked=params.include_checked)
        if not items:
            return ToolOutput(content="La liste de courses est vide.")
        aisles = await self.client.aisles()
        names = aisle_names(aisles)
        position = {a.id: a.position for a in aisles}
        groups: dict[str, list[ShoppingItem]] = {}
        for item in items:
            groups.setdefault(item.category, []).append(item)

        todo = sum(1 for i in items if not i.checked)
        lines = [
            f"{todo} article(s) à acheter"
            + (f", {len(items) - todo} déjà coché(s)" if len(items) > todo else "")
            + f", sur {len(groups)} rayon(s)."
        ]
        for category in sorted(groups, key=lambda c: (position.get(c, 999), c)):
            lines.append(f"\n{names.get(category, category)} :")
            for i in groups[category]:
                qty = amount(i)
                line = f"- {'[x] ' if i.checked else ''}{i.name}" + (
                    f" ({qty})" if qty != "—" else ""
                )
                line += f" — {SOURCE_LABELS[i.source]}"
                if i.note:
                    line += f" ; {clip(i.note, 80)}"
                lines.append(line)
        return ToolOutput(content="\n".join(lines))


class BudgetInput(ToolInput):
    month: str | None = Field(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Mois AAAA-MM ; par défaut le mois en cours.",
    )


class BudgetTool(_CuisineTool[BudgetInput]):
    name = "cuisine_budget"
    description = (
        "Budget du foyer dans Atelier Cuisine pour un mois : dépenses Alimentaire, Maison & "
        "hygiène, Sorties / resto et total, comparées aux plafonds ; panier moyen, coût par repas "
        "cuisiné et tickets de caisse du mois (magasin, montants). Données financières : modèle "
        "local imposé."
    )
    input_model = BudgetInput
    sensitive = True

    async def run(self, params: BudgetInput, ctx: ToolContext) -> ToolOutput:
        today = self.client.today()
        year, month = (
            (int(params.month[:4]), int(params.month[5:]))
            if params.month
            else (today.year, today.month)
        )
        start, end = month_bounds(year, month)
        current = start <= today <= end
        week_start, week_end = week_bounds(today)
        fetch_start, fetch_end = (
            (min(start, week_start), max(end, week_end)) if current else (start, end)
        )
        tickets = await self.client.tickets(fetch_start, fetch_end)
        meals = await self.client.meals(fetch_start, fetch_end, with_cost=True)
        budgets = {b.scope: b for b in await self.client.budgets()}
        spent = spending(tickets, meals, start, end)
        week = spending(tickets, meals, week_start, week_end) if current else None

        label = f"{MONTHS[month - 1]} {year}"
        lines = [
            f"Budget d'Atelier Cuisine — {label}"
            + (f" (mois en cours, au {today:%d/%m})" if current else "")
            + ".",
            f"- Dépenses : alimentaire {money(spent.alimentaire)}, maison & hygiène "
            f"{money(spent.maison)}, sorties / resto {money(spent.sorties)} ; total "
            f"{money(spent.global_)}.",
            f"- {spent.tickets} ticket(s) ; panier alimentaire moyen "
            f"{money(spent.average_basket) if spent.average_basket is not None else '∅'} ; "
            f"{spent.cooked_meals} repas cuisiné(s) à la maison, coût alimentaire par repas "
            f"{money(spent.cost_per_meal) if spent.cost_per_meal is not None else '∅'}.",
            "\nPlafonds :",
        ]
        for scope in ("global", "alimentaire", "maison", "sorties"):
            budget = budgets.get(scope)
            name = SCOPE_LABELS[scope]
            if budget is None:
                lines.append(f"- {name} : aucun plafond défini.")
                continue
            if budget.period == "mois":
                used, where = spent.of(scope), "ce mois"
            elif week is not None:
                used, where = week.of(scope), f"semaine du {week_start:%d/%m} au {week_end:%d/%m}"
            else:
                lines.append(
                    f"- {name} : {money(budget.amount)} par semaine (non comparé sur un mois passé)."
                )
                continue
            share = used / budget.amount
            rest = budget.amount - used
            state = f"reste {money(rest)}" if rest >= 0 else f"DÉPASSÉ de {money(-rest)}"
            lines.append(
                f"- {name} : {money(used)} sur {money(budget.amount)} par {budget.period} "
                f"({where}, {round(share * 100)} %) — {state}."
            )

        month_tickets = [t for t in tickets if start <= local_day(t.purchased_at) <= end]
        if month_tickets:
            rows = [
                [
                    f"{t.purchased_at.astimezone():%d/%m %H:%M}",
                    t.store_name,
                    money(t.total_amount),
                    money(t.food_subtotal),
                    money(t.home_subtotal),
                    t.items_count,
                ]
                for t in month_tickets[:31]
            ]
            lines.append(
                f"\nTickets du mois ({len(month_tickets)}) :\n"
                + markdown_table(
                    ["date", "magasin", "total", "alimentaire", "maison", "articles"], rows
                )
            )
        else:
            lines.append("\nAucun ticket archivé ce mois-ci.")
        return ToolOutput(content="\n".join(lines))


def cuisine_tools(client: CuisineClient) -> list[BaseTool[Any]]:
    """Stock, planning, courses : données du foyer non financières (lecture seule)."""
    return [StockTool(client), MealPlanTool(client), ShoppingListTool(client)]


def cuisine_budget_tools(client: CuisineClient) -> list[BaseTool[Any]]:
    """Budget et tickets : données financières (`sensitive`, modèle local imposé)."""
    return [BudgetTool(client)]
