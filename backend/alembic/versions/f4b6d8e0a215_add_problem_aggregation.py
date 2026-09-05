"""add problem aggregation

Revision ID: f4b6d8e0a215
Revises: d2a4c6e8f013
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4b6d8e0a215"
down_revision: str | Sequence[str] | None = "d2a4c6e8f013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create exact primary-problem aggregation persistence."""
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "problem_aggregation_completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    op.create_table(
        "problems",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(length=255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("mapping_key", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(definition)) > 0",
            name="ck_problems_definition_not_empty",
        ),
        sa.CheckConstraint(
            "mapping_version = 'PRIMARY-PROBLEM-EXACT-V1'",
            name="ck_problems_mapping_version",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "mapping_key",
            name="uq_problems_run_mapping_key",
        ),
    )
    op.create_index(
        op.f("ix_problems_evaluation_run_id"),
        "problems",
        ["evaluation_run_id"],
        unique=False,
    )

    op.create_table(
        "result_problem_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_result_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "role = 'primary'",
            name="ck_result_problem_links_role",
        ),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.ForeignKeyConstraint(
            ["evaluation_result_id"],
            ["evaluation_results.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_result_id",
            "role",
            name="uq_result_problem_links_result_role",
        ),
    )
    op.create_index(
        op.f("ix_result_problem_links_problem_id"),
        "result_problem_links",
        ["problem_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_result_problem_links_evaluation_result_id"),
        "result_problem_links",
        ["evaluation_result_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove exact primary-problem aggregation persistence."""
    op.drop_index(
        op.f("ix_result_problem_links_evaluation_result_id"),
        table_name="result_problem_links",
    )
    op.drop_index(
        op.f("ix_result_problem_links_problem_id"),
        table_name="result_problem_links",
    )
    op.drop_table("result_problem_links")
    op.drop_index(
        op.f("ix_problems_evaluation_run_id"),
        table_name="problems",
    )
    op.drop_table("problems")

    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.drop_column("problem_aggregation_completed_at")
