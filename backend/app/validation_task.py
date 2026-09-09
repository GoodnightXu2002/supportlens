from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.candidate_validation import (
    CandidateComparisonService,
    CandidateRunner,
    CandidateRunService,
)
from app.models import Conversation, EvaluationRun, OptimizationTarget, ValidationTask
from app.schemas import (
    CandidateResponseInput,
    CandidateRunCreateRequest,
    EvaluationRunStatus,
    EvaluationRunType,
    ValidationTaskCandidateStartRequest,
    ValidationTaskCasesResponse,
    ValidationTaskCreateResponse,
    ValidationTaskReadResponse,
    ValidationTaskStatus,
    ValidationTaskSubmitRequest,
    ValidationTaskSubmitResponse,
)

RUNNER_TOKEN_TTL = timedelta(minutes=30)
RUNNER_TOKEN_BYTES = 32


class ValidationTaskErrorCode(StrEnum):
    OPTIMIZATION_TARGET_NOT_FOUND = "optimization_target_not_found"
    VALIDATION_TASK_TARGET_NOT_FROZEN = "validation_task_target_not_frozen"
    VALIDATION_TASK_CASE_SCOPE_INVALID = "validation_task_case_scope_invalid"
    VALIDATION_TASK_NOT_FOUND = "validation_task_not_found"
    RUNNER_TOKEN_INVALID = "runner_token_invalid"
    RUNNER_TOKEN_EXPIRED = "runner_token_expired"
    VALIDATION_TASK_NOT_RUNNABLE = "validation_task_not_runnable"
    VALIDATION_TASK_NOT_SUBMITTABLE = "validation_task_not_submittable"
    VALIDATION_TASK_RESPONSE_DUPLICATE = "validation_task_response_duplicate"
    VALIDATION_TASK_RESPONSE_UNKNOWN = "validation_task_response_unknown"
    VALIDATION_TASK_RESPONSE_MISSING = "validation_task_response_missing"
    VALIDATION_TASK_RESPONSE_EMPTY = "validation_task_response_empty"
    VALIDATION_TASK_PERSISTENCE_FAILED = "validation_task_persistence_failed"
    VALIDATION_TASK_NOT_SUBMITTED = "validation_task_not_submitted"


class ValidationTaskError(RuntimeError):
    def __init__(self, code: ValidationTaskErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ValidationTaskService:
    def __init__(
        self,
        *,
        ttl: timedelta = RUNNER_TOKEN_TTL,
        clock: Clock = _utc_now,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Runner token TTL must be positive.")
        self._ttl = ttl
        self._clock = clock

    def create(
        self,
        target_id: UUID,
        db_session: Session,
    ) -> ValidationTaskCreateResponse:
        target = db_session.get(OptimizationTarget, target_id)
        if target is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.OPTIMIZATION_TARGET_NOT_FOUND,
                f"Optimization target '{target_id}' was not found.",
            )
        if target.status != "frozen":
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_TARGET_NOT_FROZEN,
                "Validation task creation requires a frozen optimization target.",
            )

        scopes = (
            ("target", list(target.target_case_ids)),
            ("regression", list(target.regression_case_ids)),
            ("challenge", list(target.challenge_case_ids)),
        )
        case_ids = [case_id for _case_set, ids in scopes for case_id in ids]
        if len(case_ids) != len(set(case_ids)):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_CASE_SCOPE_INVALID,
                "Frozen validation case scopes must be disjoint.",
            )
        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == target.baseline_run.dataset_id,
                    Conversation.external_id.in_(case_ids),
                )
            ).all()
        )
        by_case_id = {item.external_id: item for item in conversations}
        if set(by_case_id) != set(case_ids):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_CASE_SCOPE_INVALID,
                "Frozen validation scope contains an unknown baseline case.",
            )
        snapshot = [
            {
                "case_id": case_id,
                "set": case_set,
                "messages": by_case_id[case_id].messages,
            }
            for case_set, ids in scopes
            for case_id in ids
        ]
        now = self._now()
        runner_token = secrets.token_urlsafe(RUNNER_TOKEN_BYTES)
        task = ValidationTask(
            optimization_target_id=target.id,
            baseline_run_id=target.baseline_run_id,
            status=ValidationTaskStatus.PENDING.value,
            case_scope_snapshot=snapshot,
            candidate_responses=None,
            runner_token_hash=_token_hash(runner_token),
            runner_token_expires_at=now + self._ttl,
            submitted_at=None,
        )
        try:
            db_session.add(task)
            db_session.commit()
            db_session.refresh(task)
        except SQLAlchemyError as error:
            db_session.rollback()
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Validation task could not be saved.",
            ) from error
        return ValidationTaskCreateResponse(
            task_id=task.id,
            optimization_target_id=task.optimization_target_id,
            baseline_run_id=task.baseline_run_id,
            status=task.status,
            case_count=len(snapshot),
            runner_token=runner_token,
            runner_token_expires_at=task.runner_token_expires_at,
        )

    def get_status(
        self,
        task_id: UUID,
        db_session: Session,
    ) -> ValidationTaskReadResponse:
        task = db_session.get(ValidationTask, task_id)
        if task is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_FOUND,
                f"Validation task '{task_id}' was not found.",
            )
        return ValidationTaskReadResponse(
            task_id=task.id,
            target_id=task.optimization_target_id,
            status=task.status,
            created_at=task.created_at,
            submitted_at=task.submitted_at,
            candidate_run_id=task.candidate_run_id,
        )

    def start_candidate_validation(
        self,
        task_id: UUID,
        request: ValidationTaskCandidateStartRequest,
        db_session: Session,
        candidate_service: CandidateRunService,
        runner: CandidateRunner,
        comparison_service: CandidateComparisonService,
    ) -> EvaluationRun:
        task = db_session.get(ValidationTask, task_id)
        if task is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_FOUND,
                f"Validation task '{task_id}' was not found.",
            )
        if task.status != ValidationTaskStatus.SUBMITTED.value:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_SUBMITTED,
                "Candidate validation requires a submitted validation task.",
            )

        candidate = (
            db_session.get(EvaluationRun, task.candidate_run_id)
            if task.candidate_run_id is not None
            else None
        )
        if task.candidate_run_id is not None and candidate is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Validation task candidate run is unavailable.",
            )
        if candidate is not None and (
            candidate.run_type != EvaluationRunType.CANDIDATE.value
            or candidate.target_id != task.optimization_target_id
            or candidate.baseline_run_id != task.baseline_run_id
        ):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Validation task candidate lineage is invalid.",
            )
        if candidate is None:
            candidate = self._create_candidate_run(
                task,
                request,
                db_session,
                candidate_service,
            )

        if candidate.status == EvaluationRunStatus.PENDING.value:
            candidate = runner.execute(candidate.id, db_session)
        if candidate.status == EvaluationRunStatus.COMPLETED.value:
            comparison_service.generate(candidate.id, db_session)
            db_session.refresh(candidate)
        return candidate

    @staticmethod
    def _create_candidate_run(
        task: ValidationTask,
        request: ValidationTaskCandidateStartRequest,
        db_session: Session,
        candidate_service: CandidateRunService,
    ) -> EvaluationRun:
        target = db_session.get(OptimizationTarget, task.optimization_target_id)
        baseline = db_session.get(EvaluationRun, task.baseline_run_id)
        if (
            target is None
            or baseline is None
            or target.status != "frozen"
            or target.plan_hash is None
            or task.submitted_at is None
        ):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Submitted validation task lineage is unavailable.",
            )

        responses = task.candidate_responses or []
        case_ids = [item["case_id"] for item in task.case_scope_snapshot]
        conversations = list(
            db_session.scalars(
                select(Conversation).where(
                    Conversation.dataset_id == baseline.dataset_id,
                    Conversation.external_id.in_(case_ids),
                )
            ).all()
        )
        by_case_id = {item.external_id: item for item in conversations}
        response_by_case_id = {item["case_id"]: item for item in responses}
        if set(by_case_id) != set(case_ids) or set(response_by_case_id) != set(
            case_ids
        ):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_CASE_SCOPE_INVALID,
                "Submitted responses do not match the frozen validation scope.",
            )

        change_summary = request.change_summary or "No change summary provided."
        candidate_request = CandidateRunCreateRequest(
            baseline_run_id=baseline.id,
            target_id=target.id,
            plan_hash=target.plan_hash,
            candidate_label=request.candidate_label,
            candidate_change_summary=change_summary,
            source="local_runner",
            actual_change_summary=change_summary,
            actual_change_status="verified",
            generation_parity_status="verified",
            candidate_first_exposure_at=task.submitted_at,
            responses=[
                CandidateResponseInput(
                    conversation_id=by_case_id[case_id].id,
                    case_id=case_id,
                    assistant_content=response_by_case_id[case_id][
                        "assistant_content"
                    ],
                )
                for case_id in case_ids
            ],
        )
        candidate = candidate_service.create(
            candidate_request,
            db_session,
            commit=False,
        )
        claimed = db_session.execute(
            update(ValidationTask)
            .where(
                ValidationTask.id == task.id,
                ValidationTask.candidate_run_id.is_(None),
            )
            .values(candidate_run_id=candidate.id)
        )
        if claimed.rowcount == 1:
            db_session.commit()
            db_session.refresh(candidate)
            return candidate

        db_session.rollback()
        existing_id = db_session.scalar(
            select(ValidationTask.candidate_run_id).where(
                ValidationTask.id == task.id
            )
        )
        existing = (
            db_session.get(EvaluationRun, existing_id)
            if existing_id is not None
            else None
        )
        if existing is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Candidate run could not be linked to the validation task.",
            )
        return existing

    def get_cases(
        self,
        task_id: UUID,
        authorization: str | None,
        db_session: Session,
    ) -> ValidationTaskCasesResponse:
        task = self._authorize(task_id, authorization, db_session)
        if task.status == ValidationTaskStatus.FAILED.value:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_RUNNABLE,
                "Failed validation tasks cannot be run.",
            )
        if task.status == ValidationTaskStatus.PENDING.value:
            task.status = ValidationTaskStatus.RUNNING.value
            try:
                db_session.commit()
                db_session.refresh(task)
            except SQLAlchemyError as error:
                db_session.rollback()
                raise ValidationTaskError(
                    ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                    "Validation task state could not be saved.",
                ) from error
        return ValidationTaskCasesResponse(
            task_id=task.id,
            status=task.status,
            cases=task.case_scope_snapshot,
        )

    def submit(
        self,
        task_id: UUID,
        authorization: str | None,
        request: ValidationTaskSubmitRequest,
        db_session: Session,
    ) -> ValidationTaskSubmitResponse:
        task = self._authorize(task_id, authorization, db_session)
        if task.status not in {
            ValidationTaskStatus.PENDING.value,
            ValidationTaskStatus.RUNNING.value,
        }:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_SUBMITTABLE,
                "Validation task no longer accepts candidate responses.",
            )

        responses = [item.model_dump() for item in request.responses]
        response_ids = [item["case_id"] for item in responses]
        if len(response_ids) != len(set(response_ids)):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_DUPLICATE,
                "Each frozen case may be submitted only once.",
            )
        if any(not item["assistant_content"].strip() for item in responses):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_EMPTY,
                "Candidate assistant_content must not be empty.",
            )
        required_ids = [item["case_id"] for item in task.case_scope_snapshot]
        unknown_ids = set(response_ids) - set(required_ids)
        if unknown_ids:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_UNKNOWN,
                "Candidate responses contain a case outside the frozen scope.",
            )
        if set(response_ids) != set(required_ids):
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_RESPONSE_MISSING,
                "Candidate responses must include every frozen case.",
            )

        response_by_id = {item["case_id"]: item for item in responses}
        ordered_responses = [response_by_id[case_id] for case_id in required_ids]
        submitted_at = self._now()
        try:
            result = db_session.execute(
                update(ValidationTask)
                .where(
                    ValidationTask.id == task.id,
                    ValidationTask.status.in_(
                        [
                            ValidationTaskStatus.PENDING.value,
                            ValidationTaskStatus.RUNNING.value,
                        ]
                    ),
                )
                .values(
                    candidate_responses=ordered_responses,
                    status=ValidationTaskStatus.SUBMITTED.value,
                    submitted_at=submitted_at,
                )
            )
            if result.rowcount != 1:
                db_session.rollback()
                raise ValidationTaskError(
                    ValidationTaskErrorCode.VALIDATION_TASK_NOT_SUBMITTABLE,
                    "Validation task no longer accepts candidate responses.",
                )
            db_session.commit()
        except SQLAlchemyError as error:
            db_session.rollback()
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_PERSISTENCE_FAILED,
                "Candidate responses could not be saved.",
            ) from error
        return ValidationTaskSubmitResponse(
            task_id=task.id,
            status=ValidationTaskStatus.SUBMITTED,
            response_count=len(ordered_responses),
            submitted_at=submitted_at,
        )

    def _authorize(
        self,
        task_id: UUID,
        authorization: str | None,
        db_session: Session,
    ) -> ValidationTask:
        task = db_session.get(ValidationTask, task_id)
        if task is None:
            raise ValidationTaskError(
                ValidationTaskErrorCode.VALIDATION_TASK_NOT_FOUND,
                f"Validation task '{task_id}' was not found.",
            )
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization is not None and authorization.startswith(prefix)
            else ""
        )
        if not token or not secrets.compare_digest(
            _token_hash(token), task.runner_token_hash
        ):
            raise ValidationTaskError(
                ValidationTaskErrorCode.RUNNER_TOKEN_INVALID,
                "Runner token is invalid for this validation task.",
            )
        if self._now() >= _as_utc(task.runner_token_expires_at):
            raise ValidationTaskError(
                ValidationTaskErrorCode.RUNNER_TOKEN_EXPIRED,
                "Runner token has expired.",
            )
        return task

    def _now(self) -> datetime:
        return _as_utc(self._clock())


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
