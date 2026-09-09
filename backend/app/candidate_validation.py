from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.human_review import HumanReviewService
from app.judge_contract import JudgeOutput, Judgment, Severity
from app.judge_executor import JudgeExecutionError, execute_judge
from app.llm_provider import LLMProvider
from app.models import (
    CaseComparison,
    Conversation,
    EvaluationResult,
    EvaluationRun,
    HumanDecision,
    OptimizationTarget,
    Problem,
)
from app.problem_aggregation import (
    PROBLEM_MAPPING_VERSION,
    ProblemAggregationService,
    build_problem_mapping_key,
    normalize_problem_definition,
)
from app.schemas import (
    CandidateFinalDecision,
    CandidateFinalDecisionRequest,
    CandidateProblemResultRead,
    CandidateRunCreateRequest,
    CandidateValidationSummaryRead,
    CaseComparisonRead,
    CaseMovement,
    EvaluationRunStatus,
    EvaluationRunType,
    FinalEffectiveResultRead,
    FinalEffectiveResultStatus,
    ProblemValidationStatus,
    RecommendedVerdict,
    RegressionLevel,
    TargetProblemStatus,
)


class CandidateValidationErrorCode(StrEnum):
    EVALUATION_RUN_NOT_FOUND = "evaluation_run_not_found"
    CANDIDATE_RUN_NOT_CANDIDATE = "candidate_run_not_candidate"
    CANDIDATE_RUN_NOT_STARTABLE = "candidate_run_not_startable"
    CANDIDATE_BASELINE_INVALID = "candidate_baseline_invalid"
    CANDIDATE_TARGET_NOT_FROZEN = "candidate_target_not_frozen"
    CANDIDATE_PLAN_HASH_MISMATCH = "candidate_plan_hash_mismatch"
    CANDIDATE_EXPOSURE_BEFORE_FREEZE = "candidate_exposure_before_freeze"
    CANDIDATE_CASE_SCOPE_INVALID = "candidate_case_scope_invalid"
    CANDIDATE_RESPONSE_PAIR_INVALID = "candidate_response_pair_invalid"
    CANDIDATE_COMPARISON_NOT_READY = "candidate_comparison_not_ready"
    CANDIDATE_COMPARISON_PERSISTENCE_FAILED = "candidate_comparison_persistence_failed"
    CANDIDATE_VALIDATION_SUMMARY_NOT_FOUND = "candidate_validation_summary_not_found"
    CANDIDATE_FINAL_DECISION_ALREADY_COMPLETED = (
        "candidate_final_decision_already_completed"
    )
    CANDIDATE_FINAL_DECISION_ACCEPT_BLOCKED = (
        "candidate_final_decision_accept_blocked"
    )
    CANDIDATE_FINAL_DECISION_OVERRIDE_REASON_REQUIRED = (
        "candidate_final_decision_override_reason_required"
    )


class CandidateValidationError(RuntimeError):
    def __init__(self, code: CandidateValidationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class CandidateRunService:
    def create(
        self,
        request: CandidateRunCreateRequest,
        db_session: Session,
        *,
        commit: bool = True,
    ) -> EvaluationRun:
        baseline = db_session.get(EvaluationRun, request.baseline_run_id)
        if (
            baseline is None
            or baseline.run_type != EvaluationRunType.BASELINE.value
            or baseline.status != EvaluationRunStatus.COMPLETED.value
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_BASELINE_INVALID,
                "Candidate creation requires a completed baseline run.",
            )
        target = db_session.get(OptimizationTarget, request.target_id)
        if (
            target is None
            or target.baseline_run_id != baseline.id
            or target.status != "frozen"
            or target.frozen_at is None
            or target.plan_hash is None
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_TARGET_NOT_FROZEN,
                "Candidate creation requires the matching frozen target.",
            )
        if request.plan_hash != target.plan_hash:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_PLAN_HASH_MISMATCH,
                "Candidate plan hash does not match the frozen target.",
            )
        if _as_utc(request.candidate_first_exposure_at) < _as_utc(target.frozen_at):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_EXPOSURE_BEFORE_FREEZE,
                "Candidate exposure cannot predate target freeze.",
            )

        conversations = list(
            db_session.scalars(
                select(Conversation)
                .where(Conversation.dataset_id == baseline.dataset_id)
                .order_by(Conversation.external_id, Conversation.id)
            ).all()
        )
        by_id = {conversation.id: conversation for conversation in conversations}
        expected_case_ids = (
            list(target.target_case_ids)
            + list(target.regression_case_ids)
            + list(target.challenge_case_ids)
        )
        if len(expected_case_ids) != len(set(expected_case_ids)):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_CASE_SCOPE_INVALID,
                "Frozen candidate case scopes must be disjoint.",
            )
        responses = [item.model_dump(mode="json") for item in request.responses]
        response_case_ids = [item["case_id"] for item in responses]
        response_conversation_ids = [
            UUID(item["conversation_id"]) for item in responses
        ]
        if (
            len(response_case_ids) != len(set(response_case_ids))
            or len(response_conversation_ids) != len(set(response_conversation_ids))
            or set(response_case_ids) != set(expected_case_ids)
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_CASE_SCOPE_INVALID,
                "Candidate responses must exactly cover each frozen case once.",
            )
        for item, conversation_id in zip(
            responses, response_conversation_ids, strict=True
        ):
            conversation = by_id.get(conversation_id)
            if conversation is None or conversation.external_id != item["case_id"]:
                raise CandidateValidationError(
                    CandidateValidationErrorCode.CANDIDATE_RESPONSE_PAIR_INVALID,
                    "Candidate case_id and conversation_id must match the "
                    "baseline dataset.",
                )

        ordered_responses = sorted(
            responses,
            key=lambda item: (item["case_id"], item["conversation_id"]),
        )
        response_set_hash = build_response_set_hash(ordered_responses)
        exposure = _as_utc(request.candidate_first_exposure_at)
        manifest = {
            "plan_hash": target.plan_hash,
            "actual_change_status": request.actual_change_status,
            "actual_change_summary": request.actual_change_summary,
            "generation_parity_status": request.generation_parity_status,
            "candidate_first_exposure_at": exposure.isoformat(),
            "source": request.source,
            "response_set_hash": response_set_hash,
            "case_count": len(ordered_responses),
        }
        candidate = EvaluationRun(
            dataset_id=baseline.dataset_id,
            run_type=EvaluationRunType.CANDIDATE.value,
            status=EvaluationRunStatus.PENDING.value,
            baseline_run_id=baseline.id,
            target_id=target.id,
            candidate_label=request.candidate_label,
            candidate_change_summary=request.candidate_change_summary,
            judge_model=baseline.judge_model,
            judge_contract_version=baseline.judge_contract_version,
            run_source=baseline.run_source,
            response_set_key=f"candidate:{response_set_hash}",
            business_reference_snapshot=baseline.business_reference_snapshot,
            candidate_responses_snapshot=ordered_responses,
            response_set_hash=response_set_hash,
            candidate_manifest_snapshot=manifest,
            candidate_validation_summary=None,
        )
        db_session.add(candidate)
        if commit:
            db_session.commit()
        else:
            db_session.flush()
        db_session.refresh(candidate)
        return candidate


class CandidateRunner:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def execute(self, candidate_run_id: UUID, db_session: Session) -> EvaluationRun:
        candidate = db_session.get(EvaluationRun, candidate_run_id)
        if candidate is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{candidate_run_id}' was not found.",
            )
        if candidate.run_type != EvaluationRunType.CANDIDATE.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_RUN_NOT_CANDIDATE,
                "Candidate execution only supports candidate runs.",
            )
        if candidate.status != EvaluationRunStatus.PENDING.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_RUN_NOT_STARTABLE,
                "Only a pending candidate run can be executed.",
            )
        if not candidate.business_reference_snapshot:
            candidate.status = EvaluationRunStatus.INVALID.value
            candidate.error_code = "evaluation_input_invalid"
            candidate.error_message = "Business reference snapshot is missing."
            db_session.commit()
            return candidate

        snapshots = candidate.candidate_responses_snapshot or []
        conversation_ids = [UUID(item["conversation_id"]) for item in snapshots]
        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == candidate.dataset_id,
                    Conversation.id.in_(conversation_ids),
                )
            ).all()
        )
        by_id = {conversation.id: conversation for conversation in conversations}
        if set(by_id) != set(conversation_ids):
            candidate.status = EvaluationRunStatus.INVALID.value
            candidate.error_code = "evaluation_input_invalid"
            candidate.error_message = "Candidate response snapshot is invalid."
            db_session.commit()
            return candidate

        candidate.status = EvaluationRunStatus.RUNNING.value
        candidate.case_errors = []
        db_session.commit()
        errors: list[dict[str, Any]] = []
        for snapshot in snapshots:
            source = by_id[UUID(snapshot["conversation_id"])]
            judge_conversation = _candidate_conversation(
                source, snapshot["assistant_content"]
            )
            try:
                execution = execute_judge(
                    judge_conversation,
                    business_reference=candidate.business_reference_snapshot,
                    provider=self._provider,
                )
            except JudgeExecutionError as error:
                errors.append(
                    {
                        "conversation_id": str(source.id),
                        "case_id": source.external_id,
                        "error_code": error.error_code,
                        "error_message": str(error),
                        "raw_judge_output": error.raw_judge_output,
                    }
                )
                candidate.case_errors = list(errors)
                db_session.commit()
                continue
            db_session.add(
                EvaluationResult(
                    evaluation_run_id=candidate.id,
                    conversation_id=source.id,
                    raw_judge_output=execution.raw_judge_output,
                    **execution.output.model_dump(mode="json"),
                )
            )
            db_session.commit()

        candidate.case_errors = errors
        result_count = db_session.scalar(
            select(func.count())
            .select_from(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == candidate.id)
        )
        if errors and result_count:
            candidate.status = EvaluationRunStatus.PARTIAL_FAILURE.value
        elif not result_count:
            candidate.status = EvaluationRunStatus.FAILED.value
        else:
            candidate.status = EvaluationRunStatus.COMPLETED.value
        db_session.commit()
        db_session.refresh(candidate)
        return candidate


class CandidateComparisonService:
    def __init__(self, final_results: HumanReviewService | None = None) -> None:
        self._final_results = final_results or HumanReviewService()

    def generate(
        self, candidate_run_id: UUID, db_session: Session
    ) -> tuple[list[CaseComparisonRead], CandidateValidationSummaryRead]:
        candidate, baseline, target, target_problem = self._load_lineage(
            candidate_run_id, db_session
        )
        existing = self.list(candidate_run_id, db_session)
        if existing:
            conversations = list(
                db_session.scalars(
                    select(Conversation).where(
                        Conversation.dataset_id == baseline.dataset_id
                    )
                ).all()
            )
            summary = self._build_summary(
                candidate,
                baseline,
                target,
                existing,
                self._effective_by_conversation(candidate.id, db_session),
                {item.id: item for item in conversations},
                db_session,
            )
            candidate.candidate_validation_summary = summary.model_dump(mode="json")
            db_session.commit()
            return existing, summary
        if candidate.status != EvaluationRunStatus.COMPLETED.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                "Case comparison requires a completed candidate run.",
            )

        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == baseline.dataset_id
                )
            ).all()
        )
        by_id = {item.id: item for item in conversations}
        scope_ids = {
            item["case_id"]: UUID(item["conversation_id"])
            for item in (candidate.candidate_responses_snapshot or [])
        }
        baseline_effective = self._effective_by_conversation(baseline.id, db_session)
        candidate_effective = self._effective_by_conversation(candidate.id, db_session)
        baseline_results = self._result_by_conversation(baseline.id, db_session)
        candidate_results = self._result_by_conversation(candidate.id, db_session)

        comparison_inputs: list[dict[str, Any]] = []
        for case_id in sorted(scope_ids):
            conversation_id = scope_ids[case_id]
            conversation = by_id.get(conversation_id)
            if conversation is None or conversation.external_id != case_id:
                raise CandidateValidationError(
                    CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                    "Candidate and baseline cases cannot be paired.",
                )
            baseline_final = baseline_effective.get(conversation_id)
            candidate_final = candidate_effective.get(conversation_id)
            baseline_result = baseline_results.get(conversation_id)
            candidate_result = candidate_results.get(conversation_id)
            if not all(
                (baseline_final, candidate_final, baseline_result, candidate_result)
            ):
                raise CandidateValidationError(
                    CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                    "Candidate and baseline results must cover the frozen scope.",
                )
            comparison_inputs.append(
                self._compare_case(
                    conversation,
                    baseline_final,
                    candidate_final,
                    baseline_result,
                    candidate_result,
                    target,
                    target_problem,
                    db_session,
                )
            )

        self._assign_regression_levels(comparison_inputs, target, db_session)
        for item in comparison_inputs:
            db_session.add(CaseComparison(**item))
        try:
            db_session.flush()
            comparisons = self.list(candidate.id, db_session)
            summary = self._build_summary(
                candidate,
                baseline,
                target,
                comparisons,
                candidate_effective,
                by_id,
                db_session,
            )
            candidate.candidate_validation_summary = summary.model_dump(mode="json")
            db_session.commit()
        except IntegrityError as error:
            db_session.rollback()
            existing = self.list(candidate.id, db_session)
            if existing:
                return existing, self.get_summary(candidate.id, db_session)
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_COMPARISON_PERSISTENCE_FAILED,
                "Case comparisons could not be persisted.",
            ) from error
        return self.list(candidate.id, db_session), self.get_summary(
            candidate.id, db_session
        )

    def list(
        self, candidate_run_id: UUID, db_session: Session
    ) -> list[CaseComparisonRead]:
        candidate = db_session.get(EvaluationRun, candidate_run_id)
        if candidate is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{candidate_run_id}' was not found.",
            )
        if candidate.run_type != EvaluationRunType.CANDIDATE.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_RUN_NOT_CANDIDATE,
                "Candidate validation only supports candidate runs.",
            )
        rows = db_session.scalars(
            select(CaseComparison)
            .where(CaseComparison.candidate_run_id == candidate_run_id)
            .order_by(CaseComparison.case_id, CaseComparison.id)
        ).all()
        return [CaseComparisonRead.model_validate(row) for row in rows]

    def get_summary(
        self, candidate_run_id: UUID, db_session: Session
    ) -> CandidateValidationSummaryRead:
        candidate = db_session.get(EvaluationRun, candidate_run_id)
        if candidate is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{candidate_run_id}' was not found.",
            )
        if candidate.candidate_validation_summary is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_VALIDATION_SUMMARY_NOT_FOUND,
                "Candidate validation summary has not been generated.",
            )
        return CandidateValidationSummaryRead.model_validate(
            candidate.candidate_validation_summary
        )

    def submit_final_decision(
        self,
        candidate_run_id: UUID,
        request: CandidateFinalDecisionRequest,
        db_session: Session,
    ) -> EvaluationRun:
        candidate = db_session.get(EvaluationRun, candidate_run_id)
        if candidate is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{candidate_run_id}' was not found.",
            )
        if candidate.run_type != EvaluationRunType.CANDIDATE.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_RUN_NOT_CANDIDATE,
                "Final decisions only support candidate runs.",
            )
        if candidate.final_decision is not None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_FINAL_DECISION_ALREADY_COMPLETED,
                "The candidate final decision has already been completed.",
            )

        summary = self.get_summary(candidate_run_id, db_session)
        if (
            request.final_decision is CandidateFinalDecision.ACCEPT
            and summary.recommended_verdict is not RecommendedVerdict.ACCEPT
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_FINAL_DECISION_ACCEPT_BLOCKED,
                "Accept is blocked unless all machine Accept gates pass.",
            )
        if (
            request.final_decision.value.upper()
            != summary.recommended_verdict.value
            and not request.override_reason
        ):
            raise CandidateValidationError(
                (
                    CandidateValidationErrorCode
                    .CANDIDATE_FINAL_DECISION_OVERRIDE_REASON_REQUIRED
                ),
                "A machine recommendation override requires override_reason.",
            )

        candidate.final_decision = request.final_decision.value
        candidate.decided_by = request.decided_by.strip()
        candidate.decided_at = datetime.now(UTC)
        candidate.reason = request.reason.strip()
        candidate.override_reason = (
            request.override_reason.strip() if request.override_reason else None
        )
        db_session.commit()
        db_session.refresh(candidate)
        return candidate

    def _effective_by_conversation(
        self, run_id: UUID, db_session: Session
    ) -> dict[UUID, FinalEffectiveResultRead]:
        return {
            item.conversation_id: item
            for item in self._final_results.list_final_effective_results(
                run_id, db_session
            )
        }

    @staticmethod
    def _result_by_conversation(
        run_id: UUID, db_session: Session
    ) -> dict[UUID, EvaluationResult]:
        return {
            result.conversation_id: result
            for result in db_session.scalars(
                select(EvaluationResult).where(
                    EvaluationResult.evaluation_run_id == run_id
                )
            ).all()
        }

    def _load_lineage(
        self, candidate_run_id: UUID, db_session: Session
    ) -> tuple[EvaluationRun, EvaluationRun, OptimizationTarget, Problem]:
        candidate = db_session.get(EvaluationRun, candidate_run_id)
        if candidate is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{candidate_run_id}' was not found.",
            )
        if candidate.run_type != EvaluationRunType.CANDIDATE.value:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_RUN_NOT_CANDIDATE,
                "Candidate validation only supports candidate runs.",
            )
        baseline = db_session.get(EvaluationRun, candidate.baseline_run_id)
        target = db_session.get(OptimizationTarget, candidate.target_id)
        if baseline is None or target is None:
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                "Candidate lineage is incomplete.",
            )
        manifest = candidate.candidate_manifest_snapshot or {}
        if (
            baseline.id != target.baseline_run_id
            or baseline.dataset_id != candidate.dataset_id
            or target.status != "frozen"
            or manifest.get("plan_hash") != target.plan_hash
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                "Candidate lineage is incompatible with the frozen plan.",
            )
        target_problem = db_session.get(Problem, target.problem_id)
        if (
            target_problem is None
            or target_problem.mapping_version != PROBLEM_MAPPING_VERSION
        ):
            raise CandidateValidationError(
                CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                "Frozen target problem identity is unavailable.",
            )
        return candidate, baseline, target, target_problem

    def _compare_case(
        self,
        conversation: Conversation,
        baseline_effective: FinalEffectiveResultRead,
        candidate_effective: FinalEffectiveResultRead,
        baseline_result: EvaluationResult,
        candidate_result: EvaluationResult,
        target: OptimizationTarget,
        target_problem: Problem,
        db_session: Session,
    ) -> dict[str, Any]:
        baseline_final = baseline_effective.final_result
        candidate_final = candidate_effective.final_result
        case_is_target = conversation.external_id in set(target.target_case_ids)
        blockers: list[str] = []
        if baseline_final is None or candidate_final is None:
            blockers.append("pending_human_review")
        if baseline_final is not None and not _evidence_is_traceable(
            baseline_final, conversation
        ):
            blockers.append("baseline_evidence_insufficient")
        if candidate_final is not None and not _evidence_is_traceable(
            candidate_final, conversation
        ):
            blockers.append("candidate_evidence_insufficient")
        if (
            baseline_final is not None
            and candidate_final is not None
            and (
                baseline_final.judgment is Judgment.UNCERTAIN
                or candidate_final.judgment is Judgment.UNCERTAIN
            )
        ):
            blockers.append("uncertain_result")

        candidate_key = _result_mapping_key(candidate_final, conversation)
        baseline_key = _result_mapping_key(baseline_final, conversation)
        if not case_is_target:
            target_status = TargetProblemStatus.NOT_APPLICABLE
        elif candidate_final is None or candidate_final.judgment is Judgment.UNCERTAIN:
            target_status = TargetProblemStatus.INCONCLUSIVE
        elif candidate_key == target_problem.mapping_key:
            target_status = TargetProblemStatus.PRESENT
        else:
            target_status = TargetProblemStatus.ABSENT

        movement = CaseMovement.INCONCLUSIVE
        target_worse = False
        if not blockers and baseline_final is not None and candidate_final is not None:
            movement, target_worse = _determine_movement(
                baseline_final,
                candidate_final,
                case_is_target=case_is_target,
                target_status=target_status,
                candidate_has_other_problem=(
                    candidate_key is not None
                    and candidate_key
                    != (
                        target_problem.mapping_key
                        if case_is_target
                        else baseline_key
                    )
                ),
            )

        return {
            "baseline_run_id": target.baseline_run_id,
            "candidate_run_id": candidate_result.evaluation_run_id,
            "target_id": target.id,
            "conversation_id": conversation.id,
            "case_id": conversation.external_id,
            "baseline_evaluation_result_id": baseline_result.id,
            "candidate_evaluation_result_id": candidate_result.id,
            "movement": movement.value,
            "target_problem_status": target_status.value,
            "target_worse": target_worse,
            "regression_level": None,
            "evidence_snapshot": {
                "baseline": (
                    [item.model_dump(mode="json") for item in baseline_final.evidence]
                    if baseline_final is not None
                    else None
                ),
                "candidate": (
                    [item.model_dump(mode="json") for item in candidate_final.evidence]
                    if candidate_final is not None
                    else None
                ),
            },
            "rule_result_snapshot": {
                "mapping_version": PROBLEM_MAPPING_VERSION,
                "target_mapping_key": target_problem.mapping_key,
                "baseline_mapping_key": baseline_key,
                "candidate_mapping_key": candidate_key,
                "case_set": _case_set(conversation.metadata_),
                "blockers": blockers,
            },
        }

    @staticmethod
    def _assign_regression_levels(
        items: list[dict[str, Any]],
        target: OptimizationTarget,
        db_session: Session,
    ) -> None:
        regressed_by_candidate_key = Counter(
            item["rule_result_snapshot"].get("candidate_mapping_key")
            for item in items
            if item["movement"] == CaseMovement.REGRESSED.value
        )
        result_ids = [item["candidate_evaluation_result_id"] for item in items]
        final_by_id = {
            result.evaluation_result_id: result
            for result in HumanReviewService().list_final_effective_results(
                items[0]["candidate_run_id"], db_session
            )
        }
        reviewed_ids = set(
            db_session.scalars(
                select(HumanDecision.evaluation_result_id).where(
                    HumanDecision.evaluation_result_id.in_(result_ids)
                )
            ).all()
        )
        for item in items:
            if item["movement"] != CaseMovement.REGRESSED.value:
                continue
            effective = final_by_id[item["candidate_evaluation_result_id"]]
            final = effective.final_result
            if final is not None and final.severity is Severity.CRITICAL:
                level = RegressionLevel.CRITICAL
            elif (
                final is not None
                and final.judgment is Judgment.WARNING
                and item["candidate_evaluation_result_id"] in reviewed_ids
                and regressed_by_candidate_key[
                    item["rule_result_snapshot"].get("candidate_mapping_key")
                ]
                == 1
                and not target.protected_capabilities
            ):
                level = RegressionLevel.MINOR
            else:
                level = RegressionLevel.MAJOR
            item["regression_level"] = level.value

    def _build_summary(
        self,
        candidate: EvaluationRun,
        baseline: EvaluationRun,
        target: OptimizationTarget,
        comparisons: list[CaseComparisonRead],
        candidate_effective: dict[UUID, FinalEffectiveResultRead],
        conversations: dict[UUID, Conversation],
        db_session: Session,
    ) -> CandidateValidationSummaryRead:
        target_comparisons = [
            item for item in comparisons if item.case_id in set(target.target_case_ids)
        ]
        problem_results = self._build_problem_results(
            baseline, target, target_comparisons, db_session
        )
        review_complete = all(
            item.status is FinalEffectiveResultStatus.FINAL
            for item in candidate_effective.values()
        )
        target_worse_count = sum(item.target_worse for item in target_comparisons)
        clear_improved_count = sum(
            item.movement is CaseMovement.IMPROVED
            and item.target_problem_status is TargetProblemStatus.ABSENT
            for item in target_comparisons
        )
        remaining_high_critical = sum(
            _candidate_severity(item, candidate_effective)
            in {Severity.HIGH, Severity.CRITICAL}
            and item.target_problem_status is TargetProblemStatus.PRESENT
            for item in target_comparisons
        )
        target_inconclusive = any(
            item.movement is CaseMovement.INCONCLUSIVE for item in target_comparisons
        )
        all_resolved = bool(target_comparisons) and all(
            item.movement is CaseMovement.IMPROVED
            and item.target_problem_status is TargetProblemStatus.ABSENT
            for item in target_comparisons
        )
        threshold = math.ceil(2 * len(target_comparisons) / 3)
        if target_inconclusive:
            target_outcome = "inconclusive"
        elif all_resolved and target_worse_count == 0:
            target_outcome = "resolved"
        elif (
            clear_improved_count >= threshold
            and target_worse_count == 0
            and remaining_high_critical == 0
        ):
            target_outcome = "improved"
        else:
            target_outcome = "not_improved"

        baseline_problem_keys = set(
            db_session.scalars(
                select(Problem.mapping_key).where(
                    Problem.evaluation_run_id == baseline.id
                )
            ).all()
        )
        other_groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"case_ids": [], "core_case_ids": [], "severities": []}
        )
        for item in comparisons:
            key = item.rule_result_snapshot.get("candidate_mapping_key")
            if not key or key == item.rule_result_snapshot["target_mapping_key"]:
                continue
            group = other_groups[key]
            group["case_ids"].append(item.case_id)
            if item.rule_result_snapshot.get("case_set") == "core":
                group["core_case_ids"].append(item.case_id)
            severity = _candidate_severity(item, candidate_effective)
            if severity is not None:
                group["severities"].append(severity.value)
        other_problems = [
            {"mapping_key": key, **value} for key, value in sorted(other_groups.items())
        ]
        new_systematic = [
            problem
            for problem in other_problems
            if problem["mapping_key"] not in baseline_problem_keys
            and (
                len(problem["core_case_ids"]) >= 2
                or any(level in {"high", "critical"} for level in problem["severities"])
            )
        ]
        regression_counts = Counter(
            item.regression_level.value
            for item in comparisons
            if item.regression_level is not None
        )
        manifest = candidate.candidate_manifest_snapshot or {}
        persisted_responses = candidate.candidate_responses_snapshot or []
        calculated_response_hash = build_response_set_hash(persisted_responses)
        integrity_passed = (
            candidate.response_set_hash == manifest.get("response_set_hash")
            and candidate.response_set_hash == calculated_response_hash
            and manifest.get("case_count") == len(comparisons)
            and manifest.get("actual_change_status") == "verified"
            and manifest.get("generation_parity_status") == "verified"
            and manifest.get("plan_hash") == target.plan_hash
        )
        compatibility_passed = (
            candidate.dataset_id == baseline.dataset_id
            and candidate.judge_contract_version == baseline.judge_contract_version
            and candidate.judge_model == baseline.judge_model
        )
        protected_gate = (
            "not_applicable" if not target.protected_capabilities else "unsupported"
        )
        blockers: list[str] = []
        if not review_complete:
            blockers.append("pending_human_review")
        if not integrity_passed:
            blockers.append("integrity_gate_failed")
        if not compatibility_passed:
            blockers.append("compatibility_gate_failed")
        if protected_gate == "unsupported":
            blockers.append("protected_capability_membership_unsupported")
        if any(item.movement is CaseMovement.INCONCLUSIVE for item in comparisons):
            blockers.append("case_comparison_inconclusive")
        has_decisive_continue_signal = bool(
            regression_counts[RegressionLevel.CRITICAL.value]
            or regression_counts[RegressionLevel.MAJOR.value]
            or new_systematic
        )
        problem_requires_continue = any(
            item.status
            in {
                ProblemValidationStatus.REGRESSED,
                ProblemValidationStatus.NOT_IMPROVED,
                ProblemValidationStatus.PARTIALLY_IMPROVED,
            }
            for item in problem_results
        )
        problem_is_inconclusive = any(
            item.status is ProblemValidationStatus.INCONCLUSIVE
            for item in problem_results
        )
        if has_decisive_continue_signal or problem_requires_continue:
            verdict = RecommendedVerdict.CONTINUE
        elif blockers or problem_is_inconclusive:
            verdict = RecommendedVerdict.INCONCLUSIVE
        elif (
            target_outcome not in {"resolved", "improved"}
            or remaining_high_critical
        ):
            verdict = RecommendedVerdict.CONTINUE
        else:
            verdict = RecommendedVerdict.ACCEPT
        return CandidateValidationSummaryRead(
            candidate_run_id=candidate.id,
            baseline_run_id=baseline.id,
            target_id=target.id,
            target_outcome=target_outcome,
            problem_results=problem_results,
            regression_summary={
                "critical": regression_counts["critical"],
                "major": regression_counts["major"],
                "minor": regression_counts["minor"],
            },
            other_problems=other_problems,
            new_systematic_problems=new_systematic,
            review_complete=review_complete,
            integrity_gate="passed" if integrity_passed else "failed",
            compatibility_gate="passed" if compatibility_passed else "failed",
            protected_capability_gate=protected_gate,
            recommended_verdict=verdict,
            policy_version=target.policy_version or "",
            rule_outcomes={
                "target_case_count": len(target_comparisons),
                "clear_improved_count": clear_improved_count,
                "improvement_threshold": threshold,
                "target_worse_count": target_worse_count,
                "remaining_target_high_critical": remaining_high_critical,
            },
            blockers=blockers,
        )

    def _build_problem_results(
        self,
        baseline: EvaluationRun,
        target: OptimizationTarget,
        comparisons: list[CaseComparisonRead],
        db_session: Session,
    ) -> list[CandidateProblemResultRead]:
        problem_ids = list(
            dict.fromkeys(
                UUID(problem_id)
                for problem_id in (target.problem_ids or [str(target.problem_id)])
            )
        )
        problems = {
            problem.problem_id: problem
            for problem in ProblemAggregationService(
                final_result_service=self._final_results
            ).list_problems(baseline.id, db_session)
            if problem.problem_id in set(problem_ids)
        }
        comparisons_by_case = {item.case_id: item for item in comparisons}
        results: list[CandidateProblemResultRead] = []
        for problem_id in problem_ids:
            problem = problems.get(problem_id)
            if problem is None:
                raise CandidateValidationError(
                    CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                    "Frozen target problem identity is unavailable.",
                )
            affected = set(problem.affected_case_ids)
            case_ids = [
                case_id for case_id in target.target_case_ids if case_id in affected
            ]
            if not case_ids or any(
                case_id not in comparisons_by_case for case_id in case_ids
            ):
                raise CandidateValidationError(
                    CandidateValidationErrorCode.CANDIDATE_COMPARISON_NOT_READY,
                    "Problem comparisons must cover the frozen target scope.",
                )
            results.append(
                CandidateProblemResultRead(
                    problem_id=problem_id,
                    definition=problem.definition,
                    case_ids=case_ids,
                    status=_aggregate_problem_status(
                        [comparisons_by_case[case_id].movement for case_id in case_ids]
                    ),
                )
            )
        return results


def _aggregate_problem_status(
    movements: list[CaseMovement],
) -> ProblemValidationStatus:
    if CaseMovement.REGRESSED in movements:
        return ProblemValidationStatus.REGRESSED
    if CaseMovement.INCONCLUSIVE in movements:
        return ProblemValidationStatus.INCONCLUSIVE
    if CaseMovement.PARTIALLY_IMPROVED in movements:
        return ProblemValidationStatus.PARTIALLY_IMPROVED
    if CaseMovement.IMPROVED in movements:
        return ProblemValidationStatus.IMPROVED
    return ProblemValidationStatus.NOT_IMPROVED


def build_response_set_hash(responses: list[dict[str, Any]]) -> str:
    payload = [
        {
            "conversation_id": str(item["conversation_id"]),
            "case_id": item["case_id"],
            "assistant_content": item["assistant_content"],
        }
        for item in sorted(
            responses,
            key=lambda item: (item["case_id"], str(item["conversation_id"])),
        )
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_conversation(
    source: Conversation, assistant_content: str
) -> Conversation:
    user_messages = [
        dict(message) for message in source.messages if message.get("role") == "user"
    ]
    return Conversation(
        id=source.id,
        dataset_id=source.dataset_id,
        external_id=source.external_id,
        messages=[
            *user_messages,
            {"role": "assistant", "content": assistant_content},
        ],
        metadata_=source.metadata_,
    )


def _determine_movement(
    baseline: JudgeOutput,
    candidate: JudgeOutput,
    *,
    case_is_target: bool,
    target_status: TargetProblemStatus,
    candidate_has_other_problem: bool,
) -> tuple[CaseMovement, bool]:
    quality = {Judgment.FAILURE: 0, Judgment.WARNING: 1, Judgment.SUCCESS: 2}
    severity = {
        Severity.LOW: 0,
        Severity.MEDIUM: 1,
        Severity.HIGH: 2,
        Severity.CRITICAL: 3,
    }
    baseline_quality = quality[baseline.judgment]
    candidate_quality = quality[candidate.judgment]
    severity_increased = (
        baseline.severity is not None
        and candidate.severity is not None
        and severity[candidate.severity] > severity[baseline.severity]
    )
    severity_decreased = (
        baseline.severity is not None
        and candidate.severity is not None
        and severity[candidate.severity] < severity[baseline.severity]
    )
    target_worse = bool(
        case_is_target
        and target_status is TargetProblemStatus.PRESENT
        and (candidate_quality < baseline_quality or severity_increased)
    )
    if candidate_quality < baseline_quality or severity_increased:
        return CaseMovement.REGRESSED, target_worse
    if candidate_has_other_problem:
        return CaseMovement.INCONCLUSIVE, False
    if candidate_quality > baseline_quality:
        if case_is_target and target_status is TargetProblemStatus.PRESENT:
            return CaseMovement.PARTIALLY_IMPROVED, False
        return CaseMovement.IMPROVED, False
    if severity_decreased:
        return CaseMovement.PARTIALLY_IMPROVED, False
    return CaseMovement.STABLE, False


def _result_mapping_key(
    result: JudgeOutput | None, conversation: Conversation
) -> str | None:
    if (
        result is None
        or result.judgment not in {Judgment.WARNING, Judgment.FAILURE}
        or not result.problem
        or not result.problem.strip()
    ):
        return None
    metadata = (
        conversation.metadata_ if isinstance(conversation.metadata_, dict) else {}
    )
    scenario = metadata.get("scenario")
    if not isinstance(scenario, str) or not scenario.strip():
        return None
    return build_problem_mapping_key(
        scenario, normalize_problem_definition(result.problem)
    )


def _evidence_is_traceable(result: JudgeOutput, conversation: Conversation) -> bool:
    if not result.evidence:
        return False
    metadata = (
        conversation.metadata_ if isinstance(conversation.metadata_, dict) else {}
    )
    available = {
        "assistant_response": any(
            message.get("role") == "assistant" for message in conversation.messages
        ),
        "business_context": metadata.get("business_context") is not None,
        "reference_evidence": metadata.get("reference_evidence") is not None,
    }
    expected = {
        "response": "assistant_response",
        "case_fact": "business_context",
        "reference": "reference_evidence",
    }
    return all(
        item.source_ref == expected[item.evidence_type.value]
        and available[expected[item.evidence_type.value]]
        for item in result.evidence
    )


def _candidate_severity(
    comparison: CaseComparisonRead,
    effective_results: dict[UUID, FinalEffectiveResultRead],
) -> Severity | None:
    result = effective_results.get(comparison.conversation_id)
    return result.final_result.severity if result and result.final_result else None


def _case_set(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    nested = metadata.get("metadata")
    if not isinstance(nested, dict):
        return None
    value = nested.get("case_set")
    return value if isinstance(value, str) else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
