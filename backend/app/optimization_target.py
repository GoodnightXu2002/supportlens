from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.human_review import HumanReviewService
from app.judge_contract import EvidenceType
from app.models import Conversation, EvaluationRun, OptimizationTarget, Problem
from app.problem_aggregation import ProblemAggregationService
from app.schemas import (
    EvaluationRunStatus,
    EvaluationRunType,
    FinalEffectiveResultStatus,
    OptimizationTargetChangeStatus,
    OptimizationTargetCreateRequest,
    OptimizationTargetRead,
    OptimizationTargetStatus,
    ProblemRead,
)


class OptimizationTargetErrorCode(StrEnum):
    EVALUATION_RUN_NOT_FOUND = "evaluation_run_not_found"
    OPTIMIZATION_TARGET_NOT_FOUND = "optimization_target_not_found"
    OPTIMIZATION_TARGET_RUN_NOT_BASELINE = "optimization_target_run_not_baseline"
    OPTIMIZATION_TARGET_RUN_NOT_COMPLETED = "optimization_target_run_not_completed"
    OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND = "optimization_target_problem_not_found"
    OPTIMIZATION_TARGET_PROBLEM_RUN_MISMATCH = (
        "optimization_target_problem_run_mismatch"
    )
    OPTIMIZATION_TARGET_PENDING_REVIEW = "optimization_target_pending_review"
    OPTIMIZATION_TARGET_AGGREGATION_NOT_COMPLETED = (
        "optimization_target_aggregation_not_completed"
    )
    OPTIMIZATION_TARGET_PROBLEM_HAS_NO_AFFECTED_CASES = (
        "optimization_target_problem_has_no_affected_cases"
    )
    OPTIMIZATION_TARGET_FAILURE_MODE_NOT_UNIQUE = (
        "optimization_target_failure_mode_not_unique"
    )
    OPTIMIZATION_TARGET_ALREADY_EXISTS = "optimization_target_already_exists"
    OPTIMIZATION_TARGET_PERSISTENCE_FAILED = (
        "optimization_target_persistence_failed"
    )


class OptimizationTargetError(RuntimeError):
    def __init__(self, code: OptimizationTargetErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class OptimizationTargetService:
    def __init__(
        self,
        *,
        problem_service: ProblemAggregationService | None = None,
        final_result_service: HumanReviewService | None = None,
    ) -> None:
        self._problem_service = problem_service or ProblemAggregationService()
        self._final_result_service = final_result_service or HumanReviewService()

    def create(
        self,
        evaluation_run_id: UUID,
        problem_id: UUID,
        request: OptimizationTargetCreateRequest,
        db_session: Session,
    ) -> OptimizationTargetRead:
        evaluation_run = self._load_run(evaluation_run_id, db_session)
        self._validate_run(evaluation_run)

        problem = db_session.get(Problem, problem_id)
        if problem is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND,
                f"Problem '{problem_id}' was not found.",
            )
        if problem.evaluation_run_id != evaluation_run.id:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_RUN_MISMATCH,
                "Problem does not belong to the requested baseline run.",
            )
        if self._target_exists(evaluation_run.id, problem.id, db_session):
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_ALREADY_EXISTS,
                "An optimization target already exists for this run and problem.",
            )

        effective_results = self._final_result_service.list_final_effective_results(
            evaluation_run.id,
            db_session,
        )
        if any(
            result.status is FinalEffectiveResultStatus.PENDING_REVIEW
            for result in effective_results
        ):
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PENDING_REVIEW,
                "All evaluation results must be final before creating a target.",
            )

        problem_read = self._load_problem_read(
            evaluation_run.id,
            problem.id,
            db_session,
        )
        if not problem_read.affected_case_ids:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_HAS_NO_AFFECTED_CASES,
                "Optimization target requires at least one affected case.",
            )

        reference_basis = [
            evidence.model_dump(mode="json")
            for evidence in problem_read.evidence
            if evidence.evidence_type is EvidenceType.REFERENCE
        ]
        effective_result_by_id = {
            result.evaluation_result_id: result for result in effective_results
        }
        affected_effective_results = [
            effective_result_by_id.get(result_id)
            for result_id in problem_read.affected_evaluation_result_ids
        ]
        if any(
            effective is None
            or effective.final_result is None
            or effective.final_result.primary_failure_mode is None
            for effective in affected_effective_results
        ):
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FAILURE_MODE_NOT_UNIQUE,
                (
                    "Affected final results do not provide one unique primary "
                    "failure mode."
                ),
            )
        failure_modes = {
            effective.final_result.primary_failure_mode.value
            for effective in affected_effective_results
            if effective is not None
            and effective.final_result is not None
            and effective.final_result.primary_failure_mode is not None
        }
        if len(failure_modes) != 1:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FAILURE_MODE_NOT_UNIQUE,
                (
                    "Affected final results do not provide one unique primary "
                    "failure mode."
                ),
            )
        failure_mode = next(iter(failure_modes))

        all_cases = list(
            db_session.scalars(
                select(Conversation)
                .where(Conversation.dataset_id == evaluation_run.dataset_id)
                .order_by(
                    Conversation.external_id.asc(),
                    Conversation.created_at.asc(),
                    Conversation.id.asc(),
                )
            ).all()
        )
        affected_case_ids = list(problem_read.affected_case_ids)
        affected_case_id_set = set(affected_case_ids)
        core_case_ids = [
            case.external_id
            for case in all_cases
            if _case_set(case.metadata_) == "core"
        ]
        target_case_ids = [
            case_id for case_id in core_case_ids if case_id in affected_case_id_set
        ]
        regression_case_ids = [
            case_id for case_id in core_case_ids if case_id not in affected_case_id_set
        ]
        challenge_case_ids = [
            case.external_id
            for case in all_cases
            if _case_set(case.metadata_) == "challenge"
        ]

        frequency = problem_read.frequency.model_dump(mode="json")
        target = OptimizationTarget(
            baseline_run_id=evaluation_run.id,
            problem_id=problem.id,
            version=1,
            status=OptimizationTargetStatus.DRAFT.value,
            definition=request.definition,
            inclusion_criteria=request.inclusion_criteria,
            exclusion_criteria=request.exclusion_criteria,
            baseline_affected_case_ids=affected_case_ids,
            reference_basis=reference_basis,
            failure_mode=failure_mode,
            baseline_metric={
                "affected_core_cases": problem_read.frequency.numerator,
                "core_denominator": problem_read.frequency.denominator,
                "frequency": frequency,
            },
            expected_observable_change=request.expected_observable_change,
            confirmed_by=None,
            confirmed_at=None,
            hypothesis_statement=request.hypothesis_statement,
            hypothesis_evidence_refs=list(request.hypothesis_evidence_refs),
            change_surface=request.change_surface,
            planned_change=request.planned_change,
            guardrails=list(request.guardrails),
            change_status=OptimizationTargetChangeStatus.PLANNED.value,
            target_case_ids=target_case_ids,
            regression_case_ids=regression_case_ids,
            challenge_case_ids=challenge_case_ids,
            protected_capabilities=list(request.protected_capabilities),
            baseline_snapshot={
                "problem_id": str(problem_read.problem_id),
                "definition": problem_read.definition,
                "scenario": problem_read.scenario,
                "priority_severity": problem_read.priority_severity,
                "business_impact": problem_read.business_impact,
                "frequency": frequency,
                "pattern_consistency": problem_read.pattern_consistency,
                "evidence_confidence": problem_read.evidence_confidence,
                "affected_case_ids": affected_case_ids,
            },
            evaluation_config_snapshot={
                "baseline_run_id": str(evaluation_run.id),
                "dataset_id": str(evaluation_run.dataset_id),
                "judge_model": evaluation_run.judge_model,
                "judge_contract_version": evaluation_run.judge_contract_version,
                "run_source": evaluation_run.run_source,
                "response_set_key": evaluation_run.response_set_key,
                "business_reference_snapshot": (
                    evaluation_run.business_reference_snapshot
                ),
            },
            policy_version=request.policy_version,
        )
        db_session.add(target)
        try:
            db_session.commit()
        except IntegrityError as error:
            db_session.rollback()
            if self._target_exists(evaluation_run.id, problem.id, db_session):
                raise OptimizationTargetError(
                    OptimizationTargetErrorCode.OPTIMIZATION_TARGET_ALREADY_EXISTS,
                    "An optimization target already exists for this run and problem.",
                ) from error
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PERSISTENCE_FAILED,
                "Optimization target could not be persisted.",
            ) from error
        db_session.refresh(target)
        return OptimizationTargetRead.model_validate(target)

    def get(self, target_id: UUID, db_session: Session) -> OptimizationTargetRead:
        target = db_session.get(OptimizationTarget, target_id)
        if target is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_NOT_FOUND,
                f"Optimization target '{target_id}' was not found.",
            )
        return OptimizationTargetRead.model_validate(target)

    def list_for_run(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> list[OptimizationTargetRead]:
        self._load_run(evaluation_run_id, db_session)
        targets = db_session.scalars(
            select(OptimizationTarget)
            .where(OptimizationTarget.baseline_run_id == evaluation_run_id)
            .order_by(
                OptimizationTarget.created_at.asc(),
                OptimizationTarget.id.asc(),
            )
        ).all()
        return [OptimizationTargetRead.model_validate(target) for target in targets]

    @staticmethod
    def _load_run(evaluation_run_id: UUID, db_session: Session) -> EvaluationRun:
        evaluation_run = db_session.get(EvaluationRun, evaluation_run_id)
        if evaluation_run is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )
        return evaluation_run

    @staticmethod
    def _validate_run(evaluation_run: EvaluationRun) -> None:
        if evaluation_run.run_type != EvaluationRunType.BASELINE.value:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_RUN_NOT_BASELINE,
                "Optimization targets require a baseline evaluation run.",
            )
        if evaluation_run.status != EvaluationRunStatus.COMPLETED.value:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_RUN_NOT_COMPLETED,
                "Optimization targets require a completed evaluation run.",
            )
        if evaluation_run.problem_aggregation_completed_at is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_AGGREGATION_NOT_COMPLETED,
                "Problem aggregation must be completed before creating a target.",
            )

    def _load_problem_read(
        self,
        evaluation_run_id: UUID,
        problem_id: UUID,
        db_session: Session,
    ) -> ProblemRead:
        for problem in self._problem_service.list_problems(
            evaluation_run_id,
            db_session,
        ):
            if problem.problem_id == problem_id:
                return problem
        raise OptimizationTargetError(
            OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_HAS_NO_AFFECTED_CASES,
            "Problem does not have traceable affected cases.",
        )

    @staticmethod
    def _target_exists(
        evaluation_run_id: UUID,
        problem_id: UUID,
        db_session: Session,
    ) -> bool:
        return (
            db_session.scalar(
                select(OptimizationTarget.id).where(
                    OptimizationTarget.baseline_run_id == evaluation_run_id,
                    OptimizationTarget.problem_id == problem_id,
                )
            )
            is not None
        )


def _case_set(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    nested_metadata = metadata.get("metadata")
    if not isinstance(nested_metadata, dict):
        return None
    case_set = nested_metadata.get("case_set")
    return case_set if isinstance(case_set, str) else None
