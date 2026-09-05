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
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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
