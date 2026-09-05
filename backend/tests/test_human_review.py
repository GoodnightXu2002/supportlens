from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.judge_contract import JudgeOutput
from app.main import app, get_db_session
from app.models import (
    Conversation,
    Dataset,
    EvaluationResult,
    EvaluationRun,
    HumanDecision,
)


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'human-review-api.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)

    def override_db_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def _machine_output(*, review_required: bool) -> dict[str, object]:
    if not review_required:
        return JudgeOutput.model_validate(
            {
                "judgment": "success",
                "primary_failure_mode": None,
                "secondary_flags": [],
                "problem": None,
                "severity": None,
                "evidence": [],
                "uncertainty": None,
                "review_required": False,
                "rationale": "The response satisfies the supplied reference.",
            }
        ).model_dump(mode="json")
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": "incorrect_information",
            "secondary_flags": [],
            "problem": "The response applies the wrong refund rule.",
            "severity": "high",
            "evidence": [
                {
                    "evidence_type": "response",
                    "content": "The refund is immediate.",
                    "source_ref": "assistant_response",
                }
            ],
            "uncertainty": None,
            "review_required": True,
            "rationale": "The response conflicts with the refund reference.",
        }
    ).model_dump(mode="json")


def _persist_run_with_results(
    engine,
    cases: list[tuple[str, bool]],
) -> tuple[UUID, dict[str, UUID]]:
    with Session(engine) as session:
        dataset = Dataset(
            name=f"Human review dataset {uuid4()}",
            source="user_upload",
            privacy_status="unknown",
        )
        evaluation_run = EvaluationRun(
            dataset=dataset,
            run_type="baseline",
            status="completed",
            judge_model="test-judge",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key=f"human-review:{uuid4()}",
        )
        result_ids: dict[str, UUID] = {}
        for case_id, review_required in cases:
            conversation = Conversation(
                dataset=dataset,
                external_id=case_id,
                messages=[
                    {"role": "user", "content": "When is my refund?"},
                    {"role": "assistant", "content": "The refund is immediate."},
                ],
            )
            result = EvaluationResult(
                evaluation_run=evaluation_run,
                conversation=conversation,
                raw_judge_output={"provider": "machine", "case_id": case_id},
                **_machine_output(review_required=review_required),
            )
            session.add(result)
            session.flush()
            result_ids[case_id] = result.id
        session.commit()
        return evaluation_run.id, result_ids


def _corrected_output() -> dict[str, object]:
    payload = deepcopy(_machine_output(review_required=True))
    payload["problem"] = "The response omits the expected refund timing caveat."
    payload["severity"] = "medium"
    payload["rationale"] = "Human review found a recoverable timing error."
    return payload


def _submit_review(
    client: TestClient,
    result_id: UUID,
    *,
    action: str,
    final_result: dict[str, object] | None = None,
    change_reason: str | None = None,
):
    payload = {
        "reviewer": "reviewer@example.com",
        "action": action,
        "change_reason": change_reason,
    }
    if final_result is not None:
        payload["final_result"] = final_result
    return client.post(
        f"/api/evaluation-results/{result_id}/human-review",
        json=payload,
    )


def test_final_results_include_machine_final_and_pending_review(api_context) -> None:
    client, engine = api_context
    run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-FINAL", False), ("CASE-PENDING", True)],
    )

    response = client.get(
        f"/api/evaluation-runs/{run_id}/final-effective-results"
    )

    assert response.status_code == 200
    by_case = {item["case_id"]: item for item in response.json()}
    direct_final = by_case["CASE-FINAL"]
    assert direct_final == {
        "evaluation_result_id": str(result_ids["CASE-FINAL"]),
        "conversation_id": direct_final["conversation_id"],
        "case_id": "CASE-FINAL",
        "status": "final",
        "source": "machine",
        "final_result": _machine_output(review_required=False),
        "human_decision_id": None,
    }
    pending = by_case["CASE-PENDING"]
    assert pending["evaluation_result_id"] == str(result_ids["CASE-PENDING"])
    assert pending["status"] == "pending_review"
    assert pending["source"] is None
    assert pending["final_result"] is None
    assert pending["human_decision_id"] is None


def test_confirm_creates_human_final_equal_to_machine_result(api_context) -> None:
    client, engine = api_context
    run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-CONFIRM", True)],
    )
    result_id = result_ids["CASE-CONFIRM"]

    response = _submit_review(client, result_id, action="confirm")

    assert response.status_code == 201
    decision = response.json()
    assert decision["evaluation_result_id"] == str(result_id)
    assert decision["original_result"] == _machine_output(review_required=True)
    assert decision["final_result"] == decision["original_result"]
    assert decision["change_reason"] is None

    final_response = client.get(
        f"/api/evaluation-runs/{run_id}/final-effective-results"
    )
    effective = final_response.json()[0]
    assert effective["status"] == "final"
    assert effective["source"] == "human"
    assert effective["final_result"] == decision["final_result"]
    assert effective["human_decision_id"] == decision["id"]


def test_correct_changes_final_but_preserves_machine_and_raw_output(
    api_context,
) -> None:
    client, engine = api_context
    run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-CORRECT", True)],
    )
    result_id = result_ids["CASE-CORRECT"]
    original_payload = _machine_output(review_required=True)
    corrected_payload = _corrected_output()

    response = _submit_review(
        client,
        result_id,
        action="correct",
        final_result=corrected_payload,
        change_reason="The machine overstated the impact.",
    )

    assert response.status_code == 201
    decision = response.json()
    assert decision["original_result"] == original_payload
    assert decision["final_result"] == corrected_payload
    assert decision["change_reason"] == "The machine overstated the impact."

    with Session(engine) as session:
        machine = session.get(EvaluationResult, result_id)
        assert machine is not None
        assert {
            field: getattr(machine, field) for field in JudgeOutput.model_fields
        } == original_payload
        assert machine.raw_judge_output == {
            "provider": "machine",
            "case_id": "CASE-CORRECT",
        }

    effective = client.get(
        f"/api/evaluation-runs/{run_id}/final-effective-results"
    ).json()[0]
    assert effective["status"] == "final"
    assert effective["source"] == "human"
    assert effective["final_result"] == corrected_payload


def test_changed_result_requires_non_empty_reason(api_context) -> None:
    client, engine = api_context
    _run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-REASON", True)],
    )

    response = _submit_review(
        client,
        result_ids["CASE-REASON"],
        action="correct",
        final_result=_corrected_output(),
        change_reason="   ",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "human_review_change_reason_required"
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HumanDecision)) == 0


def test_invalid_final_result_is_rejected(api_context) -> None:
    client, engine = api_context
    _run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-INVALID", True)],
    )
    invalid_payload = _corrected_output()
    invalid_payload["severity"] = None

    response = _submit_review(
        client,
        result_ids["CASE-INVALID"],
        action="correct",
        final_result=invalid_payload,
        change_reason="Attempted correction.",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request_validation_failed"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HumanDecision)) == 0


def test_duplicate_review_uses_stable_error(api_context) -> None:
    client, engine = api_context
    _run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-DUPLICATE", True)],
    )
    result_id = result_ids["CASE-DUPLICATE"]
    assert _submit_review(client, result_id, action="confirm").status_code == 201

    duplicate = _submit_review(client, result_id, action="confirm")

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == (
        "human_review_already_completed"
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HumanDecision)) == 1


def test_final_result_listing_does_not_cross_runs_or_conversations(
    api_context,
) -> None:
    client, engine = api_context
    first_run_id, first_results = _persist_run_with_results(
        engine,
        [("RUN-A-CASE", True)],
    )
    second_run_id, second_results = _persist_run_with_results(
        engine,
        [("RUN-B-CASE", False)],
    )
    _submit_review(client, first_results["RUN-A-CASE"], action="confirm")

    first = client.get(
        f"/api/evaluation-runs/{first_run_id}/final-effective-results"
    ).json()
    second = client.get(
        f"/api/evaluation-runs/{second_run_id}/final-effective-results"
    ).json()

    assert [item["case_id"] for item in first] == ["RUN-A-CASE"]
    assert first[0]["evaluation_result_id"] == str(first_results["RUN-A-CASE"])
    assert [item["case_id"] for item in second] == ["RUN-B-CASE"]
    assert second[0]["evaluation_result_id"] == str(
        second_results["RUN-B-CASE"]
    )


def test_review_is_rejected_when_machine_result_does_not_require_it(
    api_context,
) -> None:
    client, engine = api_context
    _run_id, result_ids = _persist_run_with_results(
        engine,
        [("CASE-NO-REVIEW", False)],
    )

    response = _submit_review(
        client,
        result_ids["CASE-NO-REVIEW"],
        action="confirm",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "human_review_not_required"
