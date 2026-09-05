"""extend runs for baseline execution

Revision ID: b7f1c3d5e902
Revises: e8d2f4a6b901
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7f1c3d5e902"
down_revision: str | Sequence[str] | None = "e8d2f4a6b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the frozen A2 execution status and snapshot fields."""
    with op.batch_alter_table("evaluation_runs", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_evaluation_runs_status", type_="check")
        batch_op.add_column(
            sa.Column(
                "case_errors",
                sa.JSON(none_as_null=True),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("business_reference_snapshot", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_evaluation_runs_status",
            "status IN "
            "('pending', 'running', 'completed', 'partial_failure', "
            "'failed', 'invalid')",
        )

    with op.batch_alter_table("evaluation_results") as batch_op:
        batch_op.add_column(
            sa.Column("raw_judge_output", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    """Remove the A2 execution status and snapshot fields."""
    with op.batch_alter_table("evaluation_results") as batch_op:
        batch_op.drop_column("raw_judge_output")

    with op.batch_alter_table("evaluation_runs", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_evaluation_runs_status", type_="check")
        batch_op.create_check_constraint(
            "ck_evaluation_runs_status",
            "status IN ('pending', 'running', 'completed', 'failed')",
        )
        batch_op.drop_column("business_reference_snapshot")
        batch_op.drop_column("case_errors")
