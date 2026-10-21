"""Déclencheurs de workflows : horaires et événements, curseurs par application, origine des
exécutions (docs/declencheurs-api.md).

Revision ID: 0007_workflow_triggers
Revises: 0006_workflow_runs
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_workflow_triggers"
down_revision: str | None = "0006_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_triggers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(36),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("app", sa.String(20), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("max_runs_per_hour", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("internal", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_triggers_workflow_id", "workflow_triggers", ["workflow_id"])
    op.create_index("ix_workflow_triggers_app", "workflow_triggers", ["app"])
    op.create_table(
        "trigger_cursors",
        sa.Column("app", sa.String(20), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("workflow_runs") as batch:
        batch.add_column(sa.Column("trigger_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("trigger_event", sa.JSON(), nullable=True))
    op.create_index("ix_workflow_runs_trigger_id", "workflow_runs", ["trigger_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_trigger_id", table_name="workflow_runs")
    # L'origine d'une exécution redevient « manuelle » : la version 0006 ne connaît qu'elle
    op.execute("UPDATE workflow_runs SET \"trigger\" = 'manual' WHERE \"trigger\" <> 'manual'")
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_column("trigger_event")
        batch.drop_column("trigger_id")
    op.drop_table("trigger_cursors")
    op.drop_index("ix_workflow_triggers_app", table_name="workflow_triggers")
    op.drop_index("ix_workflow_triggers_workflow_id", table_name="workflow_triggers")
    op.drop_table("workflow_triggers")
