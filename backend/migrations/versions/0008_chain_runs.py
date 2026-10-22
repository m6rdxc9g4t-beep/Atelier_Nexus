"""Chaînes d'agents : exécutions (demande, étape courante, livrables validés).

Revision ID: 0008_chain_runs
Revises: 0007_workflow_triggers
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_chain_runs"
down_revision: str | None = "0007_workflow_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chain_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chain", sa.String(41), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chain_runs_chain", "chain_runs", ["chain"])
    op.create_index("ix_chain_runs_updated_at", "chain_runs", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_chain_runs_updated_at", table_name="chain_runs")
    op.drop_index("ix_chain_runs_chain", table_name="chain_runs")
    op.drop_table("chain_runs")
