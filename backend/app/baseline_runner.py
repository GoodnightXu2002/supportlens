from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.judge_contract import assemble_judge_input
from app.judge_executor import JudgeExecutionError, execute_judge
from app.llm_provider import LLMProvider
from app.models import Conversation, EvaluationResult, EvaluationRun
from app.schemas import EvaluationRunStatus, EvaluationRunType


class BaselineRunnerErrorCode(StrEnum):
    EVALUATION_RUN_NOT_FOUND = "evaluation_run_not_found"
    EVALUATION_RUN_NOT_STARTABLE = "evaluation_run_not_startable"
    EVALUATION_RUN_NOT_BASELINE = "evaluation_run_not_baseline"


class BaselineRunnerError(RuntimeError):
    def __init__(self, code: BaselineRunnerErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class BaselineRunner:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def execute(self, evaluation_run_id: UUID, db_session: Session) -> EvaluationRun:
        evaluation_run = self._load_baseline_run(evaluation_run_id, db_session)
        if evaluation_run.status != EvaluationRunStatus.PENDING.value:
            raise BaselineRunnerError(
                BaselineRunnerErrorCode.EVALUATION_RUN_NOT_STARTABLE,
                "Only a pending evaluation run can be executed.",
            )

        conversations = self._dataset_conversations(evaluation_run, db_session)
        business_reference = self._validate_preconditions(
            evaluation_run,
            conversations,
            db_session,
        )
        if business_reference is None:
            return evaluation_run

        evaluation_run.status = EvaluationRunStatus.RUNNING.value
        evaluation_run.error_code = None
        evaluation_run.error_message = None
        evaluation_run.case_errors = []
        db_session.commit()

        return self._execute_conversations(
            evaluation_run,
            conversations,
            business_reference,
            db_session,
        )

    def retry_failed_cases(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> EvaluationRun:
        evaluation_run = self._load_baseline_run(evaluation_run_id, db_session)
        if evaluation_run.status != EvaluationRunStatus.PARTIAL_FAILURE.value:
            raise BaselineRunnerError(
                BaselineRunnerErrorCode.EVALUATION_RUN_NOT_STARTABLE,
                "Only a partial_failure evaluation run can retry failed cases.",
            )

        business_reference = evaluation_run.business_reference_snapshot
        if not business_reference or not business_reference.strip():
            return self._mark_invalid(
                evaluation_run,
                "Evaluation run business reference snapshot is missing or empty.",
                db_session,
            )

        conversations = self._failed_conversations(evaluation_run, db_session)
        if conversations is None:
            return self._mark_invalid(
                evaluation_run,
                "Evaluation run case errors do not identify valid failed cases.",
                db_session,
            )
        if not self._judge_inputs_are_valid(conversations):
            return self._mark_invalid(
                evaluation_run,
                "One or more failed cases contain invalid Judge input.",
                db_session,
            )

        evaluation_run.status = EvaluationRunStatus.RUNNING.value
        evaluation_run.error_code = None
        evaluation_run.error_message = None
        db_session.commit()

        return self._execute_conversations(
            evaluation_run,
            conversations,
            business_reference,
            db_session,
        )

    def _load_baseline_run(
        self,
        evaluation_run_id: UUID,
        db_session: Session,
    ) -> EvaluationRun:
        evaluation_run = db_session.get(EvaluationRun, evaluation_run_id)
        if evaluation_run is None:
            raise BaselineRunnerError(
                BaselineRunnerErrorCode.EVALUATION_RUN_NOT_FOUND,
                f"Evaluation run '{evaluation_run_id}' was not found.",
            )
        if evaluation_run.run_type != EvaluationRunType.BASELINE.value:
            raise BaselineRunnerError(
                BaselineRunnerErrorCode.EVALUATION_RUN_NOT_BASELINE,
                "Baseline runner only supports baseline evaluation runs.",
            )
        return evaluation_run

    def _validate_preconditions(
        self,
        evaluation_run: EvaluationRun,
        conversations: list[Conversation],
        db_session: Session,
    ) -> str | None:
        business_reference = evaluation_run.business_reference_snapshot
        if not business_reference or not business_reference.strip():
            self._mark_invalid(
                evaluation_run,
                "Evaluation run business reference snapshot is missing or empty.",
                db_session,
            )
            return None

        stored_result_count = db_session.scalar(
            select(func.count())
            .select_from(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == evaluation_run.id)
        )
        if stored_result_count or evaluation_run.case_errors:
            self._mark_invalid(
                evaluation_run,
                "Pending evaluation run already contains execution output.",
                db_session,
            )
            return None

        if not self._judge_inputs_are_valid(conversations):
            self._mark_invalid(
                evaluation_run,
                "One or more dataset conversations contain invalid Judge input.",
                db_session,
            )
            return None
        return business_reference

    @staticmethod
    def _judge_inputs_are_valid(conversations: list[Conversation]) -> bool:
        try:
            for conversation in conversations:
                assemble_judge_input(conversation)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _dataset_conversations(
        evaluation_run: EvaluationRun,
        db_session: Session,
    ) -> list[Conversation]:
        return list(
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

    @staticmethod
    def _failed_conversations(
        evaluation_run: EvaluationRun,
        db_session: Session,
    ) -> list[Conversation] | None:
        case_errors = evaluation_run.case_errors
        if not case_errors:
            return None

        try:
            failed_ids = [UUID(error["conversation_id"]) for error in case_errors]
        except (KeyError, TypeError, ValueError):
            return None
        if len(set(failed_ids)) != len(failed_ids):
            return None

        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == evaluation_run.dataset_id,
                    Conversation.id.in_(failed_ids),
                )
            ).all()
        )
        conversation_by_id = {
            conversation.id: conversation for conversation in conversations
        }
        if set(conversation_by_id) != set(failed_ids):
            return None

        successful_ids = set(
            db_session.scalars(
                select(EvaluationResult.conversation_id).where(
                    EvaluationResult.evaluation_run_id == evaluation_run.id,
                    EvaluationResult.conversation_id.in_(failed_ids),
                )
            ).all()
        )
        if successful_ids:
            return None
        return [conversation_by_id[conversation_id] for conversation_id in failed_ids]

    def _execute_conversations(
        self,
        evaluation_run: EvaluationRun,
        conversations: list[Conversation],
        business_reference: str,
        db_session: Session,
    ) -> EvaluationRun:
        case_errors: list[dict[str, Any]] = []
        for conversation in conversations:
            try:
                execution = execute_judge(
                    conversation,
                    business_reference=business_reference,
                    provider=self._provider,
                )
            except JudgeExecutionError as error:
                case_errors.append(
                    {
                        "conversation_id": str(conversation.id),
                        "case_id": conversation.external_id,
                        "error_code": error.error_code,
                        "error_message": str(error),
                        "raw_judge_output": error.raw_judge_output,
                    }
                )
                evaluation_run.case_errors = list(case_errors)
                db_session.commit()
                continue

            db_session.add(
                EvaluationResult(
                    evaluation_run_id=evaluation_run.id,
                    conversation_id=conversation.id,
                    raw_judge_output=execution.raw_judge_output,
                    **execution.output.model_dump(mode="json"),
                )
            )
            db_session.commit()

        evaluation_run.case_errors = case_errors
        result_count = db_session.scalar(
            select(func.count())
            .select_from(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == evaluation_run.id)
        )
        if case_errors and result_count:
            evaluation_run.status = EvaluationRunStatus.PARTIAL_FAILURE.value
        elif result_count == 0:
            evaluation_run.status = EvaluationRunStatus.FAILED.value
        else:
            evaluation_run.status = EvaluationRunStatus.COMPLETED.value
        db_session.commit()
        db_session.refresh(evaluation_run)
        return evaluation_run

    @staticmethod
    def _mark_invalid(
        evaluation_run: EvaluationRun,
        message: str,
        db_session: Session,
    ) -> EvaluationRun:
        evaluation_run.status = EvaluationRunStatus.INVALID.value
        evaluation_run.error_code = "evaluation_input_invalid"
        evaluation_run.error_message = message
        db_session.commit()
        db_session.refresh(evaluation_run)
        return evaluation_run
