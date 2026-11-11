"""Étape 13 : recherche dans l'historique des conversations."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.conversations import ConversationRepository
from app.db.models import ArtifactRow, ConversationRow
from app.db.search import like_pattern, normalize, search_text, snippet, terms
from tests.fakes import ScriptedProvider, text_response, tool_response
from tests.test_conversations import anthropic, client, sessions, user  # noqa: F401

BACKEND = Path(__file__).resolve().parents[1]


def test_normalize_and_terms() -> None:
    assert normalize("  Échéance\n  ÉTÉ  ") == "echeance ete"
    assert terms("Mesure DAX  dax a") == ["mesure", "dax"]
    assert like_pattern("100%_x") == "%100\\%\\_x%"


def test_search_text_skips_tool_results() -> None:
    history = [
        user("Calcule la marge"),
        {"role": "user", "content": [{"type": "tool_result", "content": "SECRET brut"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Voici la mesure."}]},
    ]
    text = search_text("Marge", history, [("Mesure DAX", "Marge = SUM(Ventes[Montant])")])
    assert "calcule la marge" in text and "mesure dax" in text and "secret" not in text


def test_snippet_keeps_accents_around_the_match() -> None:
    long = "Début. " + "x " * 200 + "La réunion d'échéance est jeudi. " + "y " * 200
    found = snippet(["rien", long], ["echeance"])
    assert found is not None and "d'échéance" in found
    assert found.startswith("…") and found.endswith("…")
    assert snippet(["rien"], ["echeance"]) is None


def _converse(c: TestClient, llm: ScriptedProvider, agent: str, text: str, answer: str) -> str:
    cid = c.post("/api/conversations", json={"agent": agent}).json()["id"]
    llm.script = [text_response(answer)]
    r = c.post(f"/api/agents/{agent}/run", json={"messages": [user(text)], "conversation_id": cid})
    assert r.status_code == 200
    return str(cid)


def test_search_endpoint(client: TestClient, anthropic: ScriptedProvider) -> None:  # noqa: F811
    first = _converse(
        client, anthropic, "assistant", "Prépare la réunion d'équipe", "Ordre du jour prêt."
    )
    second = _converse(client, anthropic, "assistant", "Bonjour", "Bonjour !")

    # Artefact : son contenu est cherchable
    anthropic.script = [
        tool_response(
            "publish_artifact",
            {"kind": "markdown", "title": "Budget 2027", "content": "Hausse des loyers"},
            call_id="a1",
        ),
        text_response("Publié."),
    ]
    detail = client.get(f"/api/conversations/{second}").json()
    messages = [*detail["history"], user("Publie le budget")]
    run = client.post(
        "/api/agents/assistant/run", json={"messages": messages, "conversation_id": second}
    )
    assert run.status_code == 200 and run.json()["stop_reason"] == "awaiting_approval"
    # Publication autorisée (APPROVAL_MODE=every_step, défaut)
    run = client.post(
        "/api/agents/assistant/run",
        json={
            "messages": [*messages, *run.json()["new_messages"]],
            "conversation_id": second,
            "approvals": {"a1": True},
        },
    )
    assert run.status_code == 200 and run.json()["stop_reason"] == "end_turn"

    hits = client.get("/api/conversations/search", params={"q": "REUNION equipe"}).json()
    assert [h["id"] for h in hits] == [first]
    assert "réunion d'équipe" in hits[0]["snippet"]

    hits = client.get("/api/conversations/search", params={"q": "loyers"}).json()
    assert [h["id"] for h in hits] == [second] and "Hausse des loyers" in hits[0]["snippet"]
    assert hits[0]["artifact_count"] == 1

    # Tous les mots doivent y être ; filtre par agent
    assert client.get("/api/conversations/search", params={"q": "reunion loyers"}).json() == []
    assert (
        client.get("/api/conversations/search", params={"q": "loyers", "agent": "tuteur"}).json()
        == []
    )
    # Les jokers LIKE sont des caractères ordinaires
    assert client.get("/api/conversations/search", params={"q": "%%"}).json() == []

    # Renommer rend le nouveau titre cherchable
    client.patch(f"/api/conversations/{first}", json={"title": "Séminaire Lyon"})
    hits = client.get("/api/conversations/search", params={"q": "seminaire"}).json()
    assert [h["id"] for h in hits] == [first] and hits[0]["title"] == "Séminaire Lyon"

    assert client.get("/api/conversations/search", params={"q": "x"}).status_code == 422


def test_migration_fills_existing_conversations(tmp_path: Path) -> None:
    db = tmp_path / "nexus.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    command.upgrade(cfg, "0002_conversations")

    history = [user("Où en est le chantier Bérénice ?")]
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO conversations (id, agent, title, history, turn_meta, pending, created_at, updated_at)"
            " VALUES ('c1', 'assistant', 'Chantier', ?, '{}', '[]', '2026-10-01', '2026-10-01')",
            (json.dumps(history),),
        )
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        (text,) = conn.execute("SELECT search_text FROM conversations WHERE id = 'c1'").fetchone()
    assert "berenice" in text and "chantier" in text


@pytest.mark.parametrize("query", ["  ", "a b"])
def test_empty_terms_give_no_result(client: TestClient, query: str) -> None:  # noqa: F811
    assert client.get("/api/conversations/search", params={"q": query}).json() == []


async def test_lists_read_no_heavy_column_and_search_one_artifact_query(
    sessions: async_sessionmaker,  # type: ignore[type-arg]  # noqa: F811
) -> None:
    """La liste et la recherche ne lisent pas le texte de recherche (jusqu'à 200 000 caractères
    par conversation), et la recherche lit les artefacts en une requête, pas une par résultat."""
    async with sessions() as s:
        for name in ("alpha", "bravo", "charlie", "delta"):
            row = ConversationRow(
                agent="assistant",
                title=f"Budget {name}",
                history=[user(f"Prépare le budget {name}")],
                search_text=f"budget {name} prepare le budget rapport detaille du trimestre",
            )
            s.add(row)
            await s.flush()
            s.add(
                ArtifactRow(
                    conversation_id=row.id, agent="assistant", kind="markdown",
                    title=f"Rapport {name}", content="Budget détaillé du trimestre",
                )
            )  # fmt: skip
        await s.commit()
    repo = ConversationRepository(sessions)
    statements: list[str] = []
    engine = sessions.kw["bind"].sync_engine

    def record(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        hits = await repo.search("budget trimestre")
        searched = list(statements)
        statements.clear()
        one = await repo.search("budget delta")
        single = list(statements)
        statements.clear()
        listed = await repo.recent()
        recent = list(statements)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(hits) == 4 and all(h.artifact_count == 1 and h.message_count == 1 for h in hits)
    assert all("udget" in (h.snippet or "") for h in hits)
    assert [h.title for h in one] == ["Budget delta"]
    # Même nombre de requêtes pour 1 ou 4 résultats : conversations, puis leurs artefacts
    assert len(searched) == len(single) == 2
    assert len(listed) == 4 and len(recent) == 1
    for sql in (searched[0], recent[0]):
        columns = sql.split("FROM")[0]
        assert "search_text" not in columns and "turn_meta" not in columns
        assert "conversations.history" in columns
