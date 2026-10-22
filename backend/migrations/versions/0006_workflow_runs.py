"""Workflows v2 : colonne `version`, agent facultatif (workflow de suite), exécutions persistées.

Revision ID: 0006_workflow_runs
Revises: 0005_workflows
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_workflow_runs"
down_revision: str | None = "0005_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch : SQLite ne sait pas modifier une colonne en place (table recopiée)
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.alter_column("agent", existing_type=sa.String(41), nullable=True)
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("pending", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    # Les workflows v2 n'ont pas d'équivalent v1 : ils sont retirés avant de revenir en arrière
    op.execute("DELETE FROM workflows WHERE version <> 1")
    with op.batch_alter_table("workflows") as batch:
        batch.alter_column("agent", existing_type=sa.String(41), nullable=False)
        batch.drop_column("version")
