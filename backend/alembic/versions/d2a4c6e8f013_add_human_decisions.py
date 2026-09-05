"""add human decisions

Revision ID: d2a4c6e8f013
Revises: b7f1c3d5e902
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a4c6e8f013"
down_revision: str | Sequence[str] | None = "b7f1c3d5e902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one immutable human decision per evaluation result."""
    op.create_table(
        "human_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_result_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer", sa.String(length=255), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("original_result", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("final_result", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(trim(reviewer)) > 0",
            name="ck_human_decisions_reviewer_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_result_id"],
            ["evaluation_results.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_result_id",
            name="uq_human_decisions_evaluation_result_id",
        ),
    )


def downgrade() -> None:
    """Remove human decision persistence."""
    op.drop_table("human_decisions")
