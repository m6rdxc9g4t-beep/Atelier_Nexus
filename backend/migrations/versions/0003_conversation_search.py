"""Recherche dans l'historique : colonne search_text, remplie pour les conversations existantes.

Revision ID: 0003_conversation_search
Revises: 0002_conversations
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.search import search_text

revision: str = "0003_conversation_search"
down_revision: str | None = "0002_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("search_text", sa.Text(), nullable=False, server_default="")
    )
    conn = op.get_bind()
    conversations = sa.table(
        "conversations",
        sa.column("id", sa.String),
        sa.column("title", sa.String),
        sa.column("history", sa.JSON),
        sa.column("search_text", sa.Text),
    )
    artifacts = sa.table(
        "artifacts",
        sa.column("conversation_id", sa.String),
        sa.column("title", sa.String),
        sa.column("content", sa.Text),
    )
    by_conversation: dict[str, list[tuple[str, str]]] = {}
    for cid, title, content in conn.execute(
        sa.select(artifacts.c.conversation_id, artifacts.c.title, artifacts.c.content)
    ):
        by_conversation.setdefault(cid, []).append((title or "", content or ""))
    for cid, title, history in conn.execute(
        sa.select(conversations.c.id, conversations.c.title, conversations.c.history)
    ):
        text = search_text(title or "", history or [], by_conversation.get(cid, []))
        conn.execute(
            conversations.update().where(conversations.c.id == cid).values(search_text=text)
        )


def downgrade() -> None:
    op.drop_column("conversations", "search_text")
