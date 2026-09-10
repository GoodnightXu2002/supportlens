"""add optimization target optimization suggestions

Revision ID: e7b9d1f5a3c2
Revises: b3c4d5e6f7a8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b9d1f5a3c2"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "optimization_targets",
        sa.Column("optimization_suggestions", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("optimization_targets") as batch_op:
        batch_op.drop_column("optimization_suggestions")
