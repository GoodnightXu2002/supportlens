from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.database import Base


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "source IN ('user_upload', 'fixture_import')",
            name="ck_datasets_source",
        ),
        CheckConstraint(
            "privacy_status IN "
            "('synthetic', 'deidentified', 'may_contain_personal_data', 'unknown')",
            name="ck_datasets_privacy_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="v1.0", server_default="v1.0"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    privacy_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    representativeness_statement: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversations: Mapped[list[Conversation]] = relationship(back_populates="dataset")
    evaluation_runs: Mapped[list[EvaluationRun]] = relationship(
        back_populates="dataset"
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "external_id",
            name="uq_conversations_dataset_id_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("datasets.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="conversations")
    evaluation_results: Mapped[list[EvaluationResult]] = relationship(
        back_populates="conversation"
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('baseline', 'candidate')",
            name="ck_evaluation_runs_run_type",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'running', 'completed', 'partial_failure', "
            "'failed', 'invalid')",
            name="ck_evaluation_runs_status",
        ),
        CheckConstraint(
            "run_source IN ('seed', 'live')",
            name="ck_evaluation_runs_run_source",
        ),
        CheckConstraint(
            "response_set_hash IS NULL OR length(response_set_hash) = 64",
            name="ck_evaluation_runs_response_set_hash_length",
        ),
        CheckConstraint(
            "final_decision IS NULL OR final_decision IN ('accept', 'continue')",
            name="ck_evaluation_runs_final_decision",
        ),
        CheckConstraint(
            "(final_decision IS NULL AND decided_by IS NULL AND "
            "decided_at IS NULL AND reason IS NULL AND override_reason IS NULL) OR "
            "(final_decision IS NOT NULL AND decided_by IS NOT NULL AND "
            "length(trim(decided_by)) > 0 AND decided_at IS NOT NULL AND "
            "reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_evaluation_runs_final_decision_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id"),
        nullable=True,
    )
    target_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("optimization_targets.id"),
        nullable=True,
    )
    candidate_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidate_change_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    judge_model: Mapped[str] = mapped_column(String(255), nullable=False)
    judge_contract_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    run_source: Mapped[str] = mapped_column(String(32), nullable=False)
    response_set_key: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=list,
        server_default="[]",
    )
    business_reference_snapshot: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    problem_aggregation_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candidate_responses_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    response_set_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    candidate_manifest_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    candidate_validation_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    final_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="evaluation_runs")
    evaluation_results: Mapped[list[EvaluationResult]] = relationship(
        back_populates="evaluation_run"
    )
    problems: Mapped[list[Problem]] = relationship(
        back_populates="evaluation_run"
    )
    optimization_targets: Mapped[list[OptimizationTarget]] = relationship(
        back_populates="baseline_run",
        foreign_keys="OptimizationTarget.baseline_run_id",
    )
    baseline_case_comparisons: Mapped[list[CaseComparison]] = relationship(
        back_populates="baseline_run",
        foreign_keys="CaseComparison.baseline_run_id",
    )
    candidate_case_comparisons: Mapped[list[CaseComparison]] = relationship(
        back_populates="candidate_run",
        foreign_keys="CaseComparison.candidate_run_id",
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "conversation_id",
            name="uq_evaluation_results_run_conversation",
        ),
        CheckConstraint(
            "judgment IN ('success', 'warning', 'failure', 'uncertain')",
            name="ck_evaluation_results_judgment",
        ),
        CheckConstraint(
            "primary_failure_mode IS NULL OR primary_failure_mode IN "
            "('incorrect_information', 'incomplete_unresolved', "
            "'intent_relevance_failure', 'improper_refusal', "
            "'policy_procedure_violation', 'other')",
            name="ck_evaluation_results_primary_failure_mode",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_evaluation_results_severity",
        ),
        CheckConstraint(
            "(judgment = 'failure' AND severity IS NOT NULL) OR "
            "(judgment <> 'failure' AND severity IS NULL)",
            name="ck_evaluation_results_judgment_severity",
        ),
        CheckConstraint(
            "length(trim(rationale)) > 0",
            name="ck_evaluation_results_rationale_not_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    judgment: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_failure_mode: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    secondary_flags: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    raw_judge_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    evaluation_run: Mapped[EvaluationRun] = relationship(
        back_populates="evaluation_results"
    )
    conversation: Mapped[Conversation] = relationship(
        back_populates="evaluation_results"
    )
    human_decision: Mapped[HumanDecision | None] = relationship(
        back_populates="evaluation_result",
        uselist=False,
    )
    problem_links: Mapped[list[ResultProblemLink]] = relationship(
        back_populates="evaluation_result"
    )


class HumanDecision(Base):
    __tablename__ = "human_decisions"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_result_id",
            name="uq_human_decisions_evaluation_result_id",
        ),
        CheckConstraint(
            "length(trim(reviewer)) > 0",
            name="ck_human_decisions_reviewer_not_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_result_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_results.id"),
        nullable=False,
    )
    reviewer: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    original_result: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    final_result: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    evaluation_result: Mapped[EvaluationResult] = relationship(
        back_populates="human_decision"
    )


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "mapping_key",
            name="uq_problems_run_mapping_key",
        ),
        CheckConstraint(
            "length(trim(definition)) > 0",
            name="ck_problems_definition_not_empty",
        ),
        CheckConstraint(
            "mapping_version = 'PRIMARY-PROBLEM-EXACT-V1'",
            name="ck_problems_mapping_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id"),
        nullable=False,
        index=True,
    )
    scenario: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_key: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    evaluation_run: Mapped[EvaluationRun] = relationship(
        back_populates="problems"
    )
    result_links: Mapped[list[ResultProblemLink]] = relationship(
        back_populates="problem"
    )
    optimization_targets: Mapped[list[OptimizationTarget]] = relationship(
        back_populates="problem"
    )


class ResultProblemLink(Base):
    __tablename__ = "result_problem_links"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_result_id",
            "role",
            name="uq_result_problem_links_result_role",
        ),
        CheckConstraint(
            "role = 'primary'",
            name="ck_result_problem_links_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    problem_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("problems.id"),
        nullable=False,
        index=True,
    )
    evaluation_result_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_results.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)

    problem: Mapped[Problem] = relationship(back_populates="result_links")
    evaluation_result: Mapped[EvaluationResult] = relationship(
        back_populates="problem_links"
    )


class OptimizationTarget(Base):
    __tablename__ = "optimization_targets"
    __table_args__ = (
        UniqueConstraint(
            "baseline_run_id",
            "problem_set_key",
            "version",
            name="uq_optimization_targets_run_problem_set_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_optimization_targets_version_positive",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'frozen')",
            name="ck_optimization_targets_status",
        ),
        CheckConstraint(
            "change_status = 'planned'",
            name="ck_optimization_targets_change_status",
        ),
        CheckConstraint(
            "length(trim(definition)) > 0",
            name="ck_optimization_targets_definition_not_empty",
        ),
        CheckConstraint(
            "length(trim(inclusion_criteria)) > 0",
            name="ck_optimization_targets_inclusion_not_empty",
        ),
        CheckConstraint(
            "length(trim(exclusion_criteria)) > 0",
            name="ck_optimization_targets_exclusion_not_empty",
        ),
        CheckConstraint(
            "length(trim(expected_observable_change)) > 0",
            name="ck_optimization_targets_expected_change_not_empty",
        ),
        CheckConstraint(
            "failure_mode IN "
            "('incorrect_information', 'incomplete_unresolved', "
            "'intent_relevance_failure', 'improper_refusal', "
            "'policy_procedure_violation', 'other')",
            name="ck_optimization_targets_failure_mode",
        ),
        CheckConstraint(
            "confirmed_by IS NULL OR length(trim(confirmed_by)) > 0",
            name="ck_optimization_targets_confirmer_not_empty",
        ),
        CheckConstraint(
            "(confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_optimization_targets_target_confirmation_pair",
        ),
        CheckConstraint(
            "(hypothesis_confirmed_by IS NULL AND hypothesis_confirmed_at IS NULL) "
            "OR (hypothesis_confirmed_by IS NOT NULL "
            "AND hypothesis_confirmed_at IS NOT NULL)",
            name="ck_optimization_targets_hypothesis_confirmation_pair",
        ),
        CheckConstraint(
            "hypothesis_confirmed_by IS NULL OR confirmed_by IS NOT NULL",
            name="ck_optimization_targets_hypothesis_requires_target",
        ),
        CheckConstraint(
            "(status = 'draft' AND (confirmed_by IS NULL "
            "OR hypothesis_confirmed_by IS NULL)) OR "
            "(status IN ('confirmed', 'frozen') AND confirmed_by IS NOT NULL)",
            name="ck_optimization_targets_confirmation_state",
        ),
        CheckConstraint(
            "hypothesis_confirmed_by IS NULL "
            "OR length(trim(hypothesis_confirmed_by)) > 0",
            name="ck_optimization_targets_hypothesis_confirmer_not_empty",
        ),
        CheckConstraint(
            "frozen_by IS NULL OR length(trim(frozen_by)) > 0",
            name="ck_optimization_targets_freezer_not_empty",
        ),
        CheckConstraint(
            "plan_hash IS NULL OR length(plan_hash) = 64",
            name="ck_optimization_targets_plan_hash_length",
        ),
        CheckConstraint(
            "(status <> 'frozen' AND plan_hash IS NULL AND frozen_by IS NULL "
            "AND frozen_at IS NULL) OR (status = 'frozen' "
            "AND plan_hash IS NOT NULL AND frozen_by IS NOT NULL "
            "AND frozen_at IS NOT NULL)",
            name="ck_optimization_targets_frozen_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    baseline_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id"),
        nullable=False,
        index=True,
    )
    problem_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("problems.id"),
        nullable=False,
        index=True,
    )
    problem_ids: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list, server_default="[]"
    )
    problem_set_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    inclusion_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    exclusion_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_affected_case_ids: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    reference_basis: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    failure_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_metric: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    expected_observable_change: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hypothesis_confirmed_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    hypothesis_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hypothesis_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    hypothesis_evidence_refs: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list, server_default="[]"
    )
    change_surface: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardrails: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list, server_default="[]"
    )
    change_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planned", server_default="planned"
    )
    target_case_ids: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    regression_case_ids: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    challenge_case_ids: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    protected_capabilities: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=list, server_default="[]"
    )
    baseline_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    evaluation_config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    baseline_run: Mapped[EvaluationRun] = relationship(
        back_populates="optimization_targets",
        foreign_keys=[baseline_run_id],
    )
    problem: Mapped[Problem] = relationship(back_populates="optimization_targets")
    case_comparisons: Mapped[list[CaseComparison]] = relationship(
        back_populates="target"
    )


class CaseComparison(Base):
    __tablename__ = "case_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "baseline_run_id",
            "candidate_run_id",
            "conversation_id",
            name="uq_case_comparisons_run_pair_conversation",
        ),
        CheckConstraint(
            "movement IN ('improved', 'partially_improved', 'stable', "
            "'regressed', 'inconclusive')",
            name="ck_case_comparisons_movement",
        ),
        CheckConstraint(
            "target_problem_status IN ('present', 'absent', 'not_applicable', "
            "'inconclusive')",
            name="ck_case_comparisons_target_problem_status",
        ),
        CheckConstraint(
            "regression_level IS NULL OR regression_level IN "
            "('critical', 'major', 'minor')",
            name="ck_case_comparisons_regression_level",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    baseline_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_runs.id"), nullable=False
    )
    candidate_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_runs.id"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("optimization_targets.id"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_evaluation_result_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_results.id"), nullable=False
    )
    candidate_evaluation_result_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_results.id"), nullable=False
    )
    movement: Mapped[str] = mapped_column(String(32), nullable=False)
    target_problem_status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_worse: Mapped[bool] = mapped_column(Boolean, nullable=False)
    regression_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    rule_result_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    baseline_run: Mapped[EvaluationRun] = relationship(
        back_populates="baseline_case_comparisons",
        foreign_keys=[baseline_run_id],
    )
    candidate_run: Mapped[EvaluationRun] = relationship(
        back_populates="candidate_case_comparisons",
        foreign_keys=[candidate_run_id],
    )
    target: Mapped[OptimizationTarget] = relationship(
        back_populates="case_comparisons"
    )
