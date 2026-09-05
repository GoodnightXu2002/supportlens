from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.business_impact_mapping import BusinessImpactMappingService
from app.human_review import HumanReviewService
from app.judge_contract import Judgment
from app.models import (
    Conversation,
    EvaluationResult,
    EvaluationRun,
    HumanDecision,
    Problem,
    ResultProblemLink,
)
from app.problem_priority import (
    ProblemCaseSignal,
    build_problem_profile,
    rank_problem_profiles,
)
from app.schemas import (
    FinalEffectiveResultStatus,
    ProblemEvidenceRead,
    ProblemRead,
)

PROBLEM_MAPPING_VERSION = "PRIMARY-PROBLEM-EXACT-V1"
PRIMARY_PROBLEM_ROLE = "primary"


class ProblemAggregationErrorCode(StrEnum):
    EVALUATION_RUN_NOT_FOUND = "evaluation_run_not_found"
    PROBLEM_AGGREGATION_NOT_BASELINE = "problem_aggregation_not_baseline"
    PROBLEM_AGGREGATION_RUN_NOT_COMPLETED = (
        "problem_aggregation_run_not_completed"
    )
    PROBLEM_AGGREGATION_FINAL_RESULTS_INCOMPLETE = (
        "problem_aggregation_final_results_incomplete"
    )
    PROBLEM_AGGREGATION_PENDING_REVIEW = "problem_aggregation_pending_review"
    PROBLEM_AGGREGATION_ALREADY_COMPLETED = (
        "problem_aggregation_already_completed"
    )
    PROBLEM_AGGREGATION_INVALID_INPUT = "problem_aggregation_invalid_input"
    PROBLEM_AGGREGATION_PERSISTENCE_FAILED = (
        "problem_aggregation_persistence_failed"
    )


class ProblemAggregationError(RuntimeError):
    def __init__(self, code: ProblemAggregationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProblemAggregationService:
    def __init__(
        self,
        final_result_service: HumanReviewService | None = None,
        business_impact_service: BusinessImpactMappingService | None = None,
    ) -> None:
        self._final_result_service = final_result_service or HumanReviewService()
        self._business_impact_service = (
            business_impact_service or BusinessImpactMappingService()
        )

    def generate(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> list[ProblemRead]:
        evaluation_run = db_session.get(EvaluationRun, evaluation_run_id)
        if evaluation_run is None:
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )
        if evaluation_run.run_type != "baseline":
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_NOT_BASELINE,
                "Problem aggregation only supports baseline evaluation runs.",
            )
        if evaluation_run.status != "completed":
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_RUN_NOT_COMPLETED,
                "Problem aggregation requires a completed evaluation run.",
            )
        if self._already_completed(evaluation_run, db_session):
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_ALREADY_COMPLETED,
                "Problem aggregation has already been completed for this run.",
            )

        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == evaluation_run.dataset_id
                )
            ).all()
        )
        conversation_by_id = {
            conversation.id: conversation for conversation in conversations
        }
        effective_results = (
            self._final_result_service.list_final_effective_results(
                evaluation_run.id,
                db_session,
            )
        )
        if {
            result.conversation_id for result in effective_results
        } != set(conversation_by_id):
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_FINAL_RESULTS_INCOMPLETE,
                "Every dataset conversation must have an EvaluationResult.",
            )

        pending_review_count = sum(
            result.status is FinalEffectiveResultStatus.PENDING_REVIEW
            for result in effective_results
        )
        if pending_review_count:
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_PENDING_REVIEW,
                "Problem aggregation requires pending_review_count=0.",
            )

        grouped_results: dict[
            str,
            tuple[str, str, list[UUID]],
        ] = {}
        for effective_result in effective_results:
            final_result = effective_result.final_result
            if final_result is None or final_result.judgment not in {
                Judgment.WARNING,
                Judgment.FAILURE,
            }:
                continue
            if not final_result.problem or not final_result.problem.strip():
                continue

            conversation = conversation_by_id[effective_result.conversation_id]
            metadata = (
                conversation.metadata_
                if isinstance(conversation.metadata_, dict)
                else {}
            )
            scenario = metadata.get("scenario")
            if not isinstance(scenario, str) or not scenario.strip():
                raise ProblemAggregationError(
                    ProblemAggregationErrorCode.PROBLEM_AGGREGATION_INVALID_INPUT,
                    "Eligible final results require a non-empty scenario.",
                )

            definition = normalize_problem_definition(final_result.problem)
            mapping_key = build_problem_mapping_key(scenario, definition)
            group = grouped_results.get(mapping_key)
            if group is None:
                grouped_results[mapping_key] = (
                    scenario,
                    definition,
                    [effective_result.evaluation_result_id],
                )
            else:
                group[2].append(effective_result.evaluation_result_id)

        for mapping_key in sorted(grouped_results):
            scenario, definition, evaluation_result_ids = grouped_results[
                mapping_key
            ]
            problem = Problem(
                evaluation_run=evaluation_run,
                scenario=scenario,
                definition=definition,
                mapping_key=mapping_key,
                mapping_version=PROBLEM_MAPPING_VERSION,
            )
            db_session.add(problem)
            for evaluation_result_id in evaluation_result_ids:
                db_session.add(
                    ResultProblemLink(
                        problem=problem,
                        evaluation_result_id=evaluation_result_id,
                        role=PRIMARY_PROBLEM_ROLE,
                    )
                )

        evaluation_run.problem_aggregation_completed_at = datetime.now(UTC)
        try:
            db_session.commit()
        except IntegrityError as error:
            db_session.rollback()
            if self._already_completed(evaluation_run, db_session):
                raise ProblemAggregationError(
                    ProblemAggregationErrorCode.PROBLEM_AGGREGATION_ALREADY_COMPLETED,
                    "Problem aggregation has already been completed for this run.",
                ) from error
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.PROBLEM_AGGREGATION_PERSISTENCE_FAILED,
                "Problem aggregation could not be persisted.",
            ) from error
        return self.list_problems(evaluation_run.id, db_session)

    def list_problems(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> list[ProblemRead]:
        evaluation_run = db_session.get(EvaluationRun, evaluation_run_id)
        if evaluation_run is None:
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )

        dataset_conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == evaluation_run.dataset_id
                )
            ).all()
        )
        core_denominator = sum(
            _conversation_case_set(conversation.metadata_) == "core"
            for conversation in dataset_conversations
        )

        effective_result_by_id = {
            result.evaluation_result_id: result
            for result in self._final_result_service.list_final_effective_results(
                evaluation_run_id,
                db_session,
            )
        }
        human_decision_by_result_id = {
            decision.evaluation_result_id: decision
            for decision in db_session.scalars(
                select(HumanDecision)
                .join(
                    EvaluationResult,
                    EvaluationResult.id == HumanDecision.evaluation_result_id,
                )
                .where(
                    EvaluationResult.evaluation_run_id == evaluation_run_id
                )
            ).all()
        }

        problems = list(
            db_session.scalars(
                select(Problem)
                .where(Problem.evaluation_run_id == evaluation_run_id)
                .order_by(
                    Problem.scenario.asc(),
                    Problem.definition.asc(),
                    Problem.id.asc(),
                )
            ).all()
        )
        response: list[ProblemRead] = []
        for problem in problems:
            affected = db_session.execute(
                select(
                    ResultProblemLink.evaluation_result_id,
                    Conversation.id,
                    Conversation.external_id,
                    Conversation.metadata_,
                )
                .join(
                    EvaluationResult,
                    EvaluationResult.id
                    == ResultProblemLink.evaluation_result_id,
                )
                .join(
                    Conversation,
                    Conversation.id == EvaluationResult.conversation_id,
                )
                .where(
                    ResultProblemLink.problem_id == problem.id,
                    ResultProblemLink.role == PRIMARY_PROBLEM_ROLE,
                    EvaluationResult.evaluation_run_id == evaluation_run_id,
                )
                .order_by(
                    Conversation.external_id.asc(),
                    EvaluationResult.id.asc(),
                )
            ).all()
            evidence: list[ProblemEvidenceRead] = []
            case_signals: list[ProblemCaseSignal] = []
            for (
                evaluation_result_id,
                conversation_id,
                case_id,
                conversation_metadata,
            ) in affected:
                effective_result = effective_result_by_id.get(
                    evaluation_result_id
                )
                if (
                    effective_result is None
                    or effective_result.final_result is None
                ):
                    raise ProblemAggregationError(
                        ProblemAggregationErrorCode.PROBLEM_AGGREGATION_FINAL_RESULTS_INCOMPLETE,
                        "Problem evidence requires a Final Effective Result.",
                    )
                evidence.extend(
                    ProblemEvidenceRead(
                        problem_id=problem.id,
                        evaluation_result_id=evaluation_result_id,
                        conversation_id=conversation_id,
                        case_id=case_id,
                        evidence_type=item.evidence_type,
                        content=item.content,
                        source_ref=item.source_ref,
                    )
                    for item in effective_result.final_result.evidence
                )
                decision = human_decision_by_result_id.get(
                    evaluation_result_id
                )
                case_signals.append(
                    ProblemCaseSignal(
                        is_core=(
                            _conversation_case_set(conversation_metadata)
                            == "core"
                        ),
                        final_status=effective_result.status,
                        final_result=effective_result.final_result,
                        human_problem_or_severity_changed=(
                            _human_changed_problem_or_severity(decision)
                        ),
                    )
                )
            profile = build_problem_profile(
                cases=case_signals,
                core_denominator=core_denominator,
                run_status=evaluation_run.status,
                business_impact_lookup=(
                    self._business_impact_service.lookup(problem.mapping_key)
                ),
            )
            response.append(
                ProblemRead(
                    **profile.model_dump(),
                    problem_id=problem.id,
                    evaluation_run_id=problem.evaluation_run_id,
                    scenario=problem.scenario,
                    definition=problem.definition,
                    mapping_key=problem.mapping_key,
                    mapping_version=problem.mapping_version,
                    created_at=problem.created_at,
                    affected_case_count=len(affected),
                    affected_evaluation_result_ids=[row[0] for row in affected],
                    affected_case_ids=[row[2] for row in affected],
                    evidence=evidence,
                )
            )
        assignments = rank_problem_profiles(response)
        return [
            problem.model_copy(
                update={
                    "rank": assignment.rank,
                    "equal_review_priority": (
                        assignment.equal_review_priority
                    ),
                }
            )
            for problem, assignment in zip(
                response,
                assignments,
                strict=True,
            )
        ]

    @staticmethod
    def _already_completed(
        evaluation_run: EvaluationRun,
        db_session: Session,
    ) -> bool:
        if evaluation_run.problem_aggregation_completed_at is not None:
            return True
        if db_session.scalar(
            select(Problem.id).where(
                Problem.evaluation_run_id == evaluation_run.id
            )
        ):
            return True
        return (
            db_session.scalar(
                select(ResultProblemLink.id)
                .join(
                    EvaluationResult,
                    EvaluationResult.id
                    == ResultProblemLink.evaluation_result_id,
                )
                .where(
                    EvaluationResult.evaluation_run_id == evaluation_run.id
                )
            )
            is not None
        )


def normalize_problem_definition(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def build_problem_mapping_key(scenario: str, definition: str) -> str:
    return json.dumps(
        [scenario, definition],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _conversation_case_set(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    nested_metadata = metadata.get("metadata")
    if not isinstance(nested_metadata, dict):
        return None
    case_set = nested_metadata.get("case_set")
    return case_set if isinstance(case_set, str) else None


def _human_changed_problem_or_severity(
    decision: HumanDecision | None,
) -> bool:
    if decision is None:
        return False
    return any(
        decision.original_result.get(field) != decision.final_result.get(field)
        for field in ("problem", "severity")
    )
