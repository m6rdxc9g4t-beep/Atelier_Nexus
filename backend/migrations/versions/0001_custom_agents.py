"""Agents personnalisés.

Revision ID: 0001_custom_agents
Revises:
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_custom_agents"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(41), nullable=False),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(40), nullable=False, server_default="bot"),
        sa.Column("category", sa.String(40), nullable=False, server_default="Mes agents"),
        sa.Column("toolsets", sa.JSON(), nullable=False),
        sa.Column("privacy", sa.String(20), nullable=False, server_default="standard"),
        sa.Column("default_provider", sa.String(20), nullable=True),
        sa.Column("starters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_custom_agents_name", "custom_agents", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_custom_agents_name", table_name="custom_agents")
    op.drop_table("custom_agents")
