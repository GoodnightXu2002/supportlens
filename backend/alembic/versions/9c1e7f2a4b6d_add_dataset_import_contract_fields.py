"""add dataset import contract fields

Revision ID: 9c1e7f2a4b6d
Revises: 6f30e8e34eea
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c1e7f2a4b6d"
down_revision: str | Sequence[str] | None = "6f30e8e34eea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the frozen FR-01.1 Dataset persistence contract."""
    with op.batch_alter_table("datasets", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(length=32), nullable=False))
        batch_op.add_column(
            sa.Column(
                "privacy_status",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("representativeness_statement", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_datasets_source",
            "source IN ('user_upload', 'fixture_import')",
        )
        batch_op.create_check_constraint(
            "ck_datasets_privacy_status",
            "privacy_status IN "
            "('synthetic', 'deidentified', 'may_contain_personal_data', 'unknown')",
        )


def downgrade() -> None:
    """Remove the FR-01.1 Dataset persistence contract fields."""
    with op.batch_alter_table("datasets", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_datasets_privacy_status", type_="check")
        batch_op.drop_constraint("ck_datasets_source", type_="check")
        batch_op.drop_column("representativeness_statement")
        batch_op.drop_column("privacy_status")
        batch_op.drop_column("source")
