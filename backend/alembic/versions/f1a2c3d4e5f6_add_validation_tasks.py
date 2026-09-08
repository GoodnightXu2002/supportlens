"""add validation tasks

Revision ID: f1a2c3d4e5f6
Revises: c7e9a1b3d524
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c7e9a1b3d524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validation_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("optimization_target_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("case_scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("candidate_responses", sa.JSON(), nullable=True),
        sa.Column("runner_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "runner_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'submitted', 'failed')",
            name="ck_validation_tasks_status",
        ),
        sa.CheckConstraint(
            "length(runner_token_hash) = 64",
            name="ck_validation_tasks_runner_token_hash_length",
        ),
        sa.CheckConstraint(
            "(status = 'submitted' AND submitted_at IS NOT NULL "
            "AND candidate_responses IS NOT NULL) OR "
            "(status <> 'submitted' AND submitted_at IS NULL)",
            name="ck_validation_tasks_submission_state",
        ),
        sa.ForeignKeyConstraint(
            ["optimization_target_id"], ["optimization_targets.id"]
        ),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["evaluation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_tasks_optimization_target_id",
        "validation_tasks",
        ["optimization_target_id"],
    )
    op.create_index(
        "ix_validation_tasks_baseline_run_id",
        "validation_tasks",
        ["baseline_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_validation_tasks_baseline_run_id", table_name="validation_tasks"
    )
    op.drop_index(
        "ix_validation_tasks_optimization_target_id",
        table_name="validation_tasks",
    )
    op.drop_table("validation_tasks")
