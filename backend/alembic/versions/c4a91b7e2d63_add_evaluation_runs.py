"""add evaluation runs

Revision ID: c4a91b7e2d63
Revises: 9c1e7f2a4b6d
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4a91b7e2d63"
down_revision: str | Sequence[str] | None = "9c1e7f2a4b6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistence for frozen EvaluationRun fields."""
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_label", sa.String(length=255), nullable=True),
        sa.Column("candidate_change_summary", sa.Text(), nullable=True),
        sa.Column("judge_model", sa.String(length=255), nullable=False),
        sa.Column(
            "judge_contract_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("run_source", sa.String(length=32), nullable=False),
        sa.Column("response_set_key", sa.String(length=255), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "run_source IN ('seed', 'live')",
            name="ck_evaluation_runs_run_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_evaluation_runs_status",
        ),
        sa.CheckConstraint(
            "run_type IN ('baseline', 'candidate')",
            name="ck_evaluation_runs_run_type",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"],
            ["evaluation_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_runs_dataset_id"),
        "evaluation_runs",
        ["dataset_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove EvaluationRun persistence."""
    op.drop_index(
        op.f("ix_evaluation_runs_dataset_id"),
        table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")
