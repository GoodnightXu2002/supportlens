"""add candidate final decision

Revision ID: a9c2e4f6b108
Revises: e3c5a7b9d102
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9c2e4f6b108"
down_revision: str | Sequence[str] | None = "e3c5a7b9d102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_evaluation_runs")
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.add_column(
            sa.Column("final_decision", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decided_by", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("override_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_evaluation_runs_final_decision",
            "final_decision IS NULL OR final_decision IN ('accept', 'continue')",
        )
        batch_op.create_check_constraint(
            "ck_evaluation_runs_final_decision_fields",
            "(final_decision IS NULL AND decided_by IS NULL AND "
            "decided_at IS NULL AND reason IS NULL AND override_reason IS NULL) OR "
            "(final_decision IS NOT NULL AND decided_by IS NOT NULL AND "
            "length(trim(decided_by)) > 0 AND decided_at IS NOT NULL AND "
            "reason IS NOT NULL AND length(trim(reason)) > 0)",
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_evaluation_runs")
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.drop_constraint(
            "ck_evaluation_runs_final_decision_fields", type_="check"
        )
        batch_op.drop_constraint(
            "ck_evaluation_runs_final_decision", type_="check"
        )
        batch_op.drop_column("override_reason")
        batch_op.drop_column("reason")
        batch_op.drop_column("decided_at")
        batch_op.drop_column("decided_by")
        batch_op.drop_column("final_decision")
