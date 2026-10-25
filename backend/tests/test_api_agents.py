"""API de l'étape 5 : agents personnalisés (base SQLite en mémoire), validations en SSE,
éditeur, état des applications."""

import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents import AgentCatalog
from app.api.deps import get_catalog, get_custom_repository, get_env_factory
from app.core.config import Settings
from app.core.llm import get_llm_router
from app.db.models import Base, CustomAgentRow
from app.db.repository import CustomAgentRepository
from app.schemas.agents import CustomAgentCreate
from app.tools import toolsets
from app.tools.environment import ToolEnvironment
from app.tools.toolsets import Toolset
from main import app
from tests.fake_suite import FakeConvertNode
from tests.fakes import ScriptedProvider, make_router, text_response, tool_response
from tests.test_connectors import FakeProjets


@pytest.fixture
async def repo() -> AsyncIterator[CustomAgentRepository]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield CustomAgentRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


@pytest.fixture
def anthropic() -> ScriptedProvider:
    return ScriptedProvider("anthropic")


@pytest.fixture
def ollama() -> ScriptedProvider:
    return ScriptedProvider("ollama")


@pytest.fixture
def client(
    repo: CustomAgentRepository, anthropic: ScriptedProvider, ollama: ScriptedProvider
) -> Iterator[TestClient]:
    router = make_router(anthropic, ollama)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        github_repo=None,
        projets_base_url="http://projets.test/api",
        tresorerie_base_url="http://127.0.0.1:1/api",  # port fermé : injoignable
        data_via_base_url=None,
        convert_base_url="http://127.0.0.1:8010/api",
        # Jamais les vraies apps de la machine (Ciné 4000, Savoir 5051, dossier de Tab)
        cine_base_url=None,
        savoir_base_url=None,
        tab_exports_dir=None,
    )
    convert = FakeConvertNode()
    convert.mode = "down"  # Convert arrêté, simulé : jamais de connexion au vrai port 8010

    def env_factory() -> ToolEnvironment:
        return ToolEnvironment(
            settings,
            transports={
                "projets": httpx.MockTransport(FakeProjets()),
                "convert": convert.transport,
            },
        )

    app.dependency_overrides[get_llm_router] = lambda: router
    app.dependency_overrides[get_custom_repository] = lambda: repo
    app.dependency_overrides[get_catalog] = lambda: AgentCatalog(repo)
    app.dependency_overrides[get_env_factory] = lambda: env_factory
    yield TestClient(app)
    app.dependency_overrides.clear()


def user(text: str) -> dict[str, object]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


AGENT = {
    "name": "veille_projets",
    "display_name": "Veille projets",
    "description": "Surveille les retards et prépare une synthèse.",
    "system_prompt": "Tu surveilles les projets et signales les retards, sans détour.",
    "icon": "list-checks",
    "toolsets": ["projets_read", "projets_write"],
    "starters": ["Quels éléments sont en retard ?"],
}


# ─── Éditeur et catalogue ─────────────────────────────────────────


def test_editor_options_list_toolsets_with_flags(client: TestClient) -> None:
    data = client.get("/api/toolsets").json()
    toolsets = {t["id"]: t for t in data["toolsets"]}
    assert toolsets["tresorerie"]["sensitive"] is True
    assert toolsets["projets_write"]["writes"] is True
    assert toolsets["github_read"]["configured"] is False
    assert "delegation" in toolsets and "assistant" in data["reserved_names"]
    assert "chart-column" in data["icons"]


def test_agents_endpoint_exposes_profiles(client: TestClient) -> None:
    agents = {a["name"]: a for a in client.get("/api/agents").json()}
    assert agents["finance"]["local_only"] is True
    assert agents["data_analyst"]["category"] == "Données"
    assert any(t["requires_approval"] for t in agents["chef_de_projet"]["tools"])
    assert agents["developpeur"]["unavailable_toolsets"]


# ─── Agents personnalisés ─────────────────────────────────────────


def test_custom_agent_crud(client: TestClient) -> None:
    created = client.post("/api/custom-agents", json=AGENT)
    assert created.status_code == 201, created.text
    info = created.json()
    assert info["source"] == "custom" and info["toolsets"] == [
        "core",
        "projets_read",
        "projets_write",
    ]
    assert {t["name"] for t in info["tools"]} >= {"publish_artifact", "projets_dashboard"}

    assert "veille_projets" in {a["name"] for a in client.get("/api/agents").json()}
    assert client.post("/api/custom-agents", json=AGENT).status_code == 409

    updated = client.put(
        "/api/custom-agents/veille_projets",
        json={k: v for k, v in AGENT.items() if k != "name"} | {"display_name": "Veille"},
    )
    assert updated.status_code == 200 and updated.json()["display_name"] == "Veille"

    assert client.delete("/api/custom-agents/veille_projets").status_code == 204
    assert client.get("/api/custom-agents/veille_projets").status_code == 404


def test_custom_agent_validation(client: TestClient) -> None:
    assert client.post("/api/custom-agents", json=AGENT | {"name": "assistant"}).status_code == 409
    assert client.post("/api/custom-agents", json=AGENT | {"name": "Pas Valide"}).status_code == 422
    bad = client.post("/api/custom-agents", json=AGENT | {"toolsets": ["inexistante"]})
    assert bad.status_code == 422 and "inexistante" in bad.text


def test_custom_agent_with_sensitive_toolset_is_local_only(client: TestClient) -> None:
    body = AGENT | {"name": "budget_famille", "toolsets": ["tresorerie"]}
    info = client.post("/api/custom-agents", json=body).json()
    assert info["local_only"] is True
    refused = client.post(
        "/api/agents/budget_famille/run", json={"messages": [user("?")], "provider": "anthropic"}
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "provider_not_allowed"


def test_custom_agent_runs_with_guardrails(client: TestClient, anthropic: ScriptedProvider) -> None:
    client.post("/api/custom-agents", json=AGENT)
    anthropic.script = [text_response("Aucun retard.")]
    response = client.post("/api/agents/veille_projets/run", json={"messages": [user("Retards ?")]})
    assert response.status_code == 200 and response.json()["text"] == "Aucun retard."
    system = anthropic.requests[0].system or ""
    assert system.startswith("Tu surveilles") and "validation de l'utilisateur" in system


# ─── Validation humaine de bout en bout (SSE) ─────────────────────


def test_approval_round_trip_over_sse(client: TestClient, anthropic: ScriptedProvider) -> None:
    anthropic.script = [
        tool_response(
            "projets_create_work_item",
            {"story_id": 2, "type": "BUG", "title": "Corriger l'export"},
            call_id="w1",
        ),
        text_response("Le bug est créé."),
    ]
    with client.stream(
        "POST", "/api/agents/chef_de_projet/stream", json={"messages": [user("Crée le bug")]}
    ) as r:
        first = sse(r.read().decode())
    kinds = [k for k, _ in first]
    assert kinds == ["approval_required", "done"]
    pending = first[0][1]["calls"][0]  # type: ignore[index]
    assert pending["summary"] == "Créer la BUG « Corriger l'export » dans la story 2"
    done = first[1][1]["result"]  # type: ignore[index]
    assert done["stop_reason"] == "awaiting_approval"

    history = [user("Crée le bug"), *done["new_messages"]]
    with client.stream(
        "POST",
        "/api/agents/chef_de_projet/stream",
        json={"messages": history, "approvals": {"w1": True}},
    ) as r:
        second = sse(r.read().decode())
    kinds = [k for k, _ in second]
    assert kinds[:2] == ["tool_call", "tool_result"]
    assert second[1][1]["is_error"] is False and "#20001" in second[1][1]["content"]  # type: ignore[operator]
    assert kinds[-1] == "done"


def test_resume_requires_approvals(client: TestClient) -> None:
    message = {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "x", "name": "n", "input": {}}],
    }
    assert client.post("/api/agents/assistant/run", json={"messages": [message]}).status_code == 422


def test_conversation_with_a_local_answer_refuses_claude(client: TestClient) -> None:
    """F-04 : la réponse de Finance (délégation) verrouille la suite du fil sur Ollama."""
    history = [
        user("Mes dépenses du mois ?"),
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call_f1", "name": "delegate_to_agent",
                 "input": {"agent": "finance", "task": "Résume mes dépenses du mois."}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_f1", "tool_name": "delegate_to_agent",
                 "content": "Réponse de Finance :\nDépenses : 1 234 €."},
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Vos dépenses : 1 234 €."}]},
        user("Fais-en un courriel."),
    ]  # fmt: skip
    body = {"messages": history, "provider": "anthropic"}
    refused = client.post("/api/agents/orchestrateur/run", json=body)
    assert refused.status_code == 403, refused.text
    error = refused.json()["error"]
    assert error["code"] == "provider_not_allowed" and "Finance" in error["message"]


# ─── Agents personnalisés : définitions anciennes ─────────────────


async def test_unreadable_stored_definition_is_skipped_alone(repo: CustomAgentRepository) -> None:
    """G-08 : une ligne qui ne passe plus la validation est écartée seule (et journalisée)."""
    await repo.create(CustomAgentCreate.model_validate(AGENT))
    async with repo.sessions() as s:
        s.add(CustomAgentRow(**(AGENT | {"name": "ancien", "icon": "icone_retiree"})))
        await s.commit()
    assert [d.name for d in await repo.list()] == ["veille_projets"]
    assert await repo.get("ancien") is None


def test_custom_agent_survives_a_removed_extension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-08 : boîte d'une extension retirée → agent toujours listé, modifiable, boîte signalée."""
    extension = Toolset(
        id="extension_test", label="Extension", description="Boîte d'une extension.", build=lambda env: []
    )  # fmt: skip
    monkeypatch.setitem(toolsets._TOOLSETS, "extension_test", extension)
    body = AGENT | {"name": "veille_ext", "toolsets": ["projets_read", "extension_test"]}
    assert client.post("/api/custom-agents", json=body).status_code == 201
    monkeypatch.delitem(toolsets._TOOLSETS, "extension_test")  # NEXUS_PLUGINS sans l'extension

    stored = client.get("/api/custom-agents")
    assert stored.status_code == 200
    assert next(d for d in stored.json() if d["name"] == "veille_ext")["toolsets"] == [
        "core", "projets_read", "extension_test"
    ]  # fmt: skip
    agents = {a["name"]: a for a in client.get("/api/agents").json()}
    assert "assistant" in agents  # les autres agents restent là
    info = agents["veille_ext"]
    assert info["unavailable_toolsets"] == ["extension_test"]
    assert info["toolsets"] == ["core", "projets_read"] and info["local_only"] is False
    assert client.get("/api/custom-agents/veille_ext").status_code == 200

    fields = {k: v for k, v in body.items() if k != "name"} | {"display_name": "Veille ext."}
    assert client.put("/api/custom-agents/veille_ext", json=fields).status_code == 200
    # Modification : seule la boîte déjà enregistrée est admise, une faute de frappe non
    typo = fields | {"toolsets": ["projets_read", "extension_test", "projets_raed"]}
    refused = client.put("/api/custom-agents/veille_ext", json=typo)
    assert refused.status_code == 422 and "projets_raed" in refused.text
    created = client.post("/api/custom-agents", json=body | {"name": "nouvelle_ext"})
    assert created.status_code == 422  # création : une boîte inconnue reste refusée


# ─── État des applications ────────────────────────────────────────


def test_apps_status(client: TestClient) -> None:
    status = {a["id"]: a for a in client.get("/api/apps/status").json()}
    assert status["projets"]["available"] is True and "1 projet" in status["projets"]["detail"]
    assert status["github"]["configured"] is False
    assert status["cuisine"]["configured"] is False  # rien en dur : désactivé par défaut
    assert status["tresorerie"]["available"] is False  # pas de transport simulé : injoignable
    assert status["convert"]["configured"] is True and status["convert"]["available"] is False
    assert "Atelier Convert injoignable" in status["convert"]["error"]


def test_apps_status_reads_the_convert_manifest(client: TestClient) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        github_repo=None,
        data_via_base_url=None,
        projets_base_url=None,
        tresorerie_base_url=None,
        cine_base_url=None,
        savoir_base_url=None,
        tab_exports_dir=None,
        convert_base_url="http://127.0.0.1:8010/api",
    )
    convert = FakeConvertNode()
    env = lambda: ToolEnvironment(settings, transports={"convert": convert.transport})  # noqa: E731
    app.dependency_overrides[get_env_factory] = lambda: env
    status = {a["id"]: a for a in client.get("/api/apps/status").json()}
    assert (
        status["convert"]["available"] is True and status["convert"]["label"] == "Atelier Convert"
    )
    assert status["convert"]["detail"] == "6 action(s), 4 événement(s) (nœud atelier-node/1)"
    assert status["convert"]["base_url"] == "http://127.0.0.1:8010/api"
