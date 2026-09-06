"""add candidate validation snapshots and case comparisons

Revision ID: e3c5a7b9d102
Revises: d8e1f4a6b203
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c5a7b9d102"
down_revision: str | Sequence[str] | None = "d8e1f4a6b203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.add_column(
            sa.Column("candidate_responses_snapshot", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("response_set_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("candidate_manifest_snapshot", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("candidate_validation_summary", sa.JSON(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_evaluation_runs_response_set_hash_length",
            "response_set_hash IS NULL OR length(response_set_hash) = 64",
        )
        batch_op.create_foreign_key(
            "fk_evaluation_runs_target_id_optimization_targets",
            "optimization_targets",
            ["target_id"],
            ["id"],
        )

    op.create_table(
        "case_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_run_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=255), nullable=False),
        sa.Column("baseline_evaluation_result_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_evaluation_result_id", sa.Uuid(), nullable=False),
        sa.Column("movement", sa.String(length=32), nullable=False),
        sa.Column("target_problem_status", sa.String(length=32), nullable=False),
        sa.Column("target_worse", sa.Boolean(), nullable=False),
        sa.Column("regression_level", sa.String(length=32), nullable=True),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("rule_result_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "movement IN ('improved', 'partially_improved', 'stable', "
            "'regressed', 'inconclusive')",
            name="ck_case_comparisons_movement",
        ),
        sa.CheckConstraint(
            "target_problem_status IN ('present', 'absent', "
            "'not_applicable', 'inconclusive')",
            name="ck_case_comparisons_target_problem_status",
        ),
        sa.CheckConstraint(
            "regression_level IS NULL OR regression_level IN "
            "('critical', 'major', 'minor')",
            name="ck_case_comparisons_regression_level",
        ),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["evaluation_runs.id"]),
        sa.ForeignKeyConstraint(["candidate_run_id"], ["evaluation_runs.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["optimization_targets.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(
            ["baseline_evaluation_result_id"], ["evaluation_results.id"]
        ),
        sa.ForeignKeyConstraint(
            ["candidate_evaluation_result_id"], ["evaluation_results.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_run_id",
            "candidate_run_id",
            "conversation_id",
            name="uq_case_comparisons_run_pair_conversation",
        ),
    )


def downgrade() -> None:
    op.drop_table("case_comparisons")
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_evaluation_runs_target_id_optimization_targets",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_evaluation_runs_response_set_hash_length", type_="check"
        )
        batch_op.drop_column("candidate_validation_summary")
        batch_op.drop_column("candidate_manifest_snapshot")
        batch_op.drop_column("response_set_hash")
        batch_op.drop_column("candidate_responses_snapshot")
