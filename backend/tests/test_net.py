"""Applications locales jointes sans proxy (app/core/net.py).

Cas réel : sous macOS, avec le proxy de l'entreprise réglé dans le système, httpx l'appliquait
aussi à `http://127.0.0.1:8000/api` (urllib renvoie le proxy du système, pas ses exceptions) :
Atelier Viz paraissait arrêté alors qu'il tournait, et seules les apps distantes ou sans HTTP
(GitHub, Tab) restaient « en ligne ». Le proxy système est simulé ici, sans aucun réseau.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.llm.providers.ollama_provider import OllamaProvider
from app.core.net import is_loopback, use_env_proxy
from app.suite.http import NodeHttpClient
from app.tools.data_via import DataViaClient
from app.tools.http import AppClient

CORPORATE = "proxy.entreprise.example:3128"


class _Demo(AppClient):
    app = "demo"
    label = "Démo"


@pytest.fixture
def system_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy du système tel que le voit httpx sous macOS (urllib.request.getproxies)."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr(
        httpx._utils,
        "getproxies",
        lambda: {"http": CORPORATE, "https": CORPORATE},
    )


def _proxied(client: httpx.AsyncClient, url: str) -> bool:
    """Vrai si httpx enverrait `url` au proxy (transport monté pour cette adresse)."""
    return any(
        pattern.matches(httpx.URL(url)) and transport is not None
        for pattern, transport in client._mounts.items()
    )


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:8000/api", True),
        ("http://localhost:5051", True),
        ("http://LOCALHOST:5051", True),
        ("http://[::1]:3000/api", True),
        ("http://127.0.0.2:8000", True),
        ("https://api.github.com", False),
        ("https://abc.supabase.co", False),
        ("http://192.168.1.4:8000", False),
        ("http://host.docker.internal:8000/api", False),
    ],
)
def test_loopback_addresses(url: str, local: bool) -> None:
    assert is_loopback(url) is local
    assert use_env_proxy(url) is not local


def test_scheme_is_required_for_the_node_guard_but_not_for_ollama() -> None:
    # La garde des nœuds reste stricte ; OLLAMA_HOST admet `localhost:11434`
    assert not is_loopback("localhost:11434")
    assert not use_env_proxy("localhost:11434")
    assert not use_env_proxy(" 127.0.0.1:11434 ")
    assert use_env_proxy("ollama.example.com:11434")


async def test_system_proxy_would_capture_local_apps_without_the_fix(system_proxy: None) -> None:
    async with httpx.AsyncClient() as naive:  # comportement par défaut de httpx
        assert _proxied(naive, "http://127.0.0.1:8000/api/datasets")


async def test_data_via_is_reached_directly(system_proxy: None) -> None:
    client = DataViaClient("http://127.0.0.1:8000/api")
    try:
        assert client._http.trust_env is False
        assert not _proxied(client._http, "http://127.0.0.1:8000/api/datasets")
    finally:
        await client.aclose()


async def test_local_connectors_and_nodes_are_reached_directly(system_proxy: None) -> None:
    async with _Demo("http://127.0.0.1:5051/api") as savoir:
        assert not _proxied(savoir._http, "http://127.0.0.1:5051/api/notes")
    node = NodeHttpClient("viz", "Atelier Viz", "http://127.0.0.1:8000/api")
    try:
        assert not _proxied(node._http, "http://127.0.0.1:8000/api/atelier/manifest")
    finally:
        await node.aclose()


async def test_remote_apps_keep_the_system_proxy(system_proxy: None) -> None:
    async with _Demo("https://api.github.com") as github:
        assert github._http.trust_env is True
        assert _proxied(github._http, "https://api.github.com/repos")


def test_local_ollama_is_reached_directly(system_proxy: None) -> None:
    local = OllamaProvider(base_url="http://127.0.0.1:11434", default_model="m")
    bare = OllamaProvider(base_url="localhost:11434", default_model="m")  # forme OLLAMA_HOST
    remote = OllamaProvider(base_url="https://ollama.example.com", default_model="m")
    assert not _proxied(local._client._client, "http://127.0.0.1:11434/api/chat")
    assert not _proxied(bare._client._client, "http://localhost:11434/api/chat")
    assert _proxied(remote._client._client, "https://ollama.example.com/api/chat")
