"""Connecteurs Projets, Trésorerie et GitHub.

Projets / Trésorerie : réponses RÉELLES capturées le 2026-10-20 sur les données de
démonstration des applications (tests/fixtures) et rejouées par httpx.MockTransport.
"""

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.tools import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.github import GitHubClient, github_read_tools, github_write_tools
from app.tools.http import AppRequestError, AppUnavailableError
from app.tools.projets import ProjetsClient, projets_read_tools, projets_write_tools
from app.tools.tresorerie import TresorerieClient, tresorerie_tools

FIX = Path(__file__).parent / "fixtures"


def fixture(app: str, name: str) -> Any:
    return json.loads((FIX / app / f"{name}.json").read_text())


# ═══ Atelier Projets ══════════════════════════════════════════════


class FakeProjets:
    ROUTES = {
        "/api/health": "health",
        "/api/projects": "projects",
        "/api/projects/1/dashboard": "dashboard",
        "/api/projects/1/tree": "tree",
        "/api/projects/1/work-items": "work_items",
        "/api/work-items/12345": "work_item_12345",
        "/api/projects/1/timesheet": "timesheet",
        "/api/projects/1/milestones": "milestones",
    }

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path in self.ROUTES:
            return httpx.Response(200, json=fixture("projets", self.ROUTES[path]))
        if request.method == "POST" and path == "/api/stories/2/work-items":
            body = json.loads(request.content)
            detail = fixture("projets", "work_item_12345") | {
                "id": 20001, "title": body["title"], "type": body["type"], "status": "OPEN",
            }  # fmt: skip
            return httpx.Response(201, json=detail)
        if request.method == "PATCH" and path == "/api/work-items/12345":
            body = json.loads(request.content)
            return httpx.Response(200, json=fixture("projets", "work_item_12345") | body)
        return httpx.Response(
            404,
            json={
                "statusCode": 404,
                "error": "Not Found",
                "code": "NOT_FOUND",
                "message": "Élément #9 introuvable",
            },
        )


@pytest.fixture
def projets() -> tuple[ProjetsClient, FakeProjets]:
    fake = FakeProjets()
    return ProjetsClient("http://projets.test/api", transport=httpx.MockTransport(fake)), fake


async def test_projets_read_tools_on_real_payloads(
    projets: tuple[ProjetsClient, FakeProjets],
) -> None:
    client, _ = projets
    tools = {t.name: t for t in projets_read_tools(client)}
    ctx = ToolContext()
    out = await tools["projets_dashboard"].invoke({"project_id": 1}, ctx)
    assert not out.is_error and "App E-Commerce v2" in out.content and "70.7 %" in out.content
    structure = await tools["projets_structure"].invoke({"project_id": 1}, ctx)
    assert "story_id" in structure.content
    items = await tools["projets_list_work_items"].invoke({"project_id": 1}, ctx)
    assert "17 élément(s)" in items.content and items.artifacts[0].kind == "data_preview"
    detail = await tools["projets_work_item"].invoke({"work_item_id": 12345}, ctx)
    assert "moteur de synchronisation Git" in detail.content and "Commits liés" in detail.content
    sheet = await tools["projets_timesheet"].invoke({"project_id": 1}, ctx)
    assert "passé 228 h" in sheet.content


async def test_projets_filters_are_sent_as_repeated_keys(
    projets: tuple[ProjetsClient, FakeProjets],
) -> None:
    client, fake = projets
    await client.work_items(1, status=["OPEN", "BLOCKED"], types=["BUG"], q="git")
    query = fake.requests[-1].url.params
    assert query.get_list("status") == ["OPEN", "BLOCKED"]
    assert query.get_list("type") == ["BUG"] and query["q"] == "git"


async def test_projets_not_found_is_a_clear_tool_error(
    projets: tuple[ProjetsClient, FakeProjets],
) -> None:
    client, _ = projets
    tool = next(t for t in projets_read_tools(client) if t.name == "projets_work_item")
    out = await tool.invoke({"work_item_id": 9}, ToolContext())
    assert out.is_error and "introuvable" in out.content


async def test_projets_write_tools_need_approval_and_send_strict_bodies(
    projets: tuple[ProjetsClient, FakeProjets],
) -> None:
    client, fake = projets
    tools = {t.name: t for t in projets_write_tools(client)}
    assert all(t.requires_approval for t in tools.values())
    create = tools["projets_create_work_item"]
    args = {"story_id": 2, "type": "TASK", "title": "Écrire les tests", "estimated_hours": 4}
    assert (
        create.summarize(args) == "Créer la TASK « Écrire les tests » dans la story 2, 4 h estimées"
    )
    out = await create.invoke(args, ToolContext())
    assert not out.is_error and "#20001" in out.content
    assert json.loads(fake.requests[-1].content) == {
        "type": "TASK",
        "title": "Écrire les tests",
        "estimatedHours": 4,
    }

    # CLOSED impose 100 % (règle d'Atelier Projets) : l'outil corrige au lieu d'échouer
    await tools["projets_update_work_item"].invoke(
        {"work_item_id": 12345, "status": "CLOSED", "progress": 40}, ToolContext()
    )
    assert json.loads(fake.requests[-1].content) == {"status": "CLOSED", "progress": 100}


async def test_projets_unreachable() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = ProjetsClient("http://projets.test/api", transport=httpx.MockTransport(down))
    with pytest.raises(AppUnavailableError, match="Atelier Projets est-il lancé"):
        await client.projects()


# ═══ Atelier Trésorerie ═══════════════════════════════════════════


def treso_handler(request: httpx.Request) -> httpx.Response:
    name = request.url.path.removeprefix("/api/")
    if request.method != "GET":
        return httpx.Response(405)
    try:
        return httpx.Response(200, json=fixture("tresorerie", name))
    except FileNotFoundError:
        return httpx.Response(404, json={"error": "Ressource introuvable"})


async def test_tresorerie_tools_are_sensitive_read_only_and_parse_real_payloads() -> None:
    client = TresorerieClient("http://treso.test/api", transport=httpx.MockTransport(treso_handler))
    tools = {t.name: t for t in tresorerie_tools(client)}
    assert all(t.sensitive and not t.requires_approval for t in tools.values())
    ctx = ToolContext()
    dash = await tools["tresorerie_dashboard"].invoke({}, ctx)
    assert not dash.is_error and "Patrimoine net" in dash.content and "€" in dash.content
    tx = await tools["tresorerie_transactions"].invoke({"type": "expense", "limit": 20}, ctx)
    assert "Sur tout le filtre" in tx.content and tx.artifacts
    for name in (
        "tresorerie_accounts",
        "tresorerie_budgets",
        "tresorerie_goals",
        "tresorerie_holdings",
        "tresorerie_categories",
    ):
        out = await tools[name].invoke({}, ctx)
        assert not out.is_error, (name, out.content)


async def test_tresorerie_ping_checks_identity() -> None:
    def other(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"app": "autre-chose"})

    client = TresorerieClient("http://treso.test/api", transport=httpx.MockTransport(other))
    with pytest.raises(AppRequestError, match="n'est pas Atelier Trésorerie"):
        await client.ping()


async def test_tresorerie_rejects_bad_month_before_any_call() -> None:
    client = TresorerieClient("http://treso.test/api", transport=httpx.MockTransport(treso_handler))
    tool = next(t for t in tresorerie_tools(client) if t.name == "tresorerie_budgets")
    out = await tool.invoke({"month": "2026-13"}, ToolContext())
    assert out.is_error and "month" in out.content


# ═══ GitHub ═══════════════════════════════════════════════════════


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.files = {"README.md": "# Démo\n"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        repo = {
            "full_name": "moi/demo", "description": "Dépôt de démo", "default_branch": "main",
            "private": True, "language": "Python", "open_issues_count": 2,
            "html_url": "https://github.com/moi/demo", "pushed_at": "2026-10-20T08:00:00Z",
        }  # fmt: skip
        if path == "/repos/moi/demo" and method == "GET":
            return httpx.Response(200, json=repo)
        if path.startswith("/repos/moi/demo/contents"):
            rel = path.removeprefix("/repos/moi/demo/contents").strip("/")
            if method == "GET" and rel == "":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "name": "README.md",
                            "path": "README.md",
                            "type": "file",
                            "size": 7,
                            "sha": "s1",
                        }
                    ],
                )
            if method == "GET":
                if rel not in self.files:
                    return httpx.Response(404, json={"message": "Not Found"})
                content = base64.b64encode(self.files[rel].encode()).decode()
                return httpx.Response(
                    200,
                    json={
                        "name": rel,
                        "path": rel,
                        "type": "file",
                        "size": 7,
                        "sha": "s1",
                        "content": content,
                    },
                )
            if method == "PUT":
                body = json.loads(request.content)
                self.files[rel] = base64.b64decode(body["content"]).decode()
                return httpx.Response(201, json={"commit": {"sha": "abcdef1234"}})
        if path == "/repos/moi/demo/git/ref/heads/main":
            return httpx.Response(
                200, json={"ref": "refs/heads/main", "object": {"sha": "0123456789"}}
            )
        if path == "/repos/moi/demo/git/refs" and method == "POST":
            return httpx.Response(201, json={"ref": json.loads(request.content)["ref"]})
        if path == "/repos/moi/demo/pulls" and method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={"number": 7, "title": body["title"], "state": "open", "draft": body["draft"],
                      "html_url": "https://github.com/moi/demo/pull/7", "head": {"ref": body["head"]}},
            )  # fmt: skip
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github() -> tuple[GitHubClient, FakeGitHub]:
    fake = FakeGitHub()
    client = GitHubClient(
        "https://api.github.test", "jeton", ["moi/demo"], transport=httpx.MockTransport(fake)
    )
    return client, fake


async def test_github_read_and_token_header(github: tuple[GitHubClient, FakeGitHub]) -> None:
    client, fake = github
    tools = {t.name: t for t in github_read_tools(client)}
    overview = await tools["github_repo_overview"].invoke({}, ToolContext())
    assert "moi/demo" in overview.content and "README.md" in overview.content
    file = await tools["github_read_file"].invoke({"path": "README.md"}, ToolContext())
    assert "# Démo" in file.content
    assert fake.requests[0].headers["authorization"] == "Bearer jeton"


async def test_github_repo_allowlist_and_path_traversal(
    github: tuple[GitHubClient, FakeGitHub],
) -> None:
    client, _ = github
    tool = next(t for t in github_read_tools(client) if t.name == "github_read_file")
    other = await tool.invoke({"repo": "quelquun/autre", "path": "x"}, ToolContext())
    assert other.is_error and "non autorisé" in other.content
    escape = await tool.invoke({"path": "../../etc/passwd"}, ToolContext())
    assert escape.is_error and "Chemin invalide" in escape.content


@pytest.mark.parametrize("branch", ["main", "master", "nimporte", "feat/"])
async def test_github_refuses_protected_or_unconventional_branches(
    github: tuple[GitHubClient, FakeGitHub], branch: str
) -> None:
    client, fake = github
    tool = next(t for t in github_write_tools(client) if t.name == "github_commit_files")
    out = await tool.invoke(
        {"branch": branch, "message": "feat: x", "files": [{"path": "a.py", "content": "x"}]},
        ToolContext(),
    )
    assert out.is_error and "refusée" in out.content
    assert not any(r.method == "PUT" for r in fake.requests)


async def test_github_branch_commit_and_draft_pr(github: tuple[GitHubClient, FakeGitHub]) -> None:
    client, fake = github
    tools = {t.name: t for t in github_write_tools(client)}
    assert all(t.requires_approval for t in tools.values())
    ctx = ToolContext()
    assert not (await tools["github_create_branch"].invoke({"branch": "feat/tests"}, ctx)).is_error
    commit = await tools["github_commit_files"].invoke(
        {"branch": "feat/tests", "message": "test: ajoute un test #12345",
         "files": [{"path": "README.md", "content": "# Démo v2\n"}, {"path": "tests/test_a.py", "content": "def test(): ...\n"}]},
        ctx,
    )  # fmt: skip
    assert not commit.is_error and commit.artifacts[0].kind == "markdown"
    put_readme = next(
        r for r in fake.requests if r.method == "PUT" and r.url.path.endswith("README.md")
    )
    assert json.loads(put_readme.content)["sha"] == "s1"  # mise à jour d'un fichier existant
    put_new = next(
        r for r in fake.requests if r.method == "PUT" and r.url.path.endswith("test_a.py")
    )
    assert "sha" not in json.loads(put_new.content)  # création
    pr = await tools["github_open_pull_request"].invoke(
        {"head": "feat/tests", "title": "Tests"}, ctx
    )
    assert "#7" in pr.content
    body = json.loads(fake.requests[-1].content)
    assert body["draft"] is True and body["base"] == "main"


# ═══ Environnement ════════════════════════════════════════════════


async def test_environment_reuses_and_closes_clients() -> None:
    env = ToolEnvironment(
        Settings(_env_file=None, github_repo="moi/demo"),  # type: ignore[call-arg]
        transports={"projets": httpx.MockTransport(FakeProjets())},
    )
    assert env.projets() is env.projets()
    assert (await env.projets().health()).status == "ok"
    assert env.github().default_repo == "moi/demo"
    await env.aclose()
    assert env._clients == {}
