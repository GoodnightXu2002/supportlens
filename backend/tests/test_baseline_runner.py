import json
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.baseline_runner import (
    BaselineRunner,
    BaselineRunnerError,
    BaselineRunnerErrorCode,
)
from app.database import Base
from app.llm_provider import (
    LLMProviderError,
    LLMProviderErrorCode,
    LLMRequest,
    LLMResponse,
)
from app.models import Conversation, Dataset, EvaluationResult, EvaluationRun


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'baseline-runner.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _payload(judgment: str = "success") -> dict:
    is_failure = judgment == "failure"
    return {
        "judgment": judgment,
        "primary_failure_mode": "other" if is_failure else None,
        "secondary_flags": [],
        "problem": "A quality failure." if is_failure else None,
        "severity": "low" if is_failure else None,
        "evidence": [],
        "uncertainty": None,
        "review_required": False,
        "rationale": "Concise evidence-grounded judgment.",
    }


def _response(payload: dict, request_id: str) -> LLMResponse:
    return LLMResponse(
        provider="fake",
        model="fake-judge-v1",
        structured_payload=payload,
        raw_json_text=json.dumps(payload),
        request_id=request_id,
        token_usage={"total_tokens": 10},
    )


class ScriptedProvider:
    model = "fake-judge-v1"

    def __init__(self, outcomes: list[LLMResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self.outcomes[len(self.requests) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _final_provider_error() -> LLMProviderError:
    return LLMProviderError(
        LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR,
        "fake provider failure",
        retryable=False,
    )


def _persist_run(
    engine,
    *,
    conversation_count: int = 2,
    run_type: str = "baseline",
    status: str = "pending",
    business_reference_snapshot: str | None = "Frozen business reference.",
) -> UUID:
    with Session(engine) as session:
        dataset = Dataset(
            name="Baseline runner dataset",
            source="user_upload",
            privacy_status="unknown",
        )
        for index in range(conversation_count):
            dataset.conversations.append(
                Conversation(
                    external_id=f"CASE-{index + 1:03d}",
                    messages=[
                        {"role": "user", "content": f"Question {index + 1}"},
                        {
                            "role": "assistant",
                            "content": f"Answer {index + 1}",
                        },
                    ],
                    metadata_={"scenario": "Test scenario"},
                )
            )
        evaluation_run = EvaluationRun(
            dataset=dataset,
            run_type=run_type,
            status=status,
            judge_model="fake-judge-v1",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key="dataset:test:conversations",
            business_reference_snapshot=business_reference_snapshot,
        )
        session.add(evaluation_run)
        session.commit()
        return evaluation_run.id


def test_all_cases_succeed_and_raw_outputs_are_persisted(database_engine) -> None:
    run_id = _persist_run(database_engine)
    first_payload = _payload()
    second_payload = _payload("warning")
    provider = ScriptedProvider(
        [
            _response(first_payload, "response-1"),
            _response(second_payload, "response-2"),
        ]
    )
    original_complete = provider.complete

    def complete_while_run_is_running(request: LLMRequest) -> LLMResponse:
        with Session(database_engine) as status_session:
            stored_run = status_session.get(EvaluationRun, run_id)
            assert stored_run is not None
            assert stored_run.status == "running"
        return original_complete(request)

    provider.complete = complete_while_run_is_running  # type: ignore[method-assign]

    with Session(database_engine) as session:
        completed_run = BaselineRunner(provider).execute(run_id, session)

        assert completed_run.status == "completed"
        assert completed_run.case_errors == []
        results = session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == run_id)
            .order_by(EvaluationResult.conversation_id)
        ).all()

    assert len(provider.requests) == 2
    assert len(results) == 2
    assert {json.dumps(result.raw_judge_output) for result in results} == {
        json.dumps(first_payload),
        json.dumps(second_payload),
    }


def test_partial_failure_persists_success_and_failed_case(database_engine) -> None:
    run_id = _persist_run(database_engine)
    invalid_payload = {"judgment": "failure"}
    provider = ScriptedProvider(
        [
            _response(_payload(), "response-1"),
            _response(invalid_payload, "invalid-1"),
            _response(invalid_payload, "invalid-2"),
        ]
    )

    with Session(database_engine) as session:
        partial_run = BaselineRunner(provider).execute(run_id, session)
        results = session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id == run_id
            )
        ).all()

    assert partial_run.status == "partial_failure"
    assert len(results) == 1
    assert len(partial_run.case_errors) == 1
    case_error = partial_run.case_errors[0]
    assert set(case_error) == {
        "conversation_id",
        "case_id",
        "error_code",
        "error_message",
        "raw_judge_output",
    }
    assert UUID(case_error["conversation_id"])
    assert case_error["case_id"] == "CASE-002"
    assert case_error["error_code"] == "judge_output_invalid"
    assert case_error["error_message"] == (
        "Judge execution failed after 2 attempt(s)."
    )
    assert case_error["raw_judge_output"] == invalid_payload


def test_all_cases_fail_with_no_usable_results(database_engine) -> None:
    run_id = _persist_run(database_engine)
    provider = ScriptedProvider([_final_provider_error(), _final_provider_error()])

    with Session(database_engine) as session:
        failed_run = BaselineRunner(provider).execute(run_id, session)
        results = session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id == run_id
            )
        ).all()

    assert failed_run.status == "failed"
    assert results == []
    assert [error["case_id"] for error in failed_run.case_errors] == [
        "CASE-001",
        "CASE-002",
    ]
    assert all(
        error["raw_judge_output"] is None for error in failed_run.case_errors
    )


def test_invalid_reference_snapshot_marks_run_invalid(database_engine) -> None:
    run_id = _persist_run(database_engine, business_reference_snapshot="   ")
    provider = ScriptedProvider([])

    with Session(database_engine) as session:
        invalid_run = BaselineRunner(provider).execute(run_id, session)

    assert invalid_run.status == "invalid"
    assert invalid_run.error_code == "evaluation_input_invalid"
    assert invalid_run.case_errors == []
    assert provider.requests == []


def test_retry_only_processes_failed_case_and_preserves_success(
    database_engine,
) -> None:
    run_id = _persist_run(database_engine)
    initial_provider = ScriptedProvider(
        [_response(_payload(), "response-1"), _final_provider_error()]
    )

    with Session(database_engine) as session:
        partial_run = BaselineRunner(initial_provider).execute(run_id, session)
        first_result = session.scalar(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id == run_id
            )
        )
        assert partial_run.status == "partial_failure"
        assert first_result is not None
        first_result_id = first_result.id
        first_raw_output = first_result.raw_judge_output

    retry_payload = _payload("failure")
    retry_provider = ScriptedProvider([_response(retry_payload, "retry-response")])
    with Session(database_engine) as session:
        completed_run = BaselineRunner(retry_provider).retry_failed_cases(
            run_id,
            session,
        )
        results = session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id == run_id
            )
        ).all()
        preserved_result = session.get(EvaluationResult, first_result_id)

    assert completed_run.status == "completed"
    assert completed_run.case_errors == []
    assert len(retry_provider.requests) == 1
    assert len(results) == 2
    assert preserved_result is not None
    assert preserved_result.raw_judge_output == first_raw_output


@pytest.mark.parametrize(
    "status",
    ["running", "completed", "partial_failure", "failed", "invalid"],
)
def test_full_execute_rejects_non_pending_runs(
    database_engine,
    status: str,
) -> None:
    run_id = _persist_run(database_engine, status=status)

    with Session(database_engine) as session:
        with pytest.raises(BaselineRunnerError) as exc_info:
            BaselineRunner(ScriptedProvider([])).execute(run_id, session)

    assert (
        exc_info.value.code
        is BaselineRunnerErrorCode.EVALUATION_RUN_NOT_STARTABLE
    )


@pytest.mark.parametrize(
    "status",
    ["pending", "running", "completed", "failed", "invalid"],
)
def test_retry_rejects_runs_that_are_not_partial_failures(
    database_engine,
    status: str,
) -> None:
    run_id = _persist_run(database_engine, status=status)

    with Session(database_engine) as session:
        with pytest.raises(BaselineRunnerError) as exc_info:
            BaselineRunner(ScriptedProvider([])).retry_failed_cases(
                run_id,
                session,
            )

    assert (
        exc_info.value.code
        is BaselineRunnerErrorCode.EVALUATION_RUN_NOT_STARTABLE
    )


def test_non_baseline_run_is_rejected(database_engine) -> None:
    run_id = _persist_run(database_engine, run_type="candidate")

    with Session(database_engine) as session:
        with pytest.raises(BaselineRunnerError) as exc_info:
            BaselineRunner(ScriptedProvider([])).execute(run_id, session)

    assert exc_info.value.code is BaselineRunnerErrorCode.EVALUATION_RUN_NOT_BASELINE
