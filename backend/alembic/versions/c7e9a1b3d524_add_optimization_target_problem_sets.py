"""add optimization target problem sets

Revision ID: c7e9a1b3d524
Revises: b2d4f6a8c013
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e9a1b3d524"
down_revision: str | Sequence[str] | None = "b2d4f6a8c013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _problem_set_key(problem_ids: list[str]) -> str:
    canonical = ",".join(sorted(problem_ids))
    return hashlib.sha256(canonical.encode()).hexdigest()


def upgrade() -> None:
    targets = sa.table(
        "optimization_targets",
        sa.column("id", sa.Uuid()),
        sa.column("problem_id", sa.Uuid()),
        sa.column("problem_ids", sa.JSON()),
        sa.column("problem_set_key", sa.String(64)),
    )
    op.add_column(
        "optimization_targets",
        sa.Column("problem_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "optimization_targets",
        sa.Column("problem_set_key", sa.String(length=64), nullable=True),
    )
    connection = op.get_bind()
    for target_id, problem_id in connection.execute(
        sa.select(targets.c.id, targets.c.problem_id)
    ):
        problem_ids = [str(problem_id)]
        connection.execute(
            sa.update(targets)
            .where(targets.c.id == target_id)
            .values(
                problem_ids=problem_ids,
                problem_set_key=_problem_set_key(problem_ids),
            )
        )
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.alter_column("problem_ids", nullable=False)
        batch_op.alter_column("problem_set_key", nullable=False)
        batch_op.drop_constraint(
            "uq_optimization_targets_run_problem_version", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_optimization_targets_run_problem_set_version",
            ["baseline_run_id", "problem_set_key", "version"],
        )


def downgrade() -> None:
    targets = sa.table(
        "optimization_targets",
        sa.column("problem_id", sa.Uuid()),
        sa.column("problem_ids", sa.JSON()),
    )
    for problem_id, problem_ids in op.get_bind().execute(
        sa.select(targets.c.problem_id, targets.c.problem_ids)
    ):
        if problem_ids != [str(problem_id)]:
            raise RuntimeError(
                "Cannot downgrade multi-problem targets without data loss."
            )
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.drop_constraint(
            "uq_optimization_targets_run_problem_set_version", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_optimization_targets_run_problem_version",
            ["baseline_run_id", "problem_id", "version"],
        )
        batch_op.drop_column("problem_set_key")
        batch_op.drop_column("problem_ids")
