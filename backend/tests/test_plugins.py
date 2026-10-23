"""Extensions (app/plugins.py) et fichiers joints mis à la disposition des outils."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.plugins import load_plugins, parse_plugin_list
from app.schemas.attachments import AttachmentInfo
from app.tools.environment import ToolEnvironment
from app.tools.files import ConversationFiles, FilesError
from tests import fake_plugin

# ═══ Extensions ═══════════════════════════════════════════════════


def test_plugin_list_is_explicit_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_PLUGINS", raising=False)
    assert parse_plugin_list("") == []
    assert parse_plugin_list(" a ,b,,a ") == ["a", "b"]
    assert Settings(_env_file=None).nexus_plugins == ""  # type: ignore[call-arg]  # rien par défaut


def test_plugin_is_registered_once() -> None:
    states = load_plugins(["tests.fake_plugin", "tests.fake_plugin"])
    assert [s.loaded for s in states] == [True, True]
    load_plugins(["tests.fake_plugin"])
    assert fake_plugin.CALLS == ["register"]


def test_broken_or_invalid_plugins_never_stop_nexus() -> None:
    states = {
        s.name: s
        for s in load_plugins(
            ["tests.fake_plugin_broken", "paquet_absent_xyz", "../evil", "tests.conftest"]
        )
    }
    assert not any(s.loaded for s in states.values())
    assert "boîte déjà enregistrée" in (states["tests.fake_plugin_broken"].error or "")
    assert "ModuleNotFoundError" in (states["paquet_absent_xyz"].error or "")
    assert states["../evil"].error == "nom de module invalide"
    assert "register()" in (states["tests.conftest"].error or "")


# ═══ Fichiers joints ══════════════════════════════════════════════


class FakeStore:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.files = {
            "a" * 32: ("ventes_2026.csv", b"date;ca\n"),
            "b" * 32: ("Relevé octobre.pdf", b"%PDF"),
            "c" * 32: ("autre.csv", b"x"),  # d'une autre conversation
        }

    async def get(self, attachment_id: str) -> tuple[AttachmentInfo, bytes] | None:
        self.asked.append(attachment_id)
        if attachment_id not in self.files:
            return None
        name, data = self.files[attachment_id]
        info = AttachmentInfo(
            id=attachment_id,
            name=name,
            media_type="application/octet-stream",
            kind="document",
            size=len(data),
            meta={},
            created_at=datetime(2026, 10, 23, tzinfo=UTC),
        )
        return info, data


async def test_only_files_cited_by_the_conversation_are_reachable() -> None:
    store = FakeStore()
    files = ConversationFiles(store, ["a" * 32, "b" * 32, "a" * 32])
    assert [i.name for i in await files.list()] == ["ventes_2026.csv", "Relevé octobre.pdf"]
    assert "c" * 32 not in store.asked
    with pytest.raises(FilesError, match="introuvable"):
        await files.load("c" * 32)
    assert (await files.load("releve octobre.PDF"))[0].id == "b" * 32  # casse et accents
    assert (await files.load("ventes_2026"))[1] == b"date;ca\n"  # sans extension
    assert (await files.load("a" * 32))[0].name == "ventes_2026.csv"


async def test_environment_without_conversation_has_no_files() -> None:
    env = ToolEnvironment(Settings(_env_file=None))  # type: ignore[call-arg]
    assert await env.conversation_files().list() == []
    with pytest.raises(FilesError, match="glisser le fichier"):
        await env.conversation_files().load("x.csv")


async def test_environment_client_is_reused_and_closed() -> None:
    class Client:
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    env = ToolEnvironment(Settings(_env_file=None))  # type: ignore[call-arg]
    first = env.client("convert", Client)
    assert env.client("convert", Client) is first
    await env.aclose()
    assert first.closed


# ═══ Client commun : multipart et téléchargement (utilisés par les extensions) ═══


async def test_app_client_sends_multipart_and_downloads_bytes() -> None:
    import httpx

    from app.tools.http import AppClient, AppRequestError

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/upload":
            return httpx.Response(201, json={"ok": True})
        if request.url.path == "/api/export":
            return httpx.Response(200, content=b"PK\x03\x04")
        return httpx.Response(422, json={"detail": "Format inconnu"})

    class Demo(AppClient):
        app = "demo"
        label = "Atelier Démo"
        error_keys = ("detail",)

    client = Demo("http://demo.test/api", transport=httpx.MockTransport(handler))
    out = await client.request(
        "POST", "upload", files={"file": ("a.csv", b"x;y\n", "text/csv")}, form={"account_id": "3"}
    )
    assert out == {"ok": True}
    body = seen[-1].content
    assert b'filename="a.csv"' in body and b'name="account_id"' in body and b"x;y" in body
    assert await client.download("export", params={"format": "xlsx"}) == b"PK\x03\x04"
    assert seen[-1].url.params["format"] == "xlsx"
    with pytest.raises(AppRequestError, match="Format inconnu"):
        await client.download("autre")
    await client.aclose()
