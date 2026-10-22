"""Réglages depuis l'interface (Étape 11) : lecture sans secret, écriture du .env qui
préserve le fichier, validation, rechargement à chaud, origine contrôlée."""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.llm.router import get_llm_router
from app.core.settings_editor import FIELDS, read_env_file, write_env_file
from main import app

KEYS = [f.key for f in FIELDS]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.chdir(tmp_path)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "# Mon fichier, commentaires gardés\nOLLAMA_MODEL=qwen2.5:7b\n# ANTHROPIC_API_KEY=ancienne\nDATABASE_URL=sqlite+aiosqlite://\n"
    )
    get_settings.cache_clear()
    get_llm_router.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()
    get_llm_router.cache_clear()


def field(body: dict, key: str) -> dict:
    return next(f for f in body["fields"] if f["key"] == key)


def test_read_never_returns_secrets(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-secret-1234\n")
    get_settings.cache_clear()
    body = client.get("/api/settings").json()
    key = field(body, "ANTHROPIC_API_KEY")
    assert key["configured"] and key["value"] is None and key["hint"] == "…1234"
    assert "sk-ant-secret" not in str(body)
    assert field(body, "OLLAMA_MODEL")["source"] == "défaut"
    assert body["env_file"] == str(tmp_path / ".env")


def test_update_writes_env_and_reloads(client: TestClient, tmp_path: Path) -> None:
    before = get_llm_router()
    assert before.default == "ollama"  # sans clé
    response = client.put(
        "/api/settings",
        json={"values": {"ANTHROPIC_API_KEY": "sk-ant-nouvelle-cle-9876", "OLLAMA_MODEL": "gemma3:12b",
                         "CINE_BASE_URL": "http://127.0.0.1:47321/api", "GITHUB_REPO": ""}},
    )  # fmt: skip
    assert response.status_code == 200, response.text
    body = response.json()
    assert field(body, "ANTHROPIC_API_KEY")["hint"] == "…9876"
    assert (
        field(body, "OLLAMA_MODEL")["value"] == "gemma3:12b"
        and field(body, "OLLAMA_MODEL")["source"] == "fichier"
    )

    text = (tmp_path / ".env").read_text()
    assert text.startswith("# Mon fichier, commentaires gardés\nOLLAMA_MODEL=gemma3:12b\n")
    assert "# ANTHROPIC_API_KEY=ancienne" in text and "DATABASE_URL=sqlite+aiosqlite://" in text
    assert "ANTHROPIC_API_KEY=sk-ant-nouvelle-cle-9876" in text and "GITHUB_REPO" not in text
    if sys.platform != "win32":  # Windows : droits du profil, pas de mode Unix
        assert oct(os.stat(tmp_path / ".env").st_mode & 0o777) == "0o600"

    after = get_llm_router()
    assert after is not before and after.default == "anthropic"  # clé prise en compte à chaud
    assert get_settings().cine_base_url == "http://127.0.0.1:47321/api"


def test_invalid_values_are_refused_and_file_untouched(client: TestClient, tmp_path: Path) -> None:
    original = (tmp_path / ".env").read_text()
    for values, key in [
        ({"OLLAMA_BASE_URL": "localhost:11434"}, "OLLAMA_BASE_URL"),
        ({"LLM_DEFAULT_PROVIDER": "gpt"}, "LLM_DEFAULT_PROVIDER"),
        (
            {"TAB_MCP_COMMAND": "rm -rf ~"},
            "TAB_MCP_COMMAND",
        ),  # commande : jamais depuis l'interface
        ({"DATABASE_URL": "sqlite://"}, "DATABASE_URL"),
        ({"ANTHROPIC_MODEL": "a\nANTHROPIC_API_KEY=x"}, "ANTHROPIC_MODEL"),
    ]:
        response = client.put("/api/settings", json={"values": values})
        assert response.status_code == 422, values
        assert key in response.json()["error"]["fields"]
    assert (tmp_path / ".env").read_text() == original


def test_foreign_origin_is_refused(client: TestClient) -> None:
    assert client.get("/api/settings", headers={"Origin": "https://exemple.com"}).status_code == 403
    assert (
        client.put(
            "/api/settings",
            json={"values": {"OLLAMA_MODEL": "x"}},
            headers={"Origin": "http://evil.localhost"},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/settings", headers={"Origin": "http://localhost:3100"}).status_code == 200
    )
    # Application de bureau : même origine que le serveur
    assert client.get("/api/settings", headers={"Origin": "http://testserver"}).status_code == 200


def test_environment_variables_win_and_are_reported(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "impose")
    get_settings.cache_clear()
    f = field(client.get("/api/settings").json(), "OLLAMA_MODEL")
    assert f["source"] == "environnement" and f["value"] == "impose"


def test_env_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / ".env"
    write_env_file(path, {"GITHUB_ALLOWED_REPOS": "moi/a, moi/b", "ANTHROPIC_MODEL": 'claude "x"'})
    assert read_env_file(path) == {
        "GITHUB_ALLOWED_REPOS": "moi/a, moi/b",
        "ANTHROPIC_MODEL": 'claude "x"',
    }
    write_env_file(path, {"ANTHROPIC_MODEL": None})
    assert read_env_file(path) == {"GITHUB_ALLOWED_REPOS": "moi/a, moi/b"}
