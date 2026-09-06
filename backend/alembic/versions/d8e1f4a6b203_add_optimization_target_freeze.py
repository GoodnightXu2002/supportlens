"""add optimization target confirmation and freeze

Revision ID: d8e1f4a6b203
Revises: a6c8e0f2b314
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e1f4a6b203"
down_revision: str | Sequence[str] | None = "a6c8e0f2b314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add separate hypothesis confirmation and immutable freeze metadata."""
    op.execute(
        sa.text(
            "UPDATE optimization_targets "
            "SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL "
            "WHERE status = 'confirmed'"
        )
    )
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "hypothesis_confirmed_by",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "hypothesis_confirmed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("plan_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("frozen_by", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "frozen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_confirmation_state",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_status",
            "status IN ('draft', 'confirmed', 'frozen')",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_target_confirmation_pair",
            "(confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_hypothesis_confirmation_pair",
            "(hypothesis_confirmed_by IS NULL "
            "AND hypothesis_confirmed_at IS NULL) OR "
            "(hypothesis_confirmed_by IS NOT NULL "
            "AND hypothesis_confirmed_at IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_hypothesis_requires_target",
            "hypothesis_confirmed_by IS NULL OR confirmed_by IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_confirmation_state",
            "(status = 'draft' AND (confirmed_by IS NULL "
            "OR hypothesis_confirmed_by IS NULL)) OR "
            "(status IN ('confirmed', 'frozen') AND confirmed_by IS NOT NULL "
            "AND hypothesis_confirmed_by IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_hypothesis_confirmer_not_empty",
            "hypothesis_confirmed_by IS NULL "
            "OR length(trim(hypothesis_confirmed_by)) > 0",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_freezer_not_empty",
            "frozen_by IS NULL OR length(trim(frozen_by)) > 0",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_plan_hash_length",
            "plan_hash IS NULL OR length(plan_hash) = 64",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_frozen_state",
            "(status <> 'frozen' AND plan_hash IS NULL AND frozen_by IS NULL "
            "AND frozen_at IS NULL) OR (status = 'frozen' "
            "AND plan_hash IS NOT NULL AND frozen_by IS NOT NULL "
            "AND frozen_at IS NOT NULL)",
        )


def downgrade() -> None:
    """Return OptimizationTarget to its draft/confirmed foundation schema."""
    op.execute(
        sa.text(
            "UPDATE optimization_targets SET status = 'confirmed', "
            "plan_hash = NULL, frozen_by = NULL, frozen_at = NULL "
            "WHERE status = 'frozen'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE optimization_targets "
            "SET confirmed_by = NULL, confirmed_at = NULL "
            "WHERE status = 'draft'"
        )
    )
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.drop_constraint(
            "ck_optimization_targets_frozen_state",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_plan_hash_length",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_freezer_not_empty",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_hypothesis_confirmer_not_empty",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_confirmation_state",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_hypothesis_requires_target",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_hypothesis_confirmation_pair",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_target_confirmation_pair",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_optimization_targets_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_status",
            "status IN ('draft', 'confirmed')",
        )
        batch_op.create_check_constraint(
            "ck_optimization_targets_confirmation_state",
            "(status = 'draft' AND confirmed_by IS NULL "
            "AND confirmed_at IS NULL) OR "
            "(status = 'confirmed' AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL)",
        )
        batch_op.drop_column("frozen_at")
        batch_op.drop_column("frozen_by")
        batch_op.drop_column("plan_hash")
        batch_op.drop_column("hypothesis_confirmed_at")
        batch_op.drop_column("hypothesis_confirmed_by")
