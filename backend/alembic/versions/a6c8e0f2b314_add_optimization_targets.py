"""add optimization targets

Revision ID: a6c8e0f2b314
Revises: f4b6d8e0a215
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6c8e0f2b314"
down_revision: str | Sequence[str] | None = "f4b6d8e0a215"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create version-one OptimizationTarget draft persistence."""
    op.create_table(
        "optimization_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("inclusion_criteria", sa.Text(), nullable=False),
        sa.Column("exclusion_criteria", sa.Text(), nullable=False),
        sa.Column(
            "baseline_affected_case_ids",
            sa.JSON(none_as_null=True),
            nullable=False,
        ),
        sa.Column("reference_basis", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("failure_mode", sa.String(length=64), nullable=False),
        sa.Column("baseline_metric", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("expected_observable_change", sa.Text(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hypothesis_statement", sa.Text(), nullable=True),
        sa.Column(
            "hypothesis_evidence_refs",
            sa.JSON(none_as_null=True),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("change_surface", sa.Text(), nullable=True),
        sa.Column("planned_change", sa.Text(), nullable=True),
        sa.Column(
            "guardrails",
            sa.JSON(none_as_null=True),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "change_status",
            sa.String(length=32),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("target_case_ids", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("regression_case_ids", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("challenge_case_ids", sa.JSON(none_as_null=True), nullable=False),
        sa.Column(
            "protected_capabilities",
            sa.JSON(none_as_null=True),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("baseline_snapshot", sa.JSON(none_as_null=True), nullable=False),
        sa.Column(
            "evaluation_config_snapshot",
            sa.JSON(none_as_null=True),
            nullable=False,
        ),
        sa.Column("policy_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_optimization_targets_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_optimization_targets_status",
        ),
        sa.CheckConstraint(
            "change_status = 'planned'",
            name="ck_optimization_targets_change_status",
        ),
        sa.CheckConstraint(
            "length(trim(definition)) > 0",
            name="ck_optimization_targets_definition_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(inclusion_criteria)) > 0",
            name="ck_optimization_targets_inclusion_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(exclusion_criteria)) > 0",
            name="ck_optimization_targets_exclusion_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(expected_observable_change)) > 0",
            name="ck_optimization_targets_expected_change_not_empty",
        ),
        sa.CheckConstraint(
            "failure_mode IN "
            "('incorrect_information', 'incomplete_unresolved', "
            "'intent_relevance_failure', 'improper_refusal', "
            "'policy_procedure_violation', 'other')",
            name="ck_optimization_targets_failure_mode",
        ),
        sa.CheckConstraint(
            "confirmed_by IS NULL OR length(trim(confirmed_by)) > 0",
            name="ck_optimization_targets_confirmer_not_empty",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND confirmed_by IS NULL AND confirmed_at IS NULL) "
            "OR (status = 'confirmed' AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL)",
            name="ck_optimization_targets_confirmation_state",
        ),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["evaluation_runs.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_run_id",
            "problem_id",
            "version",
            name="uq_optimization_targets_run_problem_version",
        ),
    )
    op.create_index(
        op.f("ix_optimization_targets_baseline_run_id"),
        "optimization_targets",
        ["baseline_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_optimization_targets_problem_id"),
        "optimization_targets",
        ["problem_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove OptimizationTarget persistence."""
    op.drop_index(
        op.f("ix_optimization_targets_problem_id"),
        table_name="optimization_targets",
    )
    op.drop_index(
        op.f("ix_optimization_targets_baseline_run_id"),
        table_name="optimization_targets",
    )
    op.drop_table("optimization_targets")
