"""Allow confirmed and frozen targets without hypothesis confirmation.

Revision ID: b2d4f6a8c013
Revises: a9c2e4f6b108
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2d4f6a8c013"
down_revision: str | Sequence[str] | None = "a9c2e4f6b108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.drop_constraint(
            "ck_optimization_targets_confirmation_state", type_="check",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_confirmation_state",
            "(status = 'draft' AND (confirmed_by IS NULL "
            "OR hypothesis_confirmed_by IS NULL)) OR "
            "(status IN ('confirmed', 'frozen') AND confirmed_by IS NOT NULL)",
        )


def downgrade() -> None:
    incompatible = op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM optimization_targets "
        "WHERE status IN ('confirmed', 'frozen') "
        "AND hypothesis_confirmed_by IS NULL"
    ))
    if incompatible:
        raise RuntimeError(
            "Cannot restore required hypothesis confirmation without changing "
            "existing records. Restore a pre-upgrade backup instead."
        )
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.drop_constraint(
            "ck_optimization_targets_confirmation_state", type_="check",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_confirmation_state",
            "(status = 'draft' AND (confirmed_by IS NULL "
            "OR hypothesis_confirmed_by IS NULL)) OR "
            "(status IN ('confirmed', 'frozen') AND confirmed_by IS NOT NULL "
            "AND hypothesis_confirmed_by IS NOT NULL)",
        )
