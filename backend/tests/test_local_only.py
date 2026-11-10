"""Garde des requêtes locales (`app/api/local_only.py`) : Host et Origin contrôlés avant tout.

Un site visité dans le navigateur ne doit ni lire l'API (DNS rebinding : Host étranger), ni
valider une action à la place de l'utilisateur (Origin étrangère sur une écriture).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.local_only import allowed_hosts, host_name, origin_host, refusal
from app.core.config import get_settings
from main import app

HOSTS = allowed_hosts(["https://nexus.exemple.fr", "http://localhost:3100"], ["nexus.lan"])


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("value", "name"),
    [
        ("127.0.0.1:8100", "127.0.0.1"),
        ("LocalHost:8100", "localhost"),
        ("[::1]:8100", "::1"),
        ("nexus.exemple.fr", "nexus.exemple.fr"),
    ],
)
def test_host_name(value: str, name: str) -> None:
    assert host_name(value) == name


def test_origin_host() -> None:
    assert origin_host("http://localhost:3100") == "localhost"
    assert origin_host("https://Nexus.Exemple.fr") == "nexus.exemple.fr"
    assert origin_host("null") is None
    assert origin_host("file:///tmp/page.html") is None


@pytest.mark.parametrize(
    ("method", "host", "origin"),
    [
        ("GET", "localhost:8100", None),  # Hub, scripts, healthcheck Docker
        ("POST", "127.0.0.1:8100", None),
        ("POST", "localhost:8100", "http://localhost:3100"),  # interface en développement
        ("PUT", "127.0.0.1:49152", "http://127.0.0.1:49152"),  # app de bureau, port libre
        ("POST", "nexus.exemple.fr", "https://nexus.exemple.fr"),  # VPS : hôte de CORS_ORIGINS
        ("DELETE", "nexus.lan:8100", "http://nexus.lan:3100"),  # ALLOWED_HOSTS
        ("GET", "localhost:8100", "https://exemple.com"),  # lecture : CORS s'en charge
    ],
)
def test_local_requests_are_accepted(method: str, host: str, origin: str | None) -> None:
    assert refusal(method, host, origin, HOSTS) is None


@pytest.mark.parametrize(
    ("method", "host", "origin", "code"),
    [
        ("GET", "attaquant.exemple:8100", None, "forbidden_host"),  # DNS rebinding
        ("GET", None, None, "forbidden_host"),
        ("POST", "attaquant.exemple:8100", "http://attaquant.exemple:8100", "forbidden_host"),
        ("POST", "localhost:8100", "https://exemple.com", "forbidden_origin"),
        ("POST", "localhost:8100", "null", "forbidden_origin"),
        ("DELETE", "127.0.0.1:8100", "http://evil.localhost", "forbidden_origin"),
    ],
)
def test_foreign_requests_are_refused(
    method: str, host: str | None, origin: str | None, code: str
) -> None:
    refused = refusal(method, host, origin, HOSTS)
    assert refused is not None and refused[0] == code


def test_api_refuses_a_foreign_host(client: TestClient) -> None:
    """DNS rebinding : la page d'un domaine rebindé vers 127.0.0.1 ne lit rien."""
    for path in ("/api/conversations", "/api/workflow-runs?status=awaiting_approval"):
        response = client.get(path, headers={"Host": "attaquant.exemple:8100"})
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "forbidden_host"
    # … même en se disant « même origine » (l'ancienne garde des réglages s'y fiait)
    forged = {"Host": "attaquant.exemple:8100", "Origin": "http://attaquant.exemple:8100"}
    assert client.get("/api/settings", headers=forged).status_code == 403
    assert (
        client.put("/api/settings", json={"values": {}}, headers=forged).json()["error"]["code"]
        == "forbidden_host"
    )


def test_api_refuses_a_write_from_another_site(client: TestClient) -> None:
    """Un autre site ne valide pas une étape, ne teste pas un déclencheur, ne charge rien."""
    foreign = {"Host": "localhost:8100", "Origin": "https://exemple.com"}
    for path in (
        "/api/workflow-runs/run-1/resume",
        "/api/triggers/trg-1/test",
        "/api/exemples-suite/boutique",
    ):
        response = client.post(path, headers=foreign)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "forbidden_origin"
    assert client.post("/api/triggers/trg-1/test", headers={**foreign, "Origin": "null"}).status_code == 403  # fmt: skip


def test_api_accepts_the_interface_the_hub_and_the_probes(client: TestClient) -> None:
    ui = {"Host": "localhost:8100", "Origin": "http://localhost:3100"}
    assert client.get("/api/agents", headers=ui).status_code == 200
    # Écriture depuis l'interface : la garde laisse passer (la route répond, ici 404)
    assert client.post("/api/triggers/inconnu/test", headers=ui).status_code != 403
    # Hub et scripts : appel serveur sans Origin, sur 127.0.0.1
    assert client.get("/api/health", headers={"Host": "127.0.0.1:8100"}).status_code == 200
    # Sondes de santé : ouvertes à tout hôte (rien de privé)
    assert client.get("/health", headers={"Host": "nexus-backend:8100"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "10.0.0.5:8100"}).status_code == 200


def test_declared_hosts_are_read_live(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """VPS : l'hôte public vient de CORS_ORIGINS ; un autre nom s'ajoute par ALLOWED_HOSTS."""
    vps = {"Host": "nexus.exemple.fr", "Origin": "https://nexus.exemple.fr"}
    assert client.get("/api/agents", headers=vps).status_code == 403
    monkeypatch.setenv("CORS_ORIGINS", "https://nexus.exemple.fr")
    get_settings.cache_clear()
    assert client.get("/api/agents", headers=vps).status_code == 200
    assert client.post("/api/triggers/inconnu/test", headers=vps).status_code != 403
    lan = {"Host": "nexus.lan:8100"}
    assert client.get("/api/agents", headers=lan).status_code == 403
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver, nexus.lan")
    get_settings.cache_clear()
    assert client.get("/api/agents", headers=lan).status_code == 200
