"""Workflows rejouables.

Revision ID: 0005_workflows
Revises: 0004_attachments
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_workflows"
down_revision: str | None = "0004_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent", sa.String(41), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("source_conversation_id", sa.String(36), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflows_agent", "workflows", ["agent"])
    op.create_index("ix_workflows_updated_at", "workflows", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_workflows_updated_at", table_name="workflows")
    op.drop_index("ix_workflows_agent", table_name="workflows")
    op.drop_table("workflows")
