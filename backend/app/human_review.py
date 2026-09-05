from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.judge_contract import JudgeOutput, validate_judge_output
from app.models import Conversation, EvaluationResult, EvaluationRun, HumanDecision
from app.schemas import (
    FinalEffectiveResultRead,
    FinalEffectiveResultSource,
    FinalEffectiveResultStatus,
    HumanDecisionRead,
    HumanReviewAction,
)


class HumanReviewErrorCode(StrEnum):
    EVALUATION_RESULT_NOT_FOUND = "evaluation_result_not_found"
    EVALUATION_RUN_NOT_FOUND = "evaluation_run_not_found"
    HUMAN_REVIEW_NOT_REQUIRED = "human_review_not_required"
    HUMAN_REVIEW_ALREADY_COMPLETED = "human_review_already_completed"
    HUMAN_REVIEW_FINAL_RESULT_REQUIRED = "human_review_final_result_required"
    HUMAN_REVIEW_CONFIRM_RESULT_MISMATCH = (
        "human_review_confirm_result_mismatch"
    )
    HUMAN_REVIEW_CHANGE_REASON_REQUIRED = "human_review_change_reason_required"
    HUMAN_REVIEW_INVALID_RESULT = "human_review_invalid_result"
    HUMAN_REVIEW_PERSISTENCE_FAILED = "human_review_persistence_failed"


class HumanReviewError(RuntimeError):
    def __init__(self, code: HumanReviewErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class HumanReviewService:
    def submit(
        self,
        evaluation_result_id: UUID,
        *,
        reviewer: str,
        action: HumanReviewAction,
        final_result: JudgeOutput | dict[str, Any] | None,
        change_reason: str | None,
        db_session: Session,
    ) -> HumanDecision:
        evaluation_result = db_session.get(
            EvaluationResult,
            evaluation_result_id,
        )
        if evaluation_result is None:
            raise HumanReviewError(
                HumanReviewErrorCode.EVALUATION_RESULT_NOT_FOUND,
                f"Evaluation result '{evaluation_result_id}' was not found.",
            )

        if evaluation_result.human_decision is not None:
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_ALREADY_COMPLETED,
                "Human review has already been completed for this result.",
            )
        if evaluation_result.review_required is not True:
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_NOT_REQUIRED,
                "Human review is only accepted when review_required is true.",
            )
        if not reviewer.strip():
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_INVALID_RESULT,
                "Reviewer must not be empty.",
            )

        original_output = self._evaluation_output(evaluation_result)
        original_payload = original_output.model_dump(mode="json")
        final_payload = self._final_payload(
            action,
            final_result,
            original_payload,
        )

        if final_payload != original_payload and not (
            change_reason and change_reason.strip()
        ):
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_CHANGE_REASON_REQUIRED,
                "A non-empty change reason is required when the result is changed.",
            )

        decision = HumanDecision(
            evaluation_result=evaluation_result,
            reviewer=reviewer,
            original_result=original_payload,
            final_result=final_payload,
            change_reason=change_reason,
        )
        db_session.add(decision)
        try:
            db_session.commit()
        except IntegrityError as error:
            db_session.rollback()
            if db_session.scalar(
                select(HumanDecision.id).where(
                    HumanDecision.evaluation_result_id == evaluation_result_id
                )
            ):
                raise HumanReviewError(
                    HumanReviewErrorCode.HUMAN_REVIEW_ALREADY_COMPLETED,
                    "Human review has already been completed for this result.",
                ) from error
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_PERSISTENCE_FAILED,
                "Human review could not be persisted.",
            ) from error
        db_session.refresh(decision)
        return decision

    def list_final_effective_results(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> list[FinalEffectiveResultRead]:
        if db_session.get(EvaluationRun, evaluation_run_id) is None:
            raise HumanReviewError(
                HumanReviewErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )

        rows = db_session.execute(
            select(EvaluationResult, Conversation, HumanDecision)
            .join(
                Conversation,
                Conversation.id == EvaluationResult.conversation_id,
            )
            .outerjoin(
                HumanDecision,
                HumanDecision.evaluation_result_id == EvaluationResult.id,
            )
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .order_by(
                Conversation.external_id.asc(),
                EvaluationResult.id.asc(),
            )
        ).all()

        effective_results: list[FinalEffectiveResultRead] = []
        for evaluation_result, conversation, decision in rows:
            machine_result = self._evaluation_output(evaluation_result)
            if evaluation_result.review_required is False:
                status = FinalEffectiveResultStatus.FINAL
                source = FinalEffectiveResultSource.MACHINE
                final_result = machine_result
                decision_id = None
            elif decision is None:
                status = FinalEffectiveResultStatus.PENDING_REVIEW
                source = None
                final_result = None
                decision_id = None
            else:
                status = FinalEffectiveResultStatus.FINAL
                source = FinalEffectiveResultSource.HUMAN
                final_result = self._validate_output(decision.final_result)
                decision_id = decision.id

            effective_results.append(
                FinalEffectiveResultRead(
                    evaluation_result_id=evaluation_result.id,
                    conversation_id=conversation.id,
                    case_id=conversation.external_id,
                    status=status,
                    source=source,
                    machine_result=machine_result,
                    final_result=final_result,
                    human_decision_id=decision_id,
                    human_decision=(
                        HumanDecisionRead.model_validate(decision)
                        if decision is not None
                        else None
                    ),
                )
            )
        return effective_results

    def _final_payload(
        self,
        action: HumanReviewAction,
        final_result: JudgeOutput | dict[str, Any] | None,
        original_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action is HumanReviewAction.CONFIRM:
            if final_result is not None:
                supplied_payload = self._validate_output(final_result).model_dump(
                    mode="json"
                )
                if supplied_payload != original_payload:
                    raise HumanReviewError(
                        HumanReviewErrorCode.HUMAN_REVIEW_CONFIRM_RESULT_MISMATCH,
                        "A confirm action cannot change the machine result.",
                    )
            return original_payload

        if final_result is None:
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_FINAL_RESULT_REQUIRED,
                "A correct action requires a final result.",
            )
        return self._validate_output(final_result).model_dump(mode="json")

    def _evaluation_output(
        self,
        evaluation_result: EvaluationResult,
    ) -> JudgeOutput:
        return self._validate_output(
            {
                field: getattr(evaluation_result, field)
                for field in JudgeOutput.model_fields
            }
        )

    @staticmethod
    def _validate_output(payload: JudgeOutput | dict[str, Any]) -> JudgeOutput:
        if isinstance(payload, JudgeOutput):
            return payload
        try:
            return validate_judge_output(payload)
        except ValidationError as error:
            raise HumanReviewError(
                HumanReviewErrorCode.HUMAN_REVIEW_INVALID_RESULT,
                "Human review result does not satisfy the JudgeOutput contract.",
            ) from error
