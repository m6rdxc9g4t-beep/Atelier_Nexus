"""Pièces jointes des conversations.

Revision ID: 0004_attachments
Revises: 0003_conversation_search
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_attachments"
down_revision: str | None = "0003_conversation_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attachments_conversation_id", "attachments", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_conversation_id", table_name="attachments")
    op.drop_table("attachments")
