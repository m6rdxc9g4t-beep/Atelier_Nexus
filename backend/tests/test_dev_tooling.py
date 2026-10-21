"""Outils Claude Code du dépôt (.claude/) : hooks de garde, sous-agents et skills bien formés."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = ROOT / ".claude"
HOOKS = CLAUDE / "hooks"


def run_hook(name: str, payload: dict[str, object], *, project: Path = ROOT) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
        env={"CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    return result.returncode, result.stderr


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} : en-tête YAML absent"
    head = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    key = ""
    for line in head.splitlines():
        if line.startswith("  - ") and key:
            fields[key] = (fields[key] + " " + line[4:]).strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


# ─── Garde git ────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    return tmp_path


def bash(command: str, cwd: Path) -> tuple[int, str]:
    return run_hook(
        "garde_git.py", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    )


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'essai'",
        "git add . && git commit -am 'essai'",
        "git push",
        "git push origin main",
        "git -C . push origin HEAD:main",
        "git push origin +feat/x:refs/heads/master",
        "git push --force origin feat/x",
        "git push -fu origin feat/x",
        "git push origin :feat/x",
        "git push --delete origin feat/x",
        "git branch -D main",
    ],
)
def test_git_guard_blocks_on_main(repo: Path, command: str) -> None:
    code, message = bash(command, repo)
    assert code == 2, command
    assert message.strip()


@pytest.mark.parametrize(
    "command",
    [
        "git status && git diff main...HEAD",
        "git switch -c feat/essai",
        "echo 'git push origin main'",
        "ls -la",
    ],
)
def test_git_guard_allows_safe_commands_on_main(repo: Path, command: str) -> None:
    assert bash(command, repo)[0] == 0, command


def test_git_guard_allows_work_branch(repo: Path) -> None:
    subprocess.run(["git", "switch", "-q", "-c", "feat/essai"], cwd=repo, check=True)
    for command in (
        "git commit -m 'ok'",
        "git push -u origin feat/essai",
        "git push",
        "git push --force-with-lease origin feat/essai",
    ):
        assert bash(command, repo)[0] == 0, command
    assert bash("git push origin feat/essai:main", repo)[0] == 2


# ─── Garde des fichiers ───────────────────────────────────────────


def edit(tool: str, path: str) -> int:
    return run_hook("garde_fichiers.py", {"tool_name": tool, "tool_input": {"file_path": path}})[0]


@pytest.mark.parametrize(
    ("tool", "path"),
    [
        ("Write", "backend/.env"),
        ("Edit", str(ROOT / "backend" / ".env.local")),
        ("Write", "frontend/src/styles/atelier-ds/colors.css"),
        ("Edit", "frontend/src/styles/brand/atelier-brand.css"),
        ("Edit", "backend/migrations/versions/0001_custom_agents.py"),
        ("Write", "backend/migrations/versions/0001_custom_agents.py"),
        ("Write", "backend/cuisine-session.json"),
    ],
)
def test_file_guard_blocks(tool: str, path: str) -> None:
    assert edit(tool, path) == 2


@pytest.mark.parametrize(
    ("tool", "path"),
    [
        ("Write", "backend/.env.example"),
        ("Write", "backend/migrations/versions/9999_nouvelle_migration.py"),
        ("Write", "backend/tests/fixtures/nouvelle_app/reponse.json"),
        ("Edit", "backend/app/tools/savoir.py"),
        ("Edit", "frontend/src/app/globals.css"),
    ],
)
def test_file_guard_allows(tool: str, path: str) -> None:
    assert edit(tool, path) == 0


def test_existing_fixture_is_frozen() -> None:
    fixture = next(p for p in (ROOT / "backend" / "tests" / "fixtures").rglob("*") if p.is_file())
    assert edit("Edit", str(fixture)) == 2


def test_hooks_ignore_unreadable_input() -> None:
    for name in ("garde_git.py", "garde_fichiers.py", "formater_python.py"):
        result = subprocess.run(
            [sys.executable, str(HOOKS / name)], input="pas du json", capture_output=True, text=True
        )
        assert result.returncode == 0, name


# ─── Sous-agents, skills, réglages ────────────────────────────────


def test_subagents_are_well_formed() -> None:
    agents = sorted((CLAUDE / "agents").glob("*.md"))
    assert agents
    skills = {p.parent.name for p in (CLAUDE / "skills").glob("*/SKILL.md")}
    for path in agents:
        meta = frontmatter(path)
        assert meta.get("name") == path.stem, path
        assert len(meta.get("description", "")) > 40, path
        assert meta.get("tools"), f"{path} : liste d'outils explicite attendue (moindre privilège)"
        assert meta.get("model") in {"haiku", "sonnet", "opus", "inherit"}, path
        for skill in meta.get("skills", "").split():
            assert skill in skills, f"{path} : skill inconnu {skill}"


def test_read_only_subagents_cannot_write() -> None:
    for name in ("relecteur-nexus", "testeur-nexus"):
        tools = frontmatter(CLAUDE / "agents" / f"{name}.md")["tools"]
        assert "Write" not in tools and "Edit" not in tools, name


def test_skills_are_well_formed() -> None:
    skills = sorted((CLAUDE / "skills").glob("*/SKILL.md"))
    assert skills
    for path in skills:
        meta = frontmatter(path)
        assert meta.get("name") == path.parent.name, path
        assert len(meta.get("description", "")) > 40, path


def test_settings_hooks_point_to_existing_scripts() -> None:
    settings = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert commands
    for command in commands:
        script = command.split("/.claude/hooks/", 1)[1]
        assert (HOOKS / script).is_file(), command
