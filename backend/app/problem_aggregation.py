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

from app.human_review import HumanReviewService
from app.judge_contract import Judgment
from app.models import (
    Conversation,
    EvaluationResult,
    EvaluationRun,
    Problem,
    ResultProblemLink,
)
from app.schemas import FinalEffectiveResultStatus, ProblemRead

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
    ) -> None:
        self._final_result_service = final_result_service or HumanReviewService()

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
        if db_session.get(EvaluationRun, evaluation_run_id) is None:
            raise ProblemAggregationError(
                ProblemAggregationErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )

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
                    Conversation.external_id,
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
                    EvaluationResult.evaluation_run_id == evaluation_run_id,
                )
                .order_by(
                    Conversation.external_id.asc(),
                    EvaluationResult.id.asc(),
                )
            ).all()
            response.append(
                ProblemRead(
                    problem_id=problem.id,
                    evaluation_run_id=problem.evaluation_run_id,
                    scenario=problem.scenario,
                    definition=problem.definition,
                    mapping_key=problem.mapping_key,
                    mapping_version=problem.mapping_version,
                    created_at=problem.created_at,
                    affected_case_count=len(affected),
                    affected_evaluation_result_ids=[row[0] for row in affected],
                    affected_case_ids=[row[1] for row in affected],
                )
            )
        return response

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
