from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.human_review import HumanReviewService
from app.judge_contract import EvidenceType
from app.models import Conversation, EvaluationRun, OptimizationTarget, Problem
from app.problem_aggregation import ProblemAggregationService
from app.schemas import (
    EvaluationRunStatus,
    EvaluationRunType,
    FinalEffectiveResultStatus,
    OptimizationTargetActorRequest,
    OptimizationTargetChangeStatus,
    OptimizationTargetCompleteRequest,
    OptimizationTargetCreateRequest,
    OptimizationTargetPatchRequest,
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
    OPTIMIZATION_TARGET_FROZEN = "optimization_target_frozen"
    OPTIMIZATION_TARGET_TARGET_CONFIRMATION_INCOMPLETE = (
        "optimization_target_target_confirmation_incomplete"
    )
    OPTIMIZATION_TARGET_TARGET_NOT_CONFIRMED = (
        "optimization_target_target_not_confirmed"
    )
    OPTIMIZATION_TARGET_HYPOTHESIS_CONFIRMATION_INCOMPLETE = (
        "optimization_target_hypothesis_confirmation_incomplete"
    )
    OPTIMIZATION_TARGET_FREEZE_GATE_FAILED = (
        "optimization_target_freeze_gate_failed"
    )
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
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        return self.create_for_problems(
            evaluation_run_id,
            [problem_id],
            request,
            db_session,
            commit=commit,
        )

    def create_for_problems(
        self,
        evaluation_run_id: UUID,
        problem_ids: list[UUID],
        request: OptimizationTargetCreateRequest,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        evaluation_run = self._load_run(evaluation_run_id, db_session)
        self._validate_run(evaluation_run)
        unique_problem_ids = list(dict.fromkeys(problem_ids))
        if not unique_problem_ids:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND,
                "Optimization target requires at least one problem.",
            )
        problems: list[Problem] = []
        for problem_id in unique_problem_ids:
            problem = db_session.get(Problem, problem_id)
            if problem is None:
                raise OptimizationTargetError(
                    OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND,
                    f"Problem '{problem_id}' was not found.",
                )
            if problem.evaluation_run_id != evaluation_run.id:
                raise OptimizationTargetError(
                    (
                        OptimizationTargetErrorCode
                        .OPTIMIZATION_TARGET_PROBLEM_RUN_MISMATCH
                    ),
                    "Problem does not belong to the requested baseline run.",
                )
            problems.append(problem)
        problem_set_key = _problem_set_key(unique_problem_ids)
        if self._target_exists(evaluation_run.id, problem_set_key, db_session):
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_ALREADY_EXISTS,
                "An optimization target already exists for this run and problem set.",
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

        problem_reads = [
            self._load_problem_read(evaluation_run.id, problem.id, db_session)
            for problem in problems
        ]
        reference_basis = [
            evidence.model_dump(mode="json")
            for problem_read in problem_reads
            for evidence in problem_read.evidence
            if evidence.evidence_type is EvidenceType.REFERENCE
        ]
        effective_result_by_id = {
            result.evaluation_result_id: result for result in effective_results
        }
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
        case_set_by_id = {
            case.external_id: _case_set(case.metadata_) for case in all_cases
        }
        legacy_failure_modes: list[str] = []
        for problem_read in problem_reads:
            core_results = [
                effective_result_by_id.get(result_id)
                for result_id in problem_read.affected_evaluation_result_ids
                if case_set_by_id.get(
                    effective_result_by_id[result_id].case_id
                    if result_id in effective_result_by_id
                    else ""
                )
                == "core"
            ]
            eligible_results = [
                result
                for result in core_results
                if result is not None
                and result.final_result is not None
                and result.final_result.judgment.value in {"warning", "failure"}
            ]
            if not eligible_results:
                raise OptimizationTargetError(
                    (
                        OptimizationTargetErrorCode
                        .OPTIMIZATION_TARGET_PROBLEM_HAS_NO_AFFECTED_CASES
                    ),
                    "Optimization target requires an affected Core case.",
                )
            failure_results = [
                result
                for result in eligible_results
                if result is not None
                and result.final_result is not None
                and result.final_result.judgment.value == "failure"
            ]
            failure_modes = {
                result.final_result.primary_failure_mode.value
                for result in failure_results
                if result.final_result is not None
                and result.final_result.primary_failure_mode is not None
            }
            if any(
                result.final_result is None
                or result.final_result.primary_failure_mode is None
                for result in failure_results
            ) or len(failure_modes) > 1:
                raise OptimizationTargetError(
                    (
                        OptimizationTargetErrorCode
                        .OPTIMIZATION_TARGET_FAILURE_MODE_NOT_UNIQUE
                    ),
                    (
                        "Affected Core failures do not provide one unique primary "
                        "failure mode."
                    ),
                )
            legacy_failure_modes.append(next(iter(failure_modes), "other"))

        affected_case_id_set = {
            case_id
            for problem_read in problem_reads
            for case_id in problem_read.affected_case_ids
        }
        affected_case_ids = [
            case.external_id
            for case in all_cases
            if case.external_id in affected_case_id_set
        ]
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

        primary_problem_read = problem_reads[0]
        primary_frequency = primary_problem_read.frequency.model_dump(mode="json")
        target = OptimizationTarget(
            baseline_run_id=evaluation_run.id,
            problem_id=problems[0].id,
            problem_ids=[str(problem_id) for problem_id in unique_problem_ids],
            problem_set_key=problem_set_key,
            version=1,
            status=OptimizationTargetStatus.DRAFT.value,
            definition=request.definition,
            inclusion_criteria=request.inclusion_criteria,
            exclusion_criteria=request.exclusion_criteria,
            baseline_affected_case_ids=affected_case_ids,
            reference_basis=reference_basis,
            failure_mode=legacy_failure_modes[0],
            baseline_metric={
                "affected_core_cases": len(target_case_ids),
                "core_denominator": len(core_case_ids),
                "frequency": {
                    "numerator": len(target_case_ids),
                    "denominator": len(core_case_ids),
                },
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
                "problem_id": str(primary_problem_read.problem_id),
                "definition": primary_problem_read.definition,
                "scenario": primary_problem_read.scenario,
                "priority_severity": primary_problem_read.priority_severity,
                "business_impact": primary_problem_read.business_impact,
                "frequency": primary_frequency,
                "pattern_consistency": primary_problem_read.pattern_consistency,
                "evidence_confidence": primary_problem_read.evidence_confidence,
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
            if commit:
                db_session.commit()
            else:
                db_session.flush()
        except IntegrityError as error:
            db_session.rollback()
            if self._target_exists(evaluation_run.id, problem_set_key, db_session):
                raise OptimizationTargetError(
                    OptimizationTargetErrorCode.OPTIMIZATION_TARGET_ALREADY_EXISTS,
                    (
                        "An optimization target already exists for this run and "
                        "problem set."
                    ),
                ) from error
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PERSISTENCE_FAILED,
                "Optimization target could not be persisted.",
            ) from error
        db_session.refresh(target)
        return OptimizationTargetRead.model_validate(target)

    def get(self, target_id: UUID, db_session: Session) -> OptimizationTargetRead:
        target = self._load_target(target_id, db_session)
        return OptimizationTargetRead.model_validate(target)

    def patch(
        self,
        target_id: UUID,
        request: OptimizationTargetPatchRequest,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        target = self._load_target(target_id, db_session)
        self._reject_frozen(target)

        updates = request.model_dump(exclude_unset=True)
        target_fields = {
            "definition",
            "inclusion_criteria",
            "exclusion_criteria",
            "expected_observable_change",
        }
        hypothesis_fields = {
            "hypothesis_statement",
            "hypothesis_evidence_refs",
            "change_surface",
            "planned_change",
            "guardrails",
        }
        changed_fields = {
            field
            for field, value in updates.items()
            if getattr(target, field) != value
        }
        for field, value in updates.items():
            setattr(target, field, list(value) if isinstance(value, list) else value)

        if changed_fields & target_fields:
            target.confirmed_by = None
            target.confirmed_at = None
            target.hypothesis_confirmed_by = None
            target.hypothesis_confirmed_at = None
        elif changed_fields & hypothesis_fields:
            target.hypothesis_confirmed_by = None
            target.hypothesis_confirmed_at = None
        target.status = self._confirmation_status(target)

        return self._commit_and_read(target, db_session, commit=commit)

    def confirm_target(
        self,
        target_id: UUID,
        request: OptimizationTargetActorRequest,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        target = self._load_target(target_id, db_session)
        self._reject_frozen(target)
        if not all(
            _has_text(getattr(target, field))
            for field in (
                "definition",
                "inclusion_criteria",
                "exclusion_criteria",
                "expected_observable_change",
            )
        ):
            raise OptimizationTargetError(
                (
                    OptimizationTargetErrorCode
                    .OPTIMIZATION_TARGET_TARGET_CONFIRMATION_INCOMPLETE
                ),
                "Target confirmation requires all target fields.",
            )

        target.confirmed_by = request.actor.strip()
        target.confirmed_at = datetime.now(UTC)
        target.status = self._confirmation_status(target)
        return self._commit_and_read(target, db_session, commit=commit)

    def confirm_hypothesis(
        self,
        target_id: UUID,
        request: OptimizationTargetActorRequest,
        db_session: Session,
    ) -> OptimizationTargetRead:
        target = self._load_target(target_id, db_session)
        self._reject_frozen(target)
        if target.confirmed_by is None or target.confirmed_at is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_TARGET_NOT_CONFIRMED,
                "Target must be confirmed before confirming the hypothesis.",
            )
        if not all(
            _has_text(getattr(target, field))
            for field in (
                "hypothesis_statement",
                "change_surface",
                "planned_change",
            )
        ):
            raise OptimizationTargetError(
                (
                    OptimizationTargetErrorCode
                    .OPTIMIZATION_TARGET_HYPOTHESIS_CONFIRMATION_INCOMPLETE
                ),
                (
                    "Hypothesis confirmation requires hypothesis and planned "
                    "change fields."
                ),
            )

        target.hypothesis_confirmed_by = request.actor.strip()
        target.hypothesis_confirmed_at = datetime.now(UTC)
        target.status = OptimizationTargetStatus.CONFIRMED.value
        return self._commit_and_read(target, db_session)

    def freeze(
        self,
        target_id: UUID,
        request: OptimizationTargetActorRequest,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        target = self._load_target(target_id, db_session)
        if target.status == OptimizationTargetStatus.FROZEN.value:
            return OptimizationTargetRead.model_validate(target)

        missing_requirements = self._freeze_gate_failures(target)
        if missing_requirements:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FREEZE_GATE_FAILED,
                "Freeze requirements not met: " + ", ".join(missing_requirements),
            )

        target.plan_hash = build_optimization_target_plan_hash(target)
        target.frozen_by = request.actor.strip()
        target.frozen_at = datetime.now(UTC)
        target.status = OptimizationTargetStatus.FROZEN.value
        return self._commit_and_read(target, db_session, commit=commit)

    def complete(
        self,
        evaluation_run_id: UUID,
        problem_id: UUID,
        request: OptimizationTargetCompleteRequest,
        db_session: Session,
    ) -> OptimizationTargetRead:
        return self.complete_for_problems(
            evaluation_run_id,
            [problem_id],
            request.target,
            request.actor,
            db_session,
        )

    def complete_for_problems(
        self,
        evaluation_run_id: UUID,
        problem_ids: list[UUID],
        request: OptimizationTargetCreateRequest,
        actor_name: str,
        db_session: Session,
    ) -> OptimizationTargetRead:
        """Save, confirm and freeze together; retries reuse the same target."""
        unique_problem_ids = list(dict.fromkeys(problem_ids))
        if not unique_problem_ids:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PROBLEM_NOT_FOUND,
                "Optimization target requires at least one problem.",
            )
        problem_set_key = _problem_set_key(unique_problem_ids)
        try:
            existing = db_session.scalar(
                select(OptimizationTarget)
                .where(
                    OptimizationTarget.baseline_run_id == evaluation_run_id,
                    OptimizationTarget.problem_set_key == problem_set_key,
                )
                .with_for_update()
            )
            if existing and existing.status == OptimizationTargetStatus.FROZEN.value:
                return OptimizationTargetRead.model_validate(existing)
            values = request.model_dump(exclude_unset=True)
            values["policy_version"] = (
                existing.policy_version if existing and existing.policy_version
                else "CANDIDATE-DECISION-POLICY-V1"
            )
            if existing:
                target = self.patch(
                    existing.id, OptimizationTargetPatchRequest(**values),
                    db_session, commit=False,
                )
            else:
                target = self.create_for_problems(
                    evaluation_run_id,
                    unique_problem_ids,
                    OptimizationTargetCreateRequest(**values),
                    db_session,
                    commit=False,
                )
            actor = OptimizationTargetActorRequest(actor=actor_name)
            self.confirm_target(target.id, actor, db_session, commit=False)
            frozen = self.freeze(target.id, actor, db_session, commit=False)
            db_session.commit()
            return frozen
        except OptimizationTargetError:
            db_session.rollback()
            raise
        except SQLAlchemyError as error:
            db_session.rollback()
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PERSISTENCE_FAILED,
                "Optimization target could not be persisted.",
            ) from error

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
    def _load_target(
        target_id: UUID,
        db_session: Session,
    ) -> OptimizationTarget:
        target = db_session.get(OptimizationTarget, target_id)
        if target is None:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_NOT_FOUND,
                f"Optimization target '{target_id}' was not found.",
            )
        return target

    @staticmethod
    def _reject_frozen(target: OptimizationTarget) -> None:
        if target.status == OptimizationTargetStatus.FROZEN.value:
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_FROZEN,
                "Frozen optimization targets are immutable.",
            )

    @staticmethod
    def _confirmation_status(target: OptimizationTarget) -> str:
        if (
            target.confirmed_by is not None
            and target.confirmed_at is not None
        ):
            return OptimizationTargetStatus.CONFIRMED.value
        return OptimizationTargetStatus.DRAFT.value

    @staticmethod
    def _freeze_gate_failures(target: OptimizationTarget) -> list[str]:
        failures: list[str] = []
        if target.confirmed_by is None or target.confirmed_at is None:
            failures.append("target_confirmation")
        if not target.target_case_ids:
            failures.append("target_case_ids")
        if not target.baseline_snapshot:
            failures.append("baseline_snapshot")
        if not target.evaluation_config_snapshot:
            failures.append("evaluation_config_snapshot")
        if not _has_text(target.policy_version):
            failures.append("policy_version")
        if target.change_status != OptimizationTargetChangeStatus.PLANNED.value:
            failures.append("change_status")
        return failures

    @staticmethod
    def _commit_and_read(
        target: OptimizationTarget,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> OptimizationTargetRead:
        try:
            if commit:
                db_session.commit()
            else:
                db_session.flush()
        except IntegrityError as error:
            db_session.rollback()
            raise OptimizationTargetError(
                OptimizationTargetErrorCode.OPTIMIZATION_TARGET_PERSISTENCE_FAILED,
                "Optimization target could not be persisted.",
            ) from error
        db_session.refresh(target)
        return OptimizationTargetRead.model_validate(target)

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
        problem_set_key: str,
        db_session: Session,
    ) -> bool:
        return (
            db_session.scalar(
                select(OptimizationTarget.id).where(
                    OptimizationTarget.baseline_run_id == evaluation_run_id,
                    OptimizationTarget.problem_set_key == problem_set_key,
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


def _problem_set_key(problem_ids: list[UUID]) -> str:
    canonical = ",".join(sorted(str(problem_id) for problem_id in problem_ids))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_optimization_target_plan_hash(target: OptimizationTarget) -> str:
    payload = {
        "problem_ids": target.problem_ids or [str(target.problem_id)],
        "target_contract": {
            "definition": target.definition,
            "inclusion_criteria": target.inclusion_criteria,
            "exclusion_criteria": target.exclusion_criteria,
            "baseline_affected_case_ids": target.baseline_affected_case_ids,
            "reference_basis": target.reference_basis,
            "failure_mode": target.failure_mode,
            "baseline_metric": target.baseline_metric,
            "expected_observable_change": target.expected_observable_change,
        },
        "hypothesis": {
            "hypothesis_statement": target.hypothesis_statement,
            "hypothesis_evidence_refs": target.hypothesis_evidence_refs,
        },
        "planned_change": {
            "change_surface": target.change_surface,
            "planned_change": target.planned_change,
        },
        "guardrails": target.guardrails,
        "target_case_ids": target.target_case_ids,
        "regression_case_ids": target.regression_case_ids,
        "challenge_case_ids": target.challenge_case_ids,
        "protected_capabilities": target.protected_capabilities,
        "baseline_snapshot": target.baseline_snapshot,
        "evaluation_config_snapshot": target.evaluation_config_snapshot,
        "policy_version": target.policy_version,
    }
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
