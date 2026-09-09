"""link validation tasks to candidate runs

Revision ID: b3c4d5e6f7a8
Revises: f1a2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_validation_tasks")
    with op.batch_alter_table("validation_tasks") as batch_op:
        batch_op.add_column(sa.Column("candidate_run_id", sa.Uuid(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_validation_tasks_candidate_run_id",
            ["candidate_run_id"],
        )
        batch_op.create_foreign_key(
            "fk_validation_tasks_candidate_run_id_evaluation_runs",
            "evaluation_runs",
            ["candidate_run_id"],
            ["id"],
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_validation_tasks")
    with op.batch_alter_table("validation_tasks") as batch_op:
        batch_op.drop_constraint(
            "fk_validation_tasks_candidate_run_id_evaluation_runs",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "uq_validation_tasks_candidate_run_id",
            type_="unique",
        )
        batch_op.drop_column("candidate_run_id")
