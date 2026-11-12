"""Claude par le jeton du forfait (`CLAUDE_OAUTH_TOKEN`, `claude setup-token`) : docs/claude-code.md.

Sur un serveur sans session `claude`, la CLI isolée s'authentifie par le jeton. Ces tests lancent
le faux `claude` (tests/fake_claude_cli.py) en vrai sous-processus — jamais la vraie CLI — et
vérifient où le jeton va (l'environnement de la CLI, dans ce mode seulement) et où il ne va
jamais (arguments, entrée standard, réponses d'API, erreurs, autres sous-processus, fichiers).
"""

import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents import get_agent_class
from app.core.config import Settings
from app.core.llm import (
    LLMRouter,
    Message,
    ProviderNotAllowedError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderUnavailableError,
    claude_token,
    get_llm_router,
)
from app.core.llm.claude_token import (
    CLI_TOKEN_ENV,
    MASK,
    TOKEN_ENV,
    capture_token,
    scrub,
    subscription_token,
)
from app.core.llm.providers import AnthropicProvider, claude_code_provider
from app.core.llm.providers.claude_code_provider import ClaudeCodeProvider
from app.core.llm.providers.ollama_provider import OllamaProvider
from app.core.llm.types import LLMRequest
from app.core.processes import CLAUDE_WINDOWS_VARS
from app.tools.environment import ToolEnvironment
from tests.winexe import console_exe

FAKE = console_exe(str(Path(__file__).parent / "fake_claude_cli.py"))
#: Faux jeton, à la forme de ceux de `claude setup-token`
TOKEN = "sk-ant-oat01-" + "Zx9" * 20 + "-faux"
API_KEY = "sk-ant-api03-ne-doit-jamais-partir"
#: Variables qu'un lanceur de Python ou macOS ajoutent d'eux-mêmes à tout processus
PROCESS_VARS = {"__PYVENV_LAUNCHER__", "__CF_USER_TEXT_ENCODING"}


def calls(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def ask(text: str = "Salut") -> LLMRequest:
    return LLMRequest(messages=[Message.user(text)], system="Tu es concis.")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Dossier de données de Nexus (celui du `.env`) et environnement d'un serveur : une clé API,
    un réglage `CLAUDE_MODE=api`, des secrets — rien de tout cela ne doit atteindre la CLI."""
    folder = tmp_path / "donnees"
    folder.mkdir()
    monkeypatch.setattr("app.core.llm.router.env_file_path", lambda: folder / ".env")
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: FAKE)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text")
    monkeypatch.setenv("ANTHROPIC_API_KEY", API_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.exemple")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///nexus.db")
    return folder


def server_settings(**extra: Any) -> Settings:
    """Réglages du serveur (kit de déploiement) : clé API renseignée, mode « clé API »."""
    return Settings(_env_file=None, anthropic_api_key=API_KEY, claude_mode="api", **extra)  # type: ignore[call-arg]


@pytest.fixture
def token_router(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> LLMRouter:
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    return LLMRouter.from_settings(server_settings())


# ─── Lecture du jeton ─────────────────────────────────────────────


def test_token_is_read_once_then_removed_from_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, f"  {TOKEN}\n")
    token = capture_token()
    assert token is not None and token.get_secret_value() == TOKEN
    # Retiré de l'environnement du processus : aucun sous-processus n'en hérite
    assert TOKEN_ENV not in os.environ
    child = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get({TOKEN_ENV!r}))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert child.stdout.strip() == "None"
    # Lu une seule fois : une variable posée ensuite n'est ni lue ni retirée
    monkeypatch.setenv(TOKEN_ENV, "sk-ant-oat01-un-autre-jeton-plus-tard")
    assert subscription_token() is token
    assert os.environ[TOKEN_ENV] == "sk-ant-oat01-un-autre-jeton-plus-tard"
    # Jamais affiché : ni dans un repr, ni dans un message formaté
    assert TOKEN not in repr(token) and TOKEN not in f"{token}"


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_token_means_no_token(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(TOKEN_ENV, value)
    assert capture_token() is None and TOKEN_ENV not in os.environ


def test_token_is_never_a_setting(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ni dans `Settings` (donc ni affiché ni réécrit par l'écran Réglages), ni lu dans le `.env`."""
    (data_dir / ".env").write_text(f"{TOKEN_ENV}={TOKEN}\n", encoding="utf-8")
    settings = Settings(_env_file=str(data_dir / ".env"))  # type: ignore[call-arg]
    assert TOKEN not in repr(settings) and TOKEN not in settings.model_dump_json()
    assert capture_token() is None  # le fichier n'est pas une source du jeton
    from app.core.settings_editor import BY_KEY

    assert TOKEN_ENV not in BY_KEY and CLI_TOKEN_ENV not in BY_KEY


def test_startup_captures_the_token_before_anything_else(tmp_path: Path) -> None:
    """`main.py` lit le jeton à l'import, avant les réglages : après, l'environnement ne l'a plus."""
    backend = Path(__file__).resolve().parents[1]
    script = (
        "import os, main\n"
        "from app.core.llm.claude_token import subscription_token\n"
        f"print({TOKEN_ENV!r} in os.environ, subscription_token() is not None)\n"
    )
    env = {
        **os.environ,
        TOKEN_ENV: TOKEN,
        "PYTHONPATH": str(backend),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'n.db').as_posix()}",
        "TRIGGERS_ENABLED": "false",
    }
    done = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "False True"
    assert TOKEN not in done.stdout and TOKEN not in done.stderr
    source = (backend / "main.py").read_text(encoding="utf-8")
    assert source.index("capture_token()") < source.index("settings = get_settings()")


# ─── Routeur : priorité du jeton, mode inchangé sans lui ──────────


def test_token_takes_precedence_over_the_api_key(token_router: LLMRouter, data_dir: Path) -> None:
    provider = token_router.get_provider("anthropic")
    # Prioritaire sur la clé API et sur CLAUDE_MODE=api
    assert isinstance(provider, ClaudeCodeProvider) and provider.access == "token"
    assert provider.binary == FAKE and token_router.default == "anthropic"
    # Le routeur a retiré le jeton de l'environnement en le lisant
    assert TOKEN_ENV not in os.environ
    # Rien n'est créé tant que la CLI n'est pas lancée
    assert not (data_dir / "claude-forfait").exists()


def test_without_token_settings_view_is_unchanged(tmp_path: Path) -> None:
    from app.core.settings_editor import BY_KEY, TOKEN_MODE_NOTE, view

    shown = view(Settings(_env_file=None), tmp_path / ".env")  # type: ignore[call-arg]
    for field in shown.fields:
        assert field.help == BY_KEY[field.key].help and field.notice is None
    noted = view(Settings(_env_file=None), tmp_path / ".env", token_mode=True)  # type: ignore[call-arg]
    changed = [f for f, g in zip(noted.fields, shown.fields, strict=True) if f != g]
    assert [f.key for f in changed] == ["CLAUDE_MODE"]
    assert changed[0].notice == TOKEN_MODE_NOTE and changed[0].help == BY_KEY["CLAUDE_MODE"].help


def test_without_token_nothing_changes(data_dir: Path) -> None:
    keyed = LLMRouter.from_settings(server_settings())
    provider = keyed.get_provider("anthropic")
    assert isinstance(provider, AnthropicProvider) and provider.access == "api"
    by_session = LLMRouter.from_settings(Settings(_env_file=None, claude_mode="cli"))  # type: ignore[call-arg]
    cli = by_session.get_provider("anthropic")
    assert isinstance(cli, ClaudeCodeProvider) and cli.access == "cli"
    assert cli.config_error is None


async def test_without_token_the_cli_keeps_the_user_session(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mode abonnement d'aujourd'hui : dossier de l'utilisateur, `claude auth status`, et jamais
    de jeton — même si le processus en porte un sous le nom que lit la CLI."""
    monkeypatch.setenv(CLI_TOKEN_ENV, "sk-ant-oat01-jeton-ambiant-du-processus")
    monkeypatch.setenv("HOME", str(tmp_path / "chez-moi"))
    router = LLMRouter.from_settings(Settings(_env_file=None, claude_mode="cli"))  # type: ignore[call-arg]
    cli = router.get_provider("anthropic")
    assert (await cli.complete(ask())).text == "Bonjour !"
    (call,) = calls(tmp_path)
    assert call["auth"][CLI_TOKEN_ENV] is None and call["auth"][TOKEN_ENV] is None
    if sys.platform != "win32":
        assert call["auth"]["HOME"] == str(tmp_path / "chez-moi")
    assert call["auth"]["CLAUDE_CONFIG_DIR"] is None
    assert not (data_dir / "claude-forfait").exists()
    # Disponibilité : la session est vérifiée par `claude auth status`
    assert await cli.list_models() == ["sonnet", "opus", "haiku"]
    assert [c for c in calls(tmp_path) if c.get("auth_status")] != []
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "auth_off")
    with pytest.raises(ProviderUnavailableError, match="pas connecté"):
        await cli.list_models()


# ─── Lancement de la CLI en mode jeton ────────────────────────────


async def test_token_reaches_only_the_cli_environment(
    token_router: LLMRouter, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = await token_router.complete(ask(), provider="anthropic")
    assert response.text == "Bonjour !" and response.provider == "anthropic"
    (call,) = calls(tmp_path)
    home = data_dir / "claude-forfait"
    # Le jeton : dans l'environnement de la CLI, sous le nom qu'elle lit, et nulle part ailleurs
    assert call["auth"] == {
        CLI_TOKEN_ENV: TOKEN,
        TOKEN_ENV: None,
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
    }
    assert all(TOKEN not in arg for arg in call["args"]) and TOKEN not in call["stdin"]
    assert TOKEN not in response.model_dump_json()
    # La clé API du processus n'est jamais transmise à la CLI
    assert call["env"] == {
        "ANTHROPIC_API_KEY": None,
        "ANTHROPIC_BASE_URL": None,
        "ANTHROPIC_AUTH_TOKEN": None,
    }
    assert API_KEY not in json.dumps(call)
    # Liste blanche de SUITE.md §5.3 (Windows §9.6) + le jeton : rien d'autre
    allowed = {n.upper() for n in (*claude_code_provider.CLI_ENV, *CLAUDE_WINDOWS_VARS)}
    allowed |= {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", CLI_TOKEN_ENV}
    leaked = [
        n
        for n in call["env_names"]
        if n.upper() not in allowed
        and not n.upper().startswith("LC_")
        and n.upper() not in PROCESS_VARS
    ]
    assert leaked == [], leaked
    assert call["cwd_empty"] and "## Utilisateur\nSalut" in call["stdin"]
    # Dossier privé créé sous le dossier de données, lisible par ce seul utilisateur
    assert home.is_dir() and (home / ".claude").is_dir()
    if sys.platform != "win32":
        assert stat.S_IMODE(home.stat().st_mode) == 0o700
        assert stat.S_IMODE((home / ".claude").stat().st_mode) == 0o700
    # Le jeton n'est écrit dans aucun fichier du dossier de données
    for path in data_dir.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace")


async def test_isolation_flags_are_exactly_those_of_the_session_mode(
    token_router: LLMRouter, tmp_path: Path
) -> None:
    """Mêmes arguments, au caractère près, avec et sans jeton (SUITE.md §5.3)."""
    by_session = ClaudeCodeProvider(binary=FAKE, default_model="sonnet", timeout=10)
    await token_router.complete(ask(), provider="anthropic")
    await by_session.complete(ask())
    with_token, without = calls(tmp_path)
    assert with_token["args"] == without["args"]
    args = with_token["args"]
    for flag in (
        "-p",
        "--safe-mode",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--max-turns") + 1] == "2"
    assert with_token["stdin"] == without["stdin"]


async def test_availability_is_binary_plus_token_without_auth_status(
    token_router: LLMRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Une session absente ferait échouer `claude auth status` : il n'est pas lancé
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "auth_off")
    claude = next(s for s in await token_router.status() if s.name == "anthropic")
    assert claude.configured and claude.available and claude.error is None
    assert claude.access == "token" and claude.models == ["sonnet", "opus", "haiku"]
    assert calls(tmp_path) == []
    ollama = next(s for s in await token_router.status() if s.name == "ollama")
    assert ollama.access is None


@pytest.fixture
def api(token_router: LLMRouter) -> Iterator[TestClient]:
    from main import app

    app.dependency_overrides[get_llm_router] = lambda: token_router
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_says_the_mode_and_never_returns_the_token(api: TestClient) -> None:
    providers = api.get("/api/llm/providers")
    assert providers.status_code == 200
    claude = next(p for p in providers.json() if p["name"] == "anthropic")
    assert claude["access"] == "token" and claude["available"] is True
    settings = api.get("/api/settings")
    assert settings.status_code == 200
    fields = {f["key"]: f for f in settings.json()["fields"]}
    assert TOKEN_ENV not in fields and CLI_TOKEN_ENV not in fields
    # Le réglage « Accès à Claude » dit qu'il est sans effet (le jeton l'emporte)
    assert fields["CLAUDE_MODE"]["notice"].startswith("Sans effet sur ce serveur")
    assert [k for k, f in fields.items() if f["notice"]] == ["CLAUDE_MODE"]
    for response in (providers, settings):
        assert TOKEN not in response.text and "sk-ant-oat" not in response.text
    # Pas modifiable depuis l'interface (liste blanche des Réglages)
    refused = api.put("/api/settings", json={"values": {TOKEN_ENV: "sk-ant-oat01-autre"}})
    assert refused.status_code == 422


def test_api_error_of_a_refused_token_has_no_secret(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "echo")
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Bonjour"}]}],
        "provider": "anthropic",
    }
    response = api.post("/api/agents/assistant/run", json=body)
    assert response.status_code >= 400
    assert TOKEN not in response.text and MASK in response.text


# ─── Erreurs en français, sans secret ─────────────────────────────


@pytest.mark.parametrize("mode", ["login", "expired"])
async def test_refused_or_expired_token(
    token_router: LLMRouter, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(ProviderRequestError) as caught:
        await token_router.complete(ask(), provider="anthropic")
    message = str(caught.value)
    assert "refusé ou expiré" in message and "claude setup-token" in message
    assert "jeton du serveur" in message and TOKEN_ENV in message
    assert TOKEN not in message


async def test_subscription_limit_repeats_the_cli_message(
    token_router: LLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    # Transitoire : le repli vers Ollama reste possible
    with pytest.raises(ProviderUnavailableError) as caught:
        await token_router.complete(ask(), provider="anthropic")
    message = str(caught.value)
    assert "Limite du forfait Claude atteinte" in message
    assert "Claude AI usage limit reached" in message  # message de la CLI repris
    assert "partagé entre les applications" in message and TOKEN not in message


@pytest.mark.parametrize("mode", ["echo", "crash"])
async def test_a_cli_error_that_repeats_the_token_is_masked(
    token_router: LLMRouter, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """La CLI répète le jeton reçu (réponse JSON, ou sortie d'erreur coupée en plein jeton)."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(ProviderRequestError) as caught:
        await token_router.complete(ask(), provider="anthropic")
    message = str(caught.value)
    assert TOKEN not in message and TOKEN[:24] not in message and "sk-ant" not in message
    # Masqué avant la coupe du message (en mode `crash`, la coupe tombe dans le masque lui-même)
    assert MASK[:6] in message and (mode == "crash" or MASK in message)


def test_scrub_masks_the_token_and_any_anthropic_secret() -> None:
    from pydantic import SecretStr

    text = f"a {TOKEN} b sk-ant-api03-AbCdEfGh1234 c"
    assert scrub(text, SecretStr(TOKEN)) == f"a {MASK} b {MASK} c"
    assert scrub("jeton maison-123 ici", SecretStr("maison-123")) == f"jeton {MASK} ici"
    assert scrub("rien à masquer", None) == "rien à masquer"


async def test_cli_missing_from_the_image(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.llm.router.find_claude_binary", lambda *_: None)
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    router = LLMRouter.from_settings(server_settings())
    # Jamais de repli silencieux sur la clé API (facturée à l'usage) : Claude est « non
    # configuré », avec la raison ; le moteur local répond par défaut
    assert router.default == "ollama"
    with pytest.raises(ProviderNotConfiguredError, match="absent de ce serveur"):
        router.get_provider("anthropic")
    claude = next(s for s in await router.status() if s.name == "anthropic")
    assert not claude.configured and not claude.available and claude.access == "token"
    assert claude.error is not None and "absent de ce serveur" in claude.error
    assert "CLAUDE_CLI_PATH" in claude.error and TOKEN not in claude.error
    assert calls(tmp_path) == []


def test_token_mode_needs_a_private_home() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="dossier privé"):
        ClaudeCodeProvider(binary=FAKE, token=SecretStr(TOKEN))


# ─── Garde-fous du dépôt inchangés ────────────────────────────────


async def test_sensitive_agents_stay_on_ollama_and_never_launch_the_cli(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le jeton ne change rien au verrou local : Finance, Comptable et Tuteur refusent Claude,
    et la CLI n'est pas lancée."""
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    settings = server_settings()
    claude = LLMRouter.from_settings(settings).get_provider("anthropic")
    router = LLMRouter(
        {"anthropic": claude, "ollama": OllamaProvider(base_url="http://x", default_model="m")},
        default="anthropic",
    )
    for name in ("finance", "comptable", "tuteur"):
        agent = get_agent_class(name)(router, ToolEnvironment(settings))
        assert agent.local_only
        with pytest.raises(ProviderNotAllowedError):
            await agent.run([Message.user("Mon solde ?")], provider="anthropic")
    assert calls(tmp_path) == []


def test_module_keeps_no_token_between_tests() -> None:
    """Garde de `conftest` : chaque test repart sans jeton lu (ni celui de la machine)."""
    assert claude_token._captured is None and TOKEN_ENV not in os.environ
