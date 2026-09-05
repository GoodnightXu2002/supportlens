"""add evaluation results

Revision ID: e8d2f4a6b901
Revises: c4a91b7e2d63
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8d2f4a6b901"
down_revision: str | Sequence[str] | None = "c4a91b7e2d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistence for valid per-case JudgeOutput results."""
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("judgment", sa.String(length=32), nullable=False),
        sa.Column("primary_failure_mode", sa.String(length=64), nullable=True),
        sa.Column(
            "secondary_flags",
            sa.JSON(none_as_null=True),
            nullable=False,
        ),
        sa.Column("problem", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("evidence", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "judgment IN ('success', 'warning', 'failure', 'uncertain')",
            name="ck_evaluation_results_judgment",
        ),
        sa.CheckConstraint(
            "(judgment = 'failure' AND severity IS NOT NULL) OR "
            "(judgment <> 'failure' AND severity IS NULL)",
            name="ck_evaluation_results_judgment_severity",
        ),
        sa.CheckConstraint(
            "primary_failure_mode IS NULL OR primary_failure_mode IN "
            "('incorrect_information', 'incomplete_unresolved', "
            "'intent_relevance_failure', 'improper_refusal', "
            "'policy_procedure_violation', 'other')",
            name="ck_evaluation_results_primary_failure_mode",
        ),
        sa.CheckConstraint(
            "length(trim(rationale)) > 0",
            name="ck_evaluation_results_rationale_not_empty",
        ),
        sa.CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_evaluation_results_severity",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "conversation_id",
            name="uq_evaluation_results_run_conversation",
        ),
    )
    op.create_index(
        op.f("ix_evaluation_results_conversation_id"),
        "evaluation_results",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_results_evaluation_run_id"),
        "evaluation_results",
        ["evaluation_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove EvaluationResult persistence."""
    op.drop_index(
        op.f("ix_evaluation_results_evaluation_run_id"),
        table_name="evaluation_results",
    )
    op.drop_index(
        op.f("ix_evaluation_results_conversation_id"),
        table_name="evaluation_results",
    )
    op.drop_table("evaluation_results")
