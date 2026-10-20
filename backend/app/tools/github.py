"""Connecteur GitHub (API REST) — pour l'agent Développeur (« Studio Dev »).

Garde-fous (CLAUDE.md §4) :
- dépôts limités à une liste blanche (`GITHUB_REPO` + `GITHUB_ALLOWED_REPOS`) ;
- jamais d'écriture sur la branche par défaut, `main` ou `master` : branche `feat/…` / `fix/…` ;
- toute écriture (branche, commit, PR) attend la validation de l'utilisateur ;
- pull requests ouvertes en brouillon par défaut.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.tools.base import Artifact, BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.formatting import table_for_model
from app.tools.http import AppClient, AppError, AppNotFoundError, AppRequestError

PROTECTED = {"main", "master"}
BRANCH_RE = re.compile(r"^(feat|fix|chore|docs|refactor|test)/[a-z0-9][a-z0-9._-]{1,60}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_FILE_CHARS = 60_000


class _R(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Repo(_R):
    full_name: str
    description: str | None = None
    default_branch: str
    private: bool
    language: str | None = None
    open_issues_count: int = 0
    html_url: str
    pushed_at: str | None = None


class ContentEntry(_R):
    name: str
    path: str
    type: Literal["file", "dir", "symlink", "submodule"]
    size: int = 0
    sha: str


class FileContent(ContentEntry):
    content: str = ""
    encoding: str = "base64"


class GitRef(_R):
    ref: str

    class _Obj(_R):
        sha: str

    object: _Obj


class PullSummary(_R):
    number: int
    title: str
    state: str
    draft: bool = False
    html_url: str

    class _Head(_R):
        ref: str

    head: _Head


class IssueSummary(_R):
    number: int
    title: str
    state: str
    html_url: str
    pull_request: dict[str, Any] | None = None


class GitHubClient(AppClient):
    app = "github"
    label = "GitHub"

    def __init__(
        self,
        api_url: str,
        token: str | None,
        allowed_repos: list[str],
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        super().__init__(api_url, headers=headers, timeout=timeout, transport=transport)
        self.allowed = [r.lower() for r in allowed_repos]
        self.default_repo = allowed_repos[0] if allowed_repos else None

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> GitHubClient | None:
        repos = settings.github_repo_list
        if not repos:
            return None
        token = settings.github_token.get_secret_value() if settings.github_token else None
        return cls(
            settings.github_api_url,
            token,
            repos,
            timeout=settings.apps_timeout,
            transport=transport,
        )

    def _unavailable_hint(self) -> str:
        return "vérifiez la connexion réseau."

    def repo(self, repo: str | None) -> str:
        """Dépôt demandé, contrôlé contre la liste blanche."""
        name = repo or self.default_repo
        if not name or not REPO_RE.match(name):
            raise AppRequestError("Dépôt invalide (format propriétaire/dépôt).", app=self.app)
        if name.lower() not in self.allowed:
            raise AppRequestError(
                f"Dépôt « {name} » non autorisé. Dépôts autorisés : {', '.join(self.allowed)}.",
                app=self.app,
            )
        return name

    async def get_repo(self, repo: str | None) -> Repo:
        return self.parse(Repo, await self.request("GET", f"repos/{self.repo(repo)}"))

    async def list_dir(self, repo: str | None, path: str, ref: str | None) -> list[ContentEntry]:
        data = await self.request(
            "GET",
            f"repos/{self.repo(repo)}/contents/{_path(path)}",
            params={"ref": ref} if ref else None,
        )
        if isinstance(data, dict):
            raise AppRequestError(f"« {path} » est un fichier, pas un dossier.", app=self.app)
        return self.parse_list(ContentEntry, data)

    async def read_file(self, repo: str | None, path: str, ref: str | None) -> FileContent:
        data = await self.request(
            "GET",
            f"repos/{self.repo(repo)}/contents/{_path(path)}",
            params={"ref": ref} if ref else None,
        )
        if isinstance(data, list):
            raise AppRequestError(f"« {path} » est un dossier.", app=self.app)
        return self.parse(FileContent, data)

    async def search_code(self, repo: str | None, query: str) -> list[dict[str, Any]]:
        data = await self.request(
            "GET", "search/code", params={"q": f"{query} repo:{self.repo(repo)}", "per_page": 30}
        )
        return list(data.get("items", [])) if isinstance(data, dict) else []

    async def pulls(self, repo: str | None, state: str) -> list[PullSummary]:
        data = await self.request(
            "GET", f"repos/{self.repo(repo)}/pulls", params={"state": state, "per_page": 50}
        )
        return self.parse_list(PullSummary, data)

    async def issues(self, repo: str | None, state: str) -> list[IssueSummary]:
        data = await self.request(
            "GET", f"repos/{self.repo(repo)}/issues", params={"state": state, "per_page": 50}
        )
        return [i for i in self.parse_list(IssueSummary, data) if i.pull_request is None]

    # ─── Écritures ────────────────────────────────────────────────

    async def check_branch(self, repo: str, branch: str) -> None:
        if branch.lower() in PROTECTED or not BRANCH_RE.match(branch):
            raise AppRequestError(
                f"Branche « {branch} » refusée : utilisez feat/…, fix/…, chore/…, docs/…, "
                "refactor/… ou test/… (jamais main).",
                app=self.app,
            )
        info = await self.get_repo(repo)
        if branch == info.default_branch:
            raise AppRequestError("Écriture refusée sur la branche par défaut.", app=self.app)

    async def create_branch(self, repo: str | None, branch: str, from_ref: str | None) -> str:
        name = self.repo(repo)
        await self.check_branch(name, branch)
        base = from_ref or (await self.get_repo(name)).default_branch
        ref = self.parse(
            GitRef, await self.request("GET", f"repos/{name}/git/ref/heads/{_path(base)}")
        )
        await self.request(
            "POST",
            f"repos/{name}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": ref.object.sha},
        )
        return ref.object.sha

    async def put_file(
        self, repo: str | None, branch: str, path: str, content: str, message: str
    ) -> str:
        name = self.repo(repo)
        await self.check_branch(name, branch)
        sha: str | None = None
        try:
            sha = (await self.read_file(name, path, branch)).sha
        except AppNotFoundError:
            sha = None  # nouveau fichier
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        data = await self.request("PUT", f"repos/{name}/contents/{_path(path)}", json_body=body)
        commit = data.get("commit", {}) if isinstance(data, dict) else {}
        return str(commit.get("sha", ""))[:7]

    async def open_pull(
        self, repo: str | None, head: str, base: str | None, title: str, body: str, draft: bool
    ) -> PullSummary:
        name = self.repo(repo)
        await self.check_branch(name, head)
        target = base or (await self.get_repo(name)).default_branch
        data = await self.request(
            "POST",
            f"repos/{name}/pulls",
            json_body={"title": title, "head": head, "base": target, "body": body, "draft": draft},
        )
        return self.parse(PullSummary, data)


def _path(path: str) -> str:
    """Chemin de fichier dans un dépôt : relatif, sans « .. » ni caractères de contrôle."""
    clean = path.strip().strip("/")
    if ".." in clean.split("/") or any(ord(c) < 32 for c in clean):
        raise AppRequestError("Chemin invalide.", app="github")
    return clean


# ═══ Outils ═══════════════════════════════════════════════════════

REPO_FIELD = Field(default=None, description="propriétaire/dépôt (défaut : dépôt configuré).")


class _GitHubTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors = (AppError,)

    def __init__(self, client: GitHubClient) -> None:
        self.client = client


class RepoInput(ToolInput):
    repo: str | None = REPO_FIELD


class RepoOverviewTool(_GitHubTool[RepoInput]):
    name = "github_repo_overview"
    description = "Présentation d'un dépôt autorisé : description, branche par défaut, langage, tickets ouverts, racine."
    input_model = RepoInput

    async def run(self, params: RepoInput, ctx: ToolContext) -> ToolOutput:
        info = await self.client.get_repo(params.repo)
        root = await self.client.list_dir(info.full_name, "", None)
        entries = ", ".join(f"{e.name}{'/' if e.type == 'dir' else ''}" for e in root)
        others = [r for r in self.client.allowed if r != info.full_name.lower()]
        return ToolOutput(
            content=(
                f"{info.full_name} ({'privé' if info.private else 'public'}) — {info.description or 'sans description'}\n"
                f"Branche par défaut : {info.default_branch} · langage : {info.language or '—'} · "
                f"tickets ouverts : {info.open_issues_count} · dernier push : {info.pushed_at}\n"
                f"Racine : {entries}"
                + (f"\nAutres dépôts autorisés : {', '.join(others)}" if others else "")
            )
        )


class ListFilesInput(ToolInput):
    repo: str | None = REPO_FIELD
    path: str = Field(default="", description="Dossier (vide = racine).")
    ref: str | None = Field(default=None, description="Branche, tag ou commit.")


class ListFilesTool(_GitHubTool[ListFilesInput]):
    name = "github_list_files"
    description = "Liste le contenu d'un dossier d'un dépôt."
    input_model = ListFilesInput

    async def run(self, params: ListFilesInput, ctx: ToolContext) -> ToolOutput:
        entries = await self.client.list_dir(params.repo, params.path, params.ref)
        rows = [[e.path, e.type, e.size if e.type == "file" else None] for e in entries]
        text, _ = table_for_model(["chemin", "type", "taille"], rows, noun="entrée")
        return ToolOutput(content=text)


class ReadFileInput(ToolInput):
    repo: str | None = REPO_FIELD
    path: str = Field(min_length=1)
    ref: str | None = None


class ReadFileTool(_GitHubTool[ReadFileInput]):
    name = "github_read_file"
    description = "Lit un fichier texte d'un dépôt (tronqué au-delà de 60 000 caractères)."
    input_model = ReadFileInput

    async def run(self, params: ReadFileInput, ctx: ToolContext) -> ToolOutput:
        f = await self.client.read_file(params.repo, params.path, params.ref)
        try:
            text = base64.b64decode(f.content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ToolOutput(
                content=f"« {f.path} » n'est pas un fichier texte lisible.", is_error=True
            )
        cut = len(text) > MAX_FILE_CHARS
        body = text[:MAX_FILE_CHARS] + ("\n… [tronqué]" if cut else "")
        return ToolOutput(content=f"Fichier {f.path} ({f.size} octets) :\n```\n{body}\n```")


class SearchInput(ToolInput):
    repo: str | None = REPO_FIELD
    query: str = Field(
        min_length=2, max_length=200, description="Mots-clés (syntaxe de recherche GitHub)."
    )


class SearchCodeTool(_GitHubTool[SearchInput]):
    name = "github_search_code"
    description = (
        "Recherche du code dans un dépôt (branche par défaut) ; renvoie les fichiers concernés."
    )
    input_model = SearchInput

    async def run(self, params: SearchInput, ctx: ToolContext) -> ToolOutput:
        items = await self.client.search_code(params.repo, params.query)
        if not items:
            return ToolOutput(content="Aucun résultat.")
        return ToolOutput(content="\n".join(f"- {i.get('path')}" for i in items))


class StateInput(ToolInput):
    repo: str | None = REPO_FIELD
    state: Literal["open", "closed", "all"] = "open"


class PullRequestsTool(_GitHubTool[StateInput]):
    name = "github_list_pull_requests"
    description = "Pull requests d'un dépôt (ouvertes par défaut)."
    input_model = StateInput

    async def run(self, params: StateInput, ctx: ToolContext) -> ToolOutput:
        prs = await self.client.pulls(params.repo, params.state)
        lines = [
            f"- #{p.number} {p.title} [{p.head.ref}]{' (brouillon)' if p.draft else ''} — {p.state}"
            for p in prs
        ]
        return ToolOutput(content="\n".join(lines) or "Aucune pull request.")


class IssuesTool(_GitHubTool[StateInput]):
    name = "github_list_issues"
    description = "Tickets (issues) d'un dépôt, hors pull requests."
    input_model = StateInput

    async def run(self, params: StateInput, ctx: ToolContext) -> ToolOutput:
        issues = await self.client.issues(params.repo, params.state)
        return ToolOutput(
            content="\n".join(f"- #{i.number} {i.title} — {i.state}" for i in issues)
            or "Aucun ticket."
        )


class CreateBranchInput(ToolInput):
    repo: str | None = REPO_FIELD
    branch: str = Field(description="feat/nom, fix/nom… (jamais main).")
    from_ref: str | None = Field(
        default=None, description="Point de départ (défaut : branche par défaut)."
    )


class CreateBranchTool(_GitHubTool[CreateBranchInput]):
    name = "github_create_branch"
    description = "Crée une branche de travail (feat/…, fix/…). Action soumise à validation."
    input_model = CreateBranchInput
    requires_approval = True

    def approval_summary(self, params: CreateBranchInput) -> str:
        return f"Créer la branche {params.branch} sur {params.repo or self.client.default_repo}"

    async def run(self, params: CreateBranchInput, ctx: ToolContext) -> ToolOutput:
        sha = await self.client.create_branch(params.repo, params.branch, params.from_ref)
        return ToolOutput(content=f"Branche {params.branch} créée depuis {sha[:7]}.")


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    content: str = Field(description="Contenu COMPLET du fichier après modification.")


class CommitFilesInput(ToolInput):
    repo: str | None = REPO_FIELD
    branch: str
    message: str = Field(
        min_length=3, max_length=300, description="Conventional Commits : feat(scope): …"
    )
    files: list[FileChange] = Field(min_length=1, max_length=20)


class CommitFilesTool(_GitHubTool[CommitFilesInput]):
    name = "github_commit_files"
    description = (
        "Écrit un ou plusieurs fichiers (contenu complet) sur une branche de travail, un commit par "
        "fichier. Jamais sur la branche par défaut. Action soumise à validation."
    )
    input_model = CommitFilesInput
    requires_approval = True

    def approval_summary(self, params: CommitFilesInput) -> str:
        paths = ", ".join(f.path for f in params.files)
        return f"Committer sur {params.branch} : {paths} — « {params.message} »"

    async def run(self, params: CommitFilesInput, ctx: ToolContext) -> ToolOutput:
        shas = []
        for f in params.files:
            shas.append(
                await self.client.put_file(
                    params.repo, params.branch, f.path, f.content, params.message
                )
            )
        diff = Artifact(
            kind="markdown",
            title=f"Fichiers envoyés sur {params.branch}",
            content="\n\n".join(
                f"### `{f.path}`\n```\n{f.content[:20_000]}\n```" for f in params.files
            ),
            metadata={"source": "github", "branch": params.branch},
        )
        return ToolOutput(
            content=f"{len(shas)} fichier(s) envoyés sur {params.branch} (commits {', '.join(shas)}).",
            artifacts=[diff],
        )


class OpenPullInput(ToolInput):
    repo: str | None = REPO_FIELD
    head: str = Field(description="Branche de travail.")
    base: str | None = Field(
        default=None, description="Branche cible (défaut : branche par défaut)."
    )
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(
        default="",
        max_length=20_000,
        description="Description Markdown : contexte, changements, tests.",
    )
    draft: bool = True


class OpenPullTool(_GitHubTool[OpenPullInput]):
    name = "github_open_pull_request"
    description = "Ouvre une pull request (brouillon par défaut) depuis une branche de travail. Action soumise à validation."
    input_model = OpenPullInput
    requires_approval = True

    def approval_summary(self, params: OpenPullInput) -> str:
        kind = "brouillon de PR" if params.draft else "PR"
        return f"Ouvrir un {kind} « {params.title} » : {params.head} → {params.base or 'branche par défaut'}"

    async def run(self, params: OpenPullInput, ctx: ToolContext) -> ToolOutput:
        pr = await self.client.open_pull(
            params.repo, params.head, params.base, params.title, params.body, params.draft
        )
        return ToolOutput(content=f"Pull request #{pr.number} ouverte : {pr.html_url}")


def github_read_tools(client: GitHubClient) -> list[BaseTool[Any]]:
    return [
        RepoOverviewTool(client),
        ListFilesTool(client),
        ReadFileTool(client),
        SearchCodeTool(client),
        PullRequestsTool(client),
        IssuesTool(client),
    ]


def github_write_tools(client: GitHubClient) -> list[BaseTool[Any]]:
    return [CreateBranchTool(client), CommitFilesTool(client), OpenPullTool(client)]
