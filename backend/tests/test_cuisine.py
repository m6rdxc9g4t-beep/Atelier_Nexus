"""Connecteur Atelier Cuisine (Supabase : PostgREST + Auth), en lecture seule.

Supabase simulé par httpx.MockTransport (jamais de vrai réseau) : authentification par mot de
passe ou jeton de rafraîchissement, rotation des jetons (un jeton déjà utilisé est refusé),
jeton d'accès expiré (401), filtres PostgREST appliqués comme le ferait le serveur.
Données : fixtures au format exact des tables déployées (schéma vérifié le 2026-10-20),
contenu de démonstration (aucune donnée réelle du foyer).
"""

import base64
import json
import stat
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agents.registry import get_agent_class
from app.core.config import Settings
from app.core.settings_editor import SettingsError, SettingsUpdate, validate_changes
from app.tools import ToolContext
from app.tools.cuisine import (
    CuisineClient,
    SessionStore,
    anon_key_problem,
    cuisine_budget_tools,
    cuisine_tools,
    supabase_url_problem,
)
from app.tools.environment import ToolEnvironment
from app.tools.http import AppNotConfiguredError
from app.tools.toolsets import build_tools, get_toolset
from tests.fakes import ScriptedProvider, make_router

FIX = Path(__file__).parent / "fixtures" / "cuisine"
URL = "https://cuisine.supabase.test"
ANON = "sb_publishable_test-cle-publique"
TODAY = date(2026, 10, 20)  # un mardi
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC).timestamp()


def fixture(name: str) -> Any:
    return json.loads((FIX / f"{name}.json").read_text())


def by_name(tools: list[Any]) -> dict[str, Any]:
    return {t.name: t for t in tools}


def jwt(payload: dict[str, Any]) -> str:
    part = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{part}.signature"


@pytest.fixture(autouse=True)
def _fresh_sessions() -> None:
    SessionStore.clear_memory()


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def _value(raw: str) -> Any:
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return raw


class FakeSupabase:
    """Supabase minimal : Auth (rotation des jetons) + PostgREST (filtres eq/gte/lte/lt/is)."""

    TABLES = ("aisles", "pantry_items", "meals", "shopping_items", "shopping_sessions", "budgets")

    def __init__(self, clock: Clock, *, password: str = "mot-de-passe") -> None:
        self.clock = clock
        self.password = password
        self.requests: list[httpx.Request] = []
        self.grants: list[str] = []
        self.access: dict[str, float] = {}  # jeton d'accès → expiration
        self.refresh: dict[str, bool] = {"rt-initial": True}  # jeton → encore valable
        self.issued = 0

    def _issue(self) -> httpx.Response:
        self.issued += 1
        access, refresh = f"at-{self.issued}", f"rt-{self.issued}"
        self.access[access] = self.clock.now + 3600
        self.refresh[refresh] = True
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "token_type": "bearer",
                "expires_in": 3600,
                "expires_at": int(self.clock.now + 3600),
                "refresh_token": refresh,
                "user": {"id": "u-foyer", "email": "foyer@example.org", "role": "authenticated"},
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["apikey"] == ANON  # la clé publique part toujours
        path = request.url.path
        if request.method == "POST" and path == "/auth/v1/token":
            grant = request.url.params["grant_type"]
            self.grants.append(grant)
            body = json.loads(request.content)
            if grant == "password":
                if body != {"email": "foyer@example.org", "password": self.password}:
                    return httpx.Response(
                        400,
                        json={"code": 400, "error_code": "invalid_credentials",
                              "msg": "Invalid login credentials"},
                    )  # fmt: skip
                return self._issue()
            token = body.get("refresh_token")
            if not self.refresh.get(token):
                return httpx.Response(
                    400,
                    json={"code": 400, "error_code": "refresh_token_already_used",
                          "msg": "Invalid Refresh Token: Already Used"},
                )  # fmt: skip
            self.refresh[token] = False  # rotation : un jeton ne sert qu'une fois
            return self._issue()
        if request.method == "GET" and path.startswith("/rest/v1/"):
            table = path.removeprefix("/rest/v1/")
            auth = request.headers.get("authorization", "")
            token = auth.removeprefix("Bearer ")
            if self.access.get(token, 0) <= self.clock.now:
                return httpx.Response(
                    401, json={"code": "PGRST303", "message": "JWT expired", "hint": None}
                )
            if table not in self.TABLES:
                return httpx.Response(404, json={"code": "PGRST205", "message": "table inconnue"})
            return httpx.Response(200, json=self._filter(fixture(table), request))
        return httpx.Response(404, json={"message": "introuvable"})

    @staticmethod
    def _filter(rows: list[dict[str, Any]], request: httpx.Request) -> list[dict[str, Any]]:
        columns = request.url.params["select"].split(",")
        for key, raw in request.url.params.multi_items():
            if key in {"select", "order"}:
                continue
            op, arg = raw.split(".", 1)
            if op == "is":
                rows = [
                    r for r in rows if r[key] is {"true": True, "false": False, "null": None}[arg]
                ]
                continue
            target = _value(arg)
            compare = {
                "eq": lambda a, b: a == b,
                "gte": lambda a, b: a >= b,
                "lte": lambda a, b: a <= b,
                "lt": lambda a, b: a < b,
            }[op]
            rows = [r for r in rows if r[key] is not None and compare(_value(r[key]), target)]
        # Comme PostgREST : seules les colonnes demandées reviennent
        return [{c: r[c] for c in columns if c in r} for r in rows]

    def selects(self, table: str) -> list[str]:
        return [r.url.params["select"] for r in self.requests if r.url.path == f"/rest/v1/{table}"]


def make_client(fake: FakeSupabase, clock: Clock, tmp_path: Path, **kw: Any) -> CuisineClient:
    kw.setdefault("email", "foyer@example.org")
    kw.setdefault("password", "mot-de-passe")
    return CuisineClient(
        URL,
        anon_key=ANON,
        sessions=SessionStore(tmp_path / "cuisine-session.json"),
        transport=httpx.MockTransport(fake),
        clock=clock,
        today=lambda: TODAY,
        **kw,
    )


@pytest.fixture
def cuisine(tmp_path: Path) -> tuple[CuisineClient, FakeSupabase, Clock]:
    clock = Clock()
    fake = FakeSupabase(clock)
    return make_client(fake, clock, tmp_path), fake, clock


# ═══ Outils ═══════════════════════════════════════════════════════


async def test_stock_puts_urgent_first_and_never_asks_prices(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock],
) -> None:
    client, fake, _ = cuisine
    tools = by_name(cuisine_tools(client))
    assert set(tools) == {"cuisine_stock", "cuisine_meal_plan", "cuisine_shopping_list"}
    assert not any(t.sensitive or t.requires_approval for t in tools.values())

    out = await tools["cuisine_stock"].invoke({}, ToolContext())
    assert not out.is_error, out.content
    text = out.content
    assert text.startswith("7 produit(s) en stock au 20/10/2026")
    urgent = text.split("À finir en premier (4, dont 1 périmé(s)) :")[1].split("\n\n")[0]
    # Du plus urgent au moins urgent ; les restes mis en boîte passent avant à date égale
    assert (
        urgent.index("Yaourts nature") < urgent.index("Restes de gratin") < urgent.index("Jambon")
    )
    assert "Yaourts nature (Frigo, 2) : périmé depuis 2 jours" in urgent
    assert (
        "Restes de gratin (Frigo, —) : à consommer aujourd'hui — mis en boîte le 18/10 ; Pour 2"
        in urgent
    )
    assert "Jambon (Frigo, 4 tranches) : demain" in urgent
    assert "Tomates cerises (Corbeille, Moitié) : dans 3 jours" in urgent
    assert "Petits pois" not in urgent
    assert "Presque finis (à racheter ?) : Pâtes (presque fini)." in text
    assert (
        "| Petits pois | Congélateur | 🍟 Surgelés / plats rapides | 1 sachet | le 01/03/2027 |"
        in text
    )
    # Lecture minimale : jamais le prix d'achat
    assert all("price" not in s for s in fake.selects("pantry_items"))

    frigo = await tools["cuisine_stock"].invoke({"location": "maison"}, ToolContext())
    assert (
        frigo.content.startswith("1 produit(s) en stock") and "Liquide vaisselle" in frigo.content
    )
    assert "Rien n'arrive à échéance d'ici 3 jour(s)." in frigo.content


async def test_meal_plan_defaults_to_current_week(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock],
) -> None:
    client, fake, _ = cuisine
    out = await by_name(cuisine_tools(client))["cuisine_meal_plan"].invoke({}, ToolContext())
    text = out.content
    assert text.startswith(
        "Repas du 19/10/2026 au 25/10/2026 : 4 au planning (2 à cuisiner, 1 cuisiné(s), 1 à l'extérieur)."
    )
    today = text.split("Mardi 20 octobre (aujourd'hui) :")[1].split("\n\n")[0]
    # Ordre des créneaux, pas ordre alphabétique
    assert today.index("Déjeuner : Burger frites (assemblage rapide, prévu)") < today.index(
        "Dîner : Restes de gratin (libre, prévu)"
    )
    assert "— Pain à décongeler la veille" in today
    assert (
        "Lundi 19 octobre (hier) :\n- Dîner : Nouilles sautées crevettes (recette, 2 pers., cuisiné)"
        in text
    )
    assert "Rien de prévu : Mercredi 21 octobre (demain), Vendredi 23 octobre" in text
    request = next(r for r in fake.requests if r.url.path == "/rest/v1/meals")
    assert request.url.params.get_list("eaten_on") == ["gte.2026-10-19", "lte.2026-10-25"]
    assert "external_cost" not in request.url.params["select"]  # coût des sorties : outil Budget
    assert "46" not in text

    month = await by_name(cuisine_tools(client))["cuisine_meal_plan"].invoke(
        {"start": "2026-10-01", "days": 31}, ToolContext()
    )
    assert "Crêpes (recette, 4 pers., cuisiné)" in month.content and "Pizza" not in month.content


async def test_shopping_list_by_aisle_without_prices(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock],
) -> None:
    client, fake, _ = cuisine
    tool = by_name(cuisine_tools(client))["cuisine_shopping_list"]
    out = await tool.invoke({}, ToolContext())
    text = out.content
    assert text.startswith("3 article(s) à acheter, sur 3 rayon(s).")
    # Rayons dans l'ordre du foyer (3 → 4 → 11), quel que soit l'ordre de saisie
    assert text.index("🧀 Produits frais") < text.index("🥖 Féculents") < text.index("🧽 Entretien")
    assert "- Lait demi-écrémé (6 L) — pour un repas prévu" in text
    assert "- Pâtes (500 g) — à racheter" in text
    assert "- Éponges — ajout manuel ; les vertes" in text
    assert "Pain de mie" not in text
    first = next(r for r in fake.requests if r.url.path == "/rest/v1/shopping_items")
    assert first.url.params["checked"] == "is.false"
    assert "price" not in first.url.params["select"]

    everything = await tool.invoke({"include_checked": True}, ToolContext())
    assert "3 article(s) à acheter, 1 déjà coché(s)" in everything.content
    assert "- [x] Pain de mie — repris d'un ticket" in everything.content


async def test_budget_of_the_month_is_sensitive_and_matches_cuisine_rules(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock],
) -> None:
    client, fake, _ = cuisine
    tool = by_name(cuisine_budget_tools(client))["cuisine_budget"]
    assert tool.sensitive and not tool.requires_approval

    out = await tool.invoke({}, ToolContext())
    assert not out.is_error, out.content
    text = out.content
    assert text.startswith("Budget d'Atelier Cuisine — octobre 2026 (mois en cours, au 20/10).")
    # Alimentaire = rayons 1-9 des tickets ; Sorties = repas extérieurs (même prévus) du mois
    assert (
        "- Dépenses : alimentaire 127.60 €, maison & hygiène 20.30 €, sorties / resto 65.40 € ; "
        "total 213.30 €." in text
    )
    assert "3 ticket(s) ; panier alimentaire moyen 42.53 €" in text
    assert "2 repas cuisiné(s) à la maison, coût alimentaire par repas 63.80 €" in text
    assert "- Global : aucun plafond défini." in text
    assert (
        "- Alimentaire : 127.60 € sur 400.00 € par mois (ce mois, 32 %) — reste 272.40 €." in text
    )
    assert (
        "- Sorties / resto : 65.40 € sur 60.00 € par mois (ce mois, 109 %) — DÉPASSÉ de 5.40 €."
        in text
    )
    # Budget hebdomadaire : la semaine en cours (ticket Lidl du 19/10)
    assert (
        "- Maison & hygiène : 8.00 € sur 15.00 € par semaine (semaine du 19/10 au 25/10, 53 %) "
        "— reste 7.00 €." in text
    )
    assert (
        "Tickets du mois (3)" in text and "| Carrefour | 86.40 € | 74.10 € | 12.30 € | 23 |" in text
    )
    assert "55.00 €" not in text  # ticket de septembre exclu
    sessions = next(r for r in fake.requests if r.url.path == "/rest/v1/shopping_sessions")
    assert "raw_text" not in sessions.url.params["select"]  # jamais le texte brut du ticket
    since, until = sessions.url.params.get_list("purchased_at")
    assert since.startswith("gte.2026-10-01T00:00:00") and until.startswith(
        "lt.2026-11-01T00:00:00"
    )


async def test_budget_of_a_past_month(cuisine: tuple[CuisineClient, FakeSupabase, Clock]) -> None:
    client, _, _ = cuisine
    tool = by_name(cuisine_budget_tools(client))["cuisine_budget"]
    out = await tool.invoke({"month": "2026-09"}, ToolContext())
    assert out.content.startswith("Budget d'Atelier Cuisine — septembre 2026.")
    assert "alimentaire 50.00 €" in out.content and "1 repas cuisiné(s)" in out.content
    assert (
        "- Maison & hygiène : 15.00 € par semaine (non comparé sur un mois passé)." in out.content
    )
    bad = await tool.invoke({"month": "2026-13"}, ToolContext())
    assert bad.is_error and "Paramètres invalides" in bad.content


# ═══ Session Supabase ═════════════════════════════════════════════


async def test_session_is_kept_renewed_and_persisted_without_password(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock], tmp_path: Path
) -> None:
    client, fake, clock = cuisine
    stock = by_name(cuisine_tools(client))["cuisine_stock"]
    await stock.invoke({}, ToolContext())
    await stock.invoke({}, ToolContext())
    assert fake.grants == ["password"]  # une seule connexion pour plusieurs lectures

    clock.now += 3600  # jeton d'accès expiré : renouvelé, pas de nouvelle connexion
    assert not (await stock.invoke({}, ToolContext())).is_error
    assert fake.grants == ["password", "refresh_token"]

    path = tmp_path / "cuisine-session.json"
    if sys.platform != "win32":  # Windows : droits du profil, pas de mode Unix
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    saved = path.read_text()
    assert "rt-2" in saved and "mot-de-passe" not in saved and "foyer@example.org" not in saved

    # Redémarrage de Nexus : la session du fichier est reprise (jeton tourné), sans mot de passe
    SessionStore.clear_memory()
    clock.now += 3600
    again = make_client(fake, clock, tmp_path)
    assert not (
        await by_name(cuisine_tools(again))["cuisine_stock"].invoke({}, ToolContext())
    ).is_error
    assert fake.grants == ["password", "refresh_token", "refresh_token"]


async def test_refresh_token_mode_follows_rotation(tmp_path: Path) -> None:
    clock = Clock()
    fake = FakeSupabase(clock)
    client = make_client(
        fake, clock, tmp_path, email=None, password=None, refresh_token="rt-initial"
    )
    assert not (
        await by_name(cuisine_tools(client))["cuisine_stock"].invoke({}, ToolContext())
    ).is_error
    assert fake.refresh["rt-initial"] is False  # consommé par Supabase

    # Redémarrage après expiration : le jeton tourné du fichier sert, jamais l'initial (déjà utilisé)
    SessionStore.clear_memory()
    clock.now += 7200
    again = make_client(
        fake, clock, tmp_path, email=None, password=None, refresh_token="rt-initial"
    )
    out = await by_name(cuisine_tools(again))["cuisine_meal_plan"].invoke({}, ToolContext())
    assert not out.is_error, out.content

    # Session perdue (fichier supprimé) : le jeton initial est refusé, message clair
    SessionStore.clear_memory()
    (tmp_path / "cuisine-session.json").unlink()
    lost = make_client(fake, clock, tmp_path, email=None, password=None, refresh_token="rt-initial")
    out = await by_name(cuisine_tools(lost))["cuisine_stock"].invoke({}, ToolContext())
    assert out.is_error and "Session Atelier Cuisine expirée ou révoquée" in out.content
    assert "rt-" not in out.content


async def test_revoked_access_token_is_renewed_once(
    cuisine: tuple[CuisineClient, FakeSupabase, Clock],
) -> None:
    client, fake, _ = cuisine
    tool = by_name(cuisine_tools(client))["cuisine_shopping_list"]
    await tool.invoke({}, ToolContext())
    fake.access.clear()  # révoqué côté serveur avant son expiration
    out = await tool.invoke({}, ToolContext())
    assert not out.is_error
    assert fake.grants == ["password", "refresh_token"]


async def test_wrong_password_is_a_clear_error(tmp_path: Path) -> None:
    clock = Clock()
    fake = FakeSupabase(clock, password="autre")
    client = make_client(fake, clock, tmp_path)
    out = await by_name(cuisine_tools(client))["cuisine_stock"].invoke({}, ToolContext())
    assert out.is_error
    assert "Connexion à Atelier Cuisine refusée" in out.content and "Réglages" in out.content
    assert "mot-de-passe" not in out.content
    assert not (tmp_path / "cuisine-session.json").exists()


async def test_offline_machine_is_reported() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known")

    client = CuisineClient(
        URL, anon_key=ANON, email="foyer@example.org", password="x",
        transport=httpx.MockTransport(down),
    )  # fmt: skip
    out = await by_name(cuisine_tools(client))["cuisine_stock"].invoke({}, ToolContext())
    assert out.is_error and "vérifiez la connexion Internet" in out.content


# ═══ Configuration et garde-fous ══════════════════════════════════


def test_only_the_public_key_is_accepted() -> None:
    assert anon_key_problem(ANON) is None
    assert anon_key_problem(jwt({"role": "anon", "ref": "x"})) is None
    assert "refusée" in (anon_key_problem(jwt({"role": "service_role"})) or "")
    assert "refusée" in (anon_key_problem("sb_secret_abc") or "")
    assert anon_key_problem("a.%%%.c") == "clé JWT illisible"

    assert supabase_url_problem("https://abcd.supabase.co") is None
    assert supabase_url_problem("http://127.0.0.1:54321") is None  # Supabase local
    assert "HTTPS" in (supabase_url_problem("http://abcd.supabase.co") or "")
    assert "sans /rest/v1" in (supabase_url_problem("https://abcd.supabase.co/rest/v1") or "")

    with pytest.raises(AppNotConfiguredError, match="service_role"):
        CuisineClient(URL, anon_key=jwt({"role": "service_role"}), email="a@b.c", password="x")
    with pytest.raises(AppNotConfiguredError, match="e-mail et le mot de passe"):
        CuisineClient(URL, anon_key=ANON, email="a@b.c")


def test_settings_editor_validates_cuisine_fields() -> None:
    current = Settings(_env_file=None)  # type: ignore[call-arg]
    ok = validate_changes(
        SettingsUpdate(
            values={
                "CUISINE_SUPABASE_URL": "https://abcd.supabase.co",
                "CUISINE_SUPABASE_ANON_KEY": ANON,
                "CUISINE_EMAIL": "foyer@example.org",
                "CUISINE_PASSWORD": "secret",
            }
        ),
        current,
    )
    assert ok["CUISINE_EMAIL"] == "foyer@example.org"
    with pytest.raises(SettingsError) as exc:
        validate_changes(
            SettingsUpdate(
                values={
                    "CUISINE_SUPABASE_ANON_KEY": "sb_secret_xyz",
                    "CUISINE_SUPABASE_URL": "http://abcd.supabase.co",
                    "CUISINE_EMAIL": "pas-un-email",
                }
            ),
            current,
        )
    assert set(exc.value.fields) == {
        "CUISINE_SUPABASE_ANON_KEY",
        "CUISINE_SUPABASE_URL",
        "CUISINE_EMAIL",
    }


def test_toolsets_need_full_configuration(tmp_path: Path) -> None:
    assert not get_toolset("cuisine").sensitive and get_toolset("cuisine_budget").sensitive
    assert not get_toolset("cuisine").writes and not get_toolset("cuisine_budget").writes

    bare = ToolEnvironment(Settings(_env_file=None))  # type: ignore[call-arg]
    tools, unavailable = build_tools(["cuisine", "cuisine_budget"], bare)
    assert tools == [] and [u.id for u in unavailable] == ["cuisine", "cuisine_budget"]

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        cuisine_supabase_url=URL,
        cuisine_supabase_anon_key=jwt({"role": "service_role"}),
        cuisine_email="foyer@example.org",
        cuisine_password="x",
        cuisine_session_file=str(tmp_path / "s.json"),
    )
    tools, unavailable = build_tools(["cuisine"], ToolEnvironment(settings))
    assert tools == [] and "service_role" in unavailable[0].reason

    good = settings.model_copy(update={"cuisine_supabase_anon_key": Settings(  # type: ignore[call-arg]
        _env_file=None, cuisine_supabase_anon_key=ANON).cuisine_supabase_anon_key})  # fmt: skip
    tools, unavailable = build_tools(["cuisine", "cuisine_budget"], ToolEnvironment(good))
    assert unavailable == [] and [t.name for t in tools] == [
        "cuisine_stock", "cuisine_meal_plan", "cuisine_shopping_list", "cuisine_budget",
    ]  # fmt: skip


async def test_finance_reads_cuisine_budget(tmp_path: Path) -> None:
    clock = Clock()
    fake = FakeSupabase(clock)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        cuisine_supabase_url=URL,
        cuisine_supabase_anon_key=ANON,
        cuisine_email="foyer@example.org",
        cuisine_password="mot-de-passe",
        cuisine_session_file=str(tmp_path / "s.json"),
    )
    env = ToolEnvironment(settings, transports={"cuisine": httpx.MockTransport(fake)})
    router = make_router(ScriptedProvider("anthropic"), ScriptedProvider("ollama"))

    finance = get_agent_class("finance")(router, env)
    assert finance.local_only and "cuisine_budget" in finance.tools
    await env.aclose()


def test_apps_status_reads_supabase_never_vercel(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_env_factory
    from main import app

    clock = Clock()
    fake = FakeSupabase(clock)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        github_repo=None,
        data_via_base_url=None,
        projets_base_url=None,
        tresorerie_base_url=None,
        cine_base_url=None,
        savoir_base_url=None,
        tab_exports_dir=None,
        cuisine_supabase_url=URL,
        cuisine_supabase_anon_key=ANON,
        cuisine_email="foyer@example.org",
        cuisine_password="mot-de-passe",
        cuisine_session_file=str(tmp_path / "s.json"),
    )

    def env_factory() -> ToolEnvironment:
        return ToolEnvironment(settings, transports={"cuisine": httpx.MockTransport(fake)})

    app.dependency_overrides[get_env_factory] = lambda: env_factory
    try:
        status = {a["id"]: a for a in TestClient(app).get("/api/apps/status").json()}
    finally:
        app.dependency_overrides.clear()
    cuisine = status["cuisine"]
    assert cuisine["label"] == "Atelier Cuisine" and cuisine["available"] is True
    assert cuisine["base_url"] == URL
    assert (
        cuisine["detail"].startswith("7 produit(s) en stock, ")
        and "(en ligne)" in cuisine["detail"]
    )
    assert {r.url.host for r in fake.requests} == {"cuisine.supabase.test"}
