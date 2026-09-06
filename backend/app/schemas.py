from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.business_impact_mapping import BusinessImpact, BusinessImpactLookupStatus
from app.judge_contract import EvidenceType, FailureMode, JudgeOutput, Severity


class DatasetSource(StrEnum):
    USER_UPLOAD = "user_upload"
    FIXTURE_IMPORT = "fixture_import"


class PrivacyStatus(StrEnum):
    SYNTHETIC = "synthetic"
    DEIDENTIFIED = "deidentified"
    MAY_CONTAIN_PERSONAL_DATA = "may_contain_personal_data"
    UNKNOWN = "unknown"


class EvaluationRunType(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class EvaluationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    INVALID = "invalid"


class EvaluationRunSource(StrEnum):
    SEED = "seed"
    LIVE = "live"


class CandidateFinalDecision(StrEnum):
    ACCEPT = "accept"
    CONTINUE = "continue"


class HumanReviewAction(StrEnum):
    CONFIRM = "confirm"
    CORRECT = "correct"


class FinalEffectiveResultStatus(StrEnum):
    FINAL = "final"
    PENDING_REVIEW = "pending_review"


class FinalEffectiveResultSource(StrEnum):
    MACHINE = "machine"
    HUMAN = "human"


class ProblemReviewStatus(StrEnum):
    CLEARED = "cleared"
    PENDING = "pending"


class EvidenceSufficiency(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class EvidenceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


class PatternConsistency(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class ReferenceConflictStatus(StrEnum):
    CLEAR = "clear"
    PRESENT = "present"
    UNSUPPORTED = "unsupported"


class DatasetBase(BaseModel):
    name: str
    description: str | None = None
    version: str = "v1.0"
    source: DatasetSource
    privacy_status: PrivacyStatus = PrivacyStatus.UNKNOWN
    representativeness_statement: str | None = None

    @model_validator(mode="after")
    def validate_fixture_import_contract(self) -> Self:
        if self.source is not DatasetSource.FIXTURE_IMPORT:
            return self
        if self.privacy_status is not PrivacyStatus.SYNTHETIC:
            raise ValueError("fixture_import requires privacy_status=synthetic")
        if not self.representativeness_statement or not (
            self.representativeness_statement.strip()
        ):
            raise ValueError(
                "fixture_import requires a non-empty "
                "representativeness_statement"
            )
        return self


class DatasetCreate(DatasetBase):
    pass


class DatasetRead(DatasetBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ConversationBase(BaseModel):
    external_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] | None = None


class ConversationCreate(ConversationBase):
    pass


class ConversationRead(ConversationBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    dataset_id: UUID
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class DatasetImportConfirmRequest(BaseModel):
    import_token: str


class DatasetImportConfirmResponse(BaseModel):
    dataset_id: UUID
    name: str
    version: str
    source: DatasetSource
    privacy_status: PrivacyStatus
    representativeness_statement: str | None
    conversation_count: int
    created_at: datetime


class DatasetListItem(BaseModel):
    dataset_id: UUID
    name: str
    description: str | None
    version: str
    source: DatasetSource
    privacy_status: PrivacyStatus
    representativeness_statement: str | None
    conversation_count: int
    created_at: datetime


class DatasetDetailResponse(DatasetListItem):
    scenario_distribution: dict[str, int]


class DatasetConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    external_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="metadata_",
    )
    created_at: datetime


class EvaluationRunCreateRequest(BaseModel):
    dataset_id: UUID
    run_type: Literal[EvaluationRunType.BASELINE]


class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    run_type: EvaluationRunType
    status: EvaluationRunStatus
    baseline_run_id: UUID | None
    target_id: UUID | None
    candidate_label: str | None
    candidate_change_summary: str | None
    judge_model: str
    judge_contract_version: str
    run_source: EvaluationRunSource
    response_set_key: str
    error_code: str | None
    error_message: str | None
    problem_aggregation_completed_at: datetime | None
    candidate_responses_snapshot: list[dict[str, Any]] | None
    response_set_hash: str | None
    candidate_manifest_snapshot: dict[str, Any] | None
    candidate_validation_summary: dict[str, Any] | None
    final_decision: CandidateFinalDecision | None
    decided_by: str | None
    decided_at: datetime | None
    reason: str | None
    override_reason: str | None
    created_at: datetime


class HumanReviewSubmitRequest(BaseModel):
    reviewer: str
    action: HumanReviewAction
    final_result: JudgeOutput | None = None
    change_reason: str | None = None

    @field_validator("reviewer")
    @classmethod
    def reviewer_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer must not be empty")
        return value

    @model_validator(mode="after")
    def correct_requires_final_result(self) -> Self:
        if (
            self.action is HumanReviewAction.CORRECT
            and self.final_result is None
        ):
            raise ValueError("correct action requires final_result")
        return self


class HumanDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evaluation_result_id: UUID
    reviewer: str
    reviewed_at: datetime
    original_result: JudgeOutput
    final_result: JudgeOutput
    change_reason: str | None


class FinalEffectiveResultRead(BaseModel):
    evaluation_result_id: UUID
    conversation_id: UUID
    case_id: str
    status: FinalEffectiveResultStatus
    source: FinalEffectiveResultSource | None
    machine_result: JudgeOutput
    final_result: JudgeOutput | None
    human_decision_id: UUID | None
    human_decision: HumanDecisionRead | None


class ProblemEvidenceRead(BaseModel):
    problem_id: UUID
    evaluation_result_id: UUID
    conversation_id: UUID
    case_id: str
    evidence_type: EvidenceType
    content: str
    source_ref: str | None


class ProblemFrequencyRead(BaseModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)


class SeverityDistributionRead(BaseModel):
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)
    critical: int = Field(ge=0)


class ProblemProfileRead(BaseModel):
    profile_version: Literal["BASELINE-PROBLEM-PROFILE-V1"]
    frequency: ProblemFrequencyRead
    severity_distribution: SeverityDistributionRead
    priority_severity: Severity | None
    business_impact: BusinessImpact | None
    business_impact_status: BusinessImpactLookupStatus
    business_impact_mapping_version: str
    review_status: ProblemReviewStatus
    evidence_sufficiency: EvidenceSufficiency
    evidence_confidence: EvidenceConfidence | None
    reference_conflict_status: ReferenceConflictStatus
    pattern_consistency: PatternConsistency | None
    individual_risk_issue: bool
    ranking_eligible: bool
    ranking_blockers: list[str]
    rank: int | None
    equal_review_priority: bool | None


class ProblemRead(ProblemProfileRead):
    problem_id: UUID
    evaluation_run_id: UUID
    scenario: str
    definition: str
    mapping_key: str
    mapping_version: str
    created_at: datetime
    affected_case_count: int
    affected_evaluation_result_ids: list[UUID]
    affected_case_ids: list[str]
    evidence: list[ProblemEvidenceRead]


class OptimizationTargetStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    FROZEN = "frozen"


class OptimizationTargetChangeStatus(StrEnum):
    PLANNED = "planned"


class OptimizationTargetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: str
    inclusion_criteria: str
    exclusion_criteria: str
    expected_observable_change: str
    hypothesis_statement: str | None = None
    hypothesis_evidence_refs: list[str] = Field(default_factory=list)
    change_surface: str | None = None
    planned_change: str | None = None
    guardrails: list[str] = Field(default_factory=list)
    protected_capabilities: list[str] = Field(default_factory=list)
    policy_version: str | None = None

    @field_validator(
        "definition",
        "inclusion_criteria",
        "exclusion_criteria",
        "expected_observable_change",
    )
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator(
        "hypothesis_statement",
        "change_surface",
        "planned_change",
        "policy_version",
    )
    @classmethod
    def optional_text_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be empty when provided")
        return value

    @field_validator(
        "hypothesis_evidence_refs",
        "guardrails",
        "protected_capabilities",
    )
    @classmethod
    def list_entries_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("list entries must not be empty")
        return value


class OptimizationTargetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: str | None = None
    inclusion_criteria: str | None = None
    exclusion_criteria: str | None = None
    expected_observable_change: str | None = None
    hypothesis_statement: str | None = None
    hypothesis_evidence_refs: list[str] | None = None
    change_surface: str | None = None
    planned_change: str | None = None
    guardrails: list[str] | None = None
    protected_capabilities: list[str] | None = None
    policy_version: str | None = None

    @field_validator(
        "definition",
        "inclusion_criteria",
        "exclusion_criteria",
        "expected_observable_change",
    )
    @classmethod
    def target_text_must_not_be_empty(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator(
        "hypothesis_statement",
        "change_surface",
        "planned_change",
        "policy_version",
    )
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be empty when provided")
        return value

    @field_validator(
        "hypothesis_evidence_refs",
        "guardrails",
        "protected_capabilities",
    )
    @classmethod
    def patch_list_entries_must_not_be_empty(
        cls,
        value: list[str] | None,
    ) -> list[str]:
        if value is None:
            raise ValueError("value must be an array")
        if any(not item.strip() for item in value):
            raise ValueError("list entries must not be empty")
        return value


class OptimizationTargetActorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str

    @field_validator("actor")
    @classmethod
    def actor_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor must not be empty")
        return value


class OptimizationTargetBaselineMetricRead(BaseModel):
    affected_core_cases: int = Field(ge=0)
    core_denominator: int = Field(ge=0)
    frequency: ProblemFrequencyRead


class OptimizationTargetBaselineSnapshotRead(BaseModel):
    problem_id: UUID
    definition: str
    scenario: str
    priority_severity: Severity | None
    business_impact: BusinessImpact | None
    frequency: ProblemFrequencyRead
    pattern_consistency: PatternConsistency | None
    evidence_confidence: EvidenceConfidence | None
    affected_case_ids: list[str]


class OptimizationTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    baseline_run_id: UUID
    problem_id: UUID
    version: int
    status: OptimizationTargetStatus
    definition: str
    inclusion_criteria: str
    exclusion_criteria: str
    baseline_affected_case_ids: list[str]
    reference_basis: list[ProblemEvidenceRead]
    failure_mode: FailureMode
    baseline_metric: OptimizationTargetBaselineMetricRead
    expected_observable_change: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    hypothesis_confirmed_by: str | None
    hypothesis_confirmed_at: datetime | None
    hypothesis_statement: str | None
    hypothesis_evidence_refs: list[str]
    change_surface: str | None
    planned_change: str | None
    guardrails: list[str]
    change_status: OptimizationTargetChangeStatus
    target_case_ids: list[str]
    regression_case_ids: list[str]
    challenge_case_ids: list[str]
    protected_capabilities: list[str]
    baseline_snapshot: OptimizationTargetBaselineSnapshotRead
    evaluation_config_snapshot: dict[str, Any]
    policy_version: str | None
    plan_hash: str | None
    frozen_by: str | None
    frozen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    case_id: str
    assistant_content: str

    @field_validator("case_id", "assistant_content")
    @classmethod
    def candidate_response_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class CandidateRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_run_id: UUID
    target_id: UUID
    plan_hash: str
    candidate_label: str
    candidate_change_summary: str
    source: str
    actual_change_summary: str
    actual_change_status: Literal["verified"]
    generation_parity_status: Literal["verified"]
    candidate_first_exposure_at: datetime
    responses: list[CandidateResponseInput] = Field(min_length=1)

    @field_validator(
        "plan_hash",
        "candidate_label",
        "candidate_change_summary",
        "source",
        "actual_change_summary",
    )
    @classmethod
    def candidate_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class CandidateFinalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_decision: CandidateFinalDecision
    decided_by: str
    reason: str
    override_reason: str | None = None

    @field_validator("decided_by", "reason")
    @classmethod
    def required_decision_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("override_reason")
    @classmethod
    def override_reason_must_not_be_empty(
        cls, value: str | None
    ) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("override_reason must not be empty when provided")
        return value


class CaseMovement(StrEnum):
    IMPROVED = "improved"
    PARTIALLY_IMPROVED = "partially_improved"
    STABLE = "stable"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"


class TargetProblemStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"
    INCONCLUSIVE = "inconclusive"


class RegressionLevel(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class RecommendedVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    CONTINUE = "CONTINUE"
    INCONCLUSIVE = "INCONCLUSIVE"


class CaseComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    baseline_run_id: UUID
    candidate_run_id: UUID
    target_id: UUID
    conversation_id: UUID
    case_id: str
    baseline_evaluation_result_id: UUID
    candidate_evaluation_result_id: UUID
    movement: CaseMovement
    target_problem_status: TargetProblemStatus
    target_worse: bool
    regression_level: RegressionLevel | None
    evidence_snapshot: dict[str, Any]
    rule_result_snapshot: dict[str, Any]
    created_at: datetime


class CandidateValidationSummaryRead(BaseModel):
    candidate_run_id: UUID
    baseline_run_id: UUID
    target_id: UUID
    target_outcome: Literal["resolved", "improved", "not_improved", "inconclusive"]
    regression_summary: dict[str, Any]
    other_problems: list[dict[str, Any]]
    new_systematic_problems: list[dict[str, Any]]
    review_complete: bool
    integrity_gate: Literal["passed", "failed"]
    compatibility_gate: Literal["passed", "failed"]
    protected_capability_gate: Literal["not_applicable", "unsupported"]
    recommended_verdict: RecommendedVerdict
    policy_version: str
    rule_outcomes: dict[str, Any]
    blockers: list[str]
