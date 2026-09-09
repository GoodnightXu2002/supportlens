import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.candidate_validation import (
    CandidateComparisonService,
    CandidateRunner,
    CandidateRunService,
    CandidateValidationError,
    CandidateValidationErrorCode,
    _determine_movement,
    build_response_set_hash,
)
from app.database import Base
from app.judge_contract import JudgeOutput
from app.llm_provider import LLMRequest, LLMResponse
from app.main import app, get_candidate_runner, get_db_session
from app.models import (
    CaseComparison,
    Conversation,
    Dataset,
    EvaluationResult,
    EvaluationRun,
    HumanDecision,
    OptimizationTarget,
    Problem,
    ResultProblemLink,
    ValidationTask,
)
from app.problem_aggregation import build_problem_mapping_key
from app.schemas import (
    CandidateResponseInput,
    CandidateRunCreateRequest,
    CaseMovement,
    TargetProblemStatus,
)


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'candidate-validation.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _output(
    judgment: str,
    *,
    problem: str | None = None,
    severity: str | None = None,
    review_required: bool = False,
) -> dict:
    return {
        "judgment": judgment,
        "primary_failure_mode": "other" if judgment == "failure" else None,
        "secondary_flags": [],
        "problem": problem,
        "severity": severity,
        "evidence": [
            {
                "evidence_type": "response",
                "content": "Traceable assistant response evidence.",
                "source_ref": "assistant_response",
            }
        ],
        "uncertainty": "Needs review." if judgment == "uncertain" else None,
        "review_required": review_required,
        "rationale": "Traceable comparison rationale.",
    }


def _persist_foundation(engine, *, protected: list[str] | None = None) -> dict:
    frozen_at = datetime.now(UTC) - timedelta(hours=1)
    with Session(engine) as session:
        dataset = Dataset(
            name="Candidate dataset",
            source="user_upload",
            privacy_status="unknown",
        )
        cases = []
        for case_id, case_set in (
            ("CASE-001", "core"),
            ("CASE-002", "core"),
            ("CASE-003", "challenge"),
        ):
            conversation = Conversation(
                external_id=case_id,
                messages=[
                    {"role": "user", "content": f"Question {case_id}"},
                    {"role": "assistant", "content": f"Baseline {case_id}"},
                ],
                metadata_={
                    "scenario": "Refund",
                    "business_context": {"case": case_id},
                    "reference_evidence": {"policy": "Policy V1"},
                    "metadata": {"case_set": case_set},
                },
            )
            dataset.conversations.append(conversation)
            cases.append(conversation)
        baseline = EvaluationRun(
            dataset=dataset,
            run_type="baseline",
            status="completed",
            judge_model="fake-judge-v1",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key="dataset:baseline",
            business_reference_snapshot="Frozen business reference.",
        )
        session.add(baseline)
        session.flush()
        baseline_payloads = [
            _output("failure", problem="Target issue", severity="high"),
            _output("success"),
            _output("success"),
        ]
        baseline_results = []
        for conversation, payload in zip(cases, baseline_payloads, strict=True):
            result = EvaluationResult(
                evaluation_run_id=baseline.id,
                conversation_id=conversation.id,
                raw_judge_output=payload,
                **payload,
            )
            session.add(result)
            baseline_results.append(result)
        session.flush()
        target_mapping_key = build_problem_mapping_key("Refund", "Target issue")
        problem = Problem(
            evaluation_run_id=baseline.id,
            scenario="Refund",
            definition="Target issue",
            mapping_key=target_mapping_key,
            mapping_version="PRIMARY-PROBLEM-EXACT-V1",
        )
        session.add(problem)
        session.flush()
        session.add(
            ResultProblemLink(
                problem_id=problem.id,
                evaluation_result_id=baseline_results[0].id,
                role="primary",
            )
        )
        plan_hash = "a" * 64
        target = OptimizationTarget(
            baseline_run_id=baseline.id,
            problem_id=problem.id,
            version=1,
            status="frozen",
            definition="Improve target issue",
            inclusion_criteria="Target cases",
            exclusion_criteria="Non-target cases",
            baseline_affected_case_ids=["CASE-001"],
            reference_basis=[],
            failure_mode="other",
            baseline_metric={
                "affected_core_cases": 1,
                "core_denominator": 2,
                "frequency": {"numerator": 1, "denominator": 2},
            },
            expected_observable_change="Target disappears",
            confirmed_by="reviewer",
            confirmed_at=frozen_at - timedelta(minutes=2),
            hypothesis_confirmed_by="reviewer",
            hypothesis_confirmed_at=frozen_at - timedelta(minutes=1),
            hypothesis_statement="Change fixes issue",
            hypothesis_evidence_refs=[],
            change_surface="prompt",
            planned_change="Clarify instruction",
            guardrails=[],
            change_status="planned",
            target_case_ids=["CASE-001"],
            regression_case_ids=["CASE-002"],
            challenge_case_ids=["CASE-003"],
            protected_capabilities=protected or [],
            baseline_snapshot={"problem_id": str(problem.id)},
            evaluation_config_snapshot={"judge_contract_version": "JUDGE-CONTRACT-V1"},
            policy_version="CANDIDATE-VALIDATION-V1",
            plan_hash=plan_hash,
            frozen_by="reviewer",
            frozen_at=frozen_at,
        )
        session.add(target)
        session.commit()
        return {
            "baseline_id": baseline.id,
            "target_id": target.id,
            "problem_id": problem.id,
            "conversation_ids": [case.id for case in cases],
            "case_ids": [case.external_id for case in cases],
            "plan_hash": plan_hash,
            "frozen_at": frozen_at,
        }


def _request(foundation: dict, **updates) -> CandidateRunCreateRequest:
    data = {
        "baseline_run_id": foundation["baseline_id"],
        "target_id": foundation["target_id"],
        "plan_hash": foundation["plan_hash"],
        "candidate_label": "Candidate A",
        "candidate_change_summary": "Clarified response policy.",
        "source": "manual_upload",
        "actual_change_summary": "Applied the frozen prompt change.",
        "actual_change_status": "verified",
        "generation_parity_status": "verified",
        "candidate_first_exposure_at": foundation["frozen_at"] + timedelta(minutes=1),
        "responses": [
            {
                "conversation_id": conversation_id,
                "case_id": case_id,
                "assistant_content": f"Candidate response for {case_id}",
            }
            for conversation_id, case_id in zip(
                foundation["conversation_ids"],
                foundation["case_ids"],
                strict=True,
            )
        ],
    }
    data.update(updates)
    return CandidateRunCreateRequest.model_validate(data)


def _create_candidate(engine, foundation: dict) -> UUID:
    with Session(engine) as session:
        candidate = CandidateRunService().create(_request(foundation), session)
        return candidate.id


def _persist_candidate_results(
    engine,
    candidate_id: UUID,
    payloads: list[dict],
    *,
    human_confirm_indexes: set[int] | None = None,
) -> None:
    with Session(engine) as session:
        candidate = session.get(EvaluationRun, candidate_id)
        assert candidate is not None
        snapshots = candidate.candidate_responses_snapshot or []
        for index, (snapshot, payload) in enumerate(
            zip(snapshots, payloads, strict=True)
        ):
            result = EvaluationResult(
                evaluation_run_id=candidate.id,
                conversation_id=UUID(snapshot["conversation_id"]),
                raw_judge_output=payload,
                **payload,
            )
            session.add(result)
            session.flush()
            if human_confirm_indexes and index in human_confirm_indexes:
                session.add(
                    HumanDecision(
                        evaluation_result_id=result.id,
                        reviewer="human-reviewer",
                        original_result=payload,
                        final_result=payload,
                        change_reason=None,
                    )
                )
        candidate.status = "completed"
        session.commit()


class ScriptedProvider:
    model = "fake-judge-v1"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        payload = self.payloads[len(self.requests) - 1]
        return LLMResponse(
            provider="fake",
            model=self.model,
            structured_payload=payload,
            raw_json_text=json.dumps(payload),
        )


def test_candidate_creation_requires_frozen_plan_and_preserves_baseline(
    database_engine,
) -> None:
    foundation = _persist_foundation(database_engine)
    with Session(database_engine) as session:
        baseline = session.get(EvaluationRun, foundation["baseline_id"])
        target = session.get(OptimizationTarget, foundation["target_id"])
        assert baseline is not None and target is not None
        original_response_key = baseline.response_set_key
        target.status = "confirmed"
        target.plan_hash = None
        target.frozen_by = None
        target.frozen_at = None
        session.commit()
        with pytest.raises(CandidateValidationError) as exc_info:
            CandidateRunService().create(_request(foundation), session)
        assert exc_info.value.code is (
            CandidateValidationErrorCode.CANDIDATE_TARGET_NOT_FROZEN
        )
        target.status = "frozen"
        target.plan_hash = foundation["plan_hash"]
        target.frozen_by = "reviewer"
        target.frozen_at = foundation["frozen_at"]
        candidate = CandidateRunService().create(_request(foundation), session)
        assert candidate.dataset_id == baseline.dataset_id
        assert candidate.id != baseline.id
        assert baseline.response_set_key == original_response_key
        assert (
            session.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id == baseline.id)
            )
            == 3
        )


def test_creation_rejects_exposure_before_freeze(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    with Session(database_engine) as session:
        with pytest.raises(CandidateValidationError) as exc_info:
            CandidateRunService().create(
                _request(
                    foundation,
                    candidate_first_exposure_at=foundation["frozen_at"]
                    - timedelta(seconds=1),
                ),
                session,
            )
    assert exc_info.value.code is (
        CandidateValidationErrorCode.CANDIDATE_EXPOSURE_BEFORE_FREEZE
    )


@pytest.mark.parametrize("variant", ["missing", "duplicate", "wrong_pair"])
def test_creation_rejects_invalid_case_scope(database_engine, variant: str) -> None:
    foundation = _persist_foundation(database_engine)
    request = _request(foundation)
    responses = [item.model_dump(mode="json") for item in request.responses]
    if variant == "missing":
        responses.pop()
    elif variant == "duplicate":
        responses[-1] = dict(responses[0])
    else:
        responses[0]["conversation_id"] = responses[1]["conversation_id"]
    request = _request(
        foundation,
        responses=[CandidateResponseInput.model_validate(item) for item in responses],
    )
    with Session(database_engine) as session:
        with pytest.raises(CandidateValidationError):
            CandidateRunService().create(request, session)


def test_response_set_hash_is_deterministic_and_manifest_is_complete(
    database_engine,
) -> None:
    foundation = _persist_foundation(database_engine)
    request = _request(foundation)
    reversed_request = request.model_copy(update={"responses": request.responses[::-1]})
    expected = build_response_set_hash(
        [item.model_dump(mode="json") for item in request.responses]
    )
    assert expected == build_response_set_hash(
        [item.model_dump(mode="json") for item in reversed_request.responses]
    )
    with Session(database_engine) as session:
        candidate = CandidateRunService().create(reversed_request, session)
        assert candidate.response_set_hash == expected
        assert candidate.candidate_manifest_snapshot == {
            "plan_hash": foundation["plan_hash"],
            "actual_change_status": "verified",
            "actual_change_summary": "Applied the frozen prompt change.",
            "generation_parity_status": "verified",
            "candidate_first_exposure_at": (
                foundation["frozen_at"] + timedelta(minutes=1)
            ).isoformat(),
            "source": "manual_upload",
            "response_set_hash": expected,
            "case_count": 3,
        }


def test_candidate_runner_uses_candidate_content_and_separate_results(
    database_engine,
) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    provider = ScriptedProvider([_output("success")] * 3)
    with Session(database_engine) as session:
        candidate = CandidateRunner(provider).execute(candidate_id, session)
        candidate_results = session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id == candidate.id
            )
        ).all()
        baseline_count = session.scalar(
            select(func.count())
            .select_from(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == foundation["baseline_id"])
        )
    assert candidate.status == "completed"
    assert len(candidate_results) == 3
    assert baseline_count == 3
    assert all(
        "Candidate response for" in request.messages[-1].content
        for request in provider.requests
    )


def test_case_pairing_target_exact_identity_and_idempotency(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [
            _output("failure", problem="Target issue", severity="high"),
            _output("success"),
            _output("success"),
        ],
    )
    with Session(database_engine) as session:
        service = CandidateComparisonService()
        first, first_summary = service.generate(candidate_id, session)
        second, second_summary = service.generate(candidate_id, session)
        assert len(first) == len(second) == 3
        assert {item.id for item in first} == {item.id for item in second}
        assert first_summary == second_summary
        target_case = next(item for item in first if item.case_id == "CASE-001")
        assert target_case.target_problem_status.value == "present"
        assert target_case.movement.value == "stable"
        assert target_case.baseline_run_id == foundation["baseline_id"]
        assert target_case.candidate_run_id == candidate_id
        assert session.scalar(select(func.count()).select_from(CaseComparison)) == 3


def test_existing_comparisons_refresh_decisive_continue_verdict(
    database_engine,
) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [
            _output("failure", problem="New repeated issue", severity="medium"),
            _output("failure", problem="New repeated issue", severity="medium"),
            _output("success"),
        ],
    )
    with Session(database_engine) as session:
        service = CandidateComparisonService()
        comparisons, summary = service.generate(candidate_id, session)
        assert summary.recommended_verdict.value == "CONTINUE"
        comparison_ids = {item.id for item in comparisons}

        candidate = session.get(EvaluationRun, candidate_id)
        stale_summary = dict(candidate.candidate_validation_summary)
        stale_summary["recommended_verdict"] = "INCONCLUSIVE"
        candidate.candidate_validation_summary = stale_summary
        session.commit()

        refreshed, refreshed_summary = service.generate(candidate_id, session)
        assert {item.id for item in refreshed} == comparison_ids
        assert refreshed_summary.recommended_verdict.value == "CONTINUE"
        assert service.get_summary(candidate_id, session) == refreshed_summary
        assert session.scalar(select(func.count()).select_from(CaseComparison)) == 3


@pytest.mark.parametrize(
    ("baseline", "candidate", "target_status", "other", "expected"),
    [
        (
            _output("failure", severity="high"),
            _output("success"),
            "absent",
            False,
            "improved",
        ),
        (
            _output("failure", severity="high"),
            _output("failure", severity="medium"),
            "present",
            False,
            "partially_improved",
        ),
        (_output("success"), _output("success"), "not_applicable", False, "stable"),
        (
            _output("success"),
            _output("failure", severity="high"),
            "not_applicable",
            False,
            "regressed",
        ),
        (
            _output("failure", severity="high"),
            _output("warning"),
            "absent",
            True,
            "inconclusive",
        ),
    ],
)
def test_movement_five_state_key_paths(
    baseline: dict,
    candidate: dict,
    target_status: str,
    other: bool,
    expected: str,
) -> None:
    movement, _target_worse = _determine_movement(
        JudgeOutput.model_validate(baseline),
        JudgeOutput.model_validate(candidate),
        case_is_target=target_status != "not_applicable",
        target_status=TargetProblemStatus(target_status),
        candidate_has_other_problem=other,
    )
    assert movement is CaseMovement(expected)


@pytest.mark.parametrize(
    ("payload", "human_reviewed", "expected"),
    [
        (
            _output("failure", problem="Critical new", severity="critical"),
            False,
            "critical",
        ),
        (_output("failure", problem="Major new", severity="high"), False, "major"),
        (_output("warning", problem="Minor new", review_required=True), True, "minor"),
    ],
)
def test_regression_levels(
    database_engine,
    payload: dict,
    human_reviewed: bool,
    expected: str,
) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [_output("success"), payload, _output("success")],
        human_confirm_indexes={1} if human_reviewed else None,
    )
    with Session(database_engine) as session:
        comparisons, _ = CandidateComparisonService().generate(candidate_id, session)
    regression = next(item for item in comparisons if item.case_id == "CASE-002")
    assert regression.regression_level is not None
    assert regression.regression_level.value == expected


def test_new_systematic_problem_and_continue_verdict(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [
            _output("failure", problem="New repeated issue", severity="medium"),
            _output("failure", problem="New repeated issue", severity="medium"),
            _output("success"),
        ],
    )
    with Session(database_engine) as session:
        _, summary = CandidateComparisonService().generate(candidate_id, session)
    assert len(summary.new_systematic_problems) == 1
    assert summary.new_systematic_problems[0]["core_case_ids"] == [
        "CASE-001",
        "CASE-002",
    ]
    assert "case_comparison_inconclusive" in summary.blockers
    assert summary.recommended_verdict.value == "CONTINUE"


def test_protected_capability_unsupported_is_inconclusive(database_engine) -> None:
    foundation = _persist_foundation(database_engine, protected=["refund accuracy"])
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [_output("success"), _output("success"), _output("success")],
    )
    with Session(database_engine) as session:
        _, summary = CandidateComparisonService().generate(candidate_id, session)
    assert summary.protected_capability_gate == "unsupported"
    assert summary.recommended_verdict.value == "INCONCLUSIVE"


def test_pending_review_never_accepts(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [
            _output("success", review_required=True),
            _output("success"),
            _output("success"),
        ],
    )
    with Session(database_engine) as session:
        comparisons, summary = CandidateComparisonService().generate(
            candidate_id, session
        )
    assert comparisons[0].movement.value == "inconclusive"
    assert summary.review_complete is False
    assert summary.recommended_verdict.value == "INCONCLUSIVE"


@pytest.mark.parametrize(
    ("payloads", "expected"),
    [
        (
            [_output("success"), _output("success"), _output("success")],
            "ACCEPT",
        ),
        (
            [
                _output("failure", problem="Target issue", severity="high"),
                _output("success"),
                _output("success"),
            ],
            "CONTINUE",
        ),
        (
            [
                _output("success", review_required=True),
                _output("success"),
                _output("success"),
            ],
            "INCONCLUSIVE",
        ),
    ],
)
def test_recommended_verdict_key_paths_and_no_score(
    database_engine,
    payloads: list[dict],
    expected: str,
) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(database_engine, candidate_id, payloads)
    with Session(database_engine) as session:
        _, summary = CandidateComparisonService().generate(candidate_id, session)
        raw = session.get(EvaluationRun, candidate_id).candidate_validation_summary
    assert summary.recommended_verdict.value == expected
    assert "score" not in json.dumps(raw).lower()


def test_candidate_api_create_execute_compare_and_read(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    provider = ScriptedProvider([_output("success")] * 3)

    def override_db_session():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_candidate_runner] = lambda: CandidateRunner(provider)
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/evaluation-runs",
                json=_request(foundation).model_dump(mode="json"),
            )
            assert create_response.status_code == 201
            candidate_id = create_response.json()["id"]

            execute_response = client.post(
                f"/api/evaluation-runs/{candidate_id}/execute-candidate"
            )
            assert execute_response.status_code == 200
            assert execute_response.json()["status"] == "completed"

            comparison_response = client.post(
                f"/api/evaluation-runs/{candidate_id}/case-comparisons"
            )
            assert comparison_response.status_code == 201
            assert len(comparison_response.json()) == 3

            read_response = client.get(
                f"/api/evaluation-runs/{candidate_id}/case-comparisons"
            )
            summary_response = client.get(
                f"/api/evaluation-runs/{candidate_id}/candidate-validation-summary"
            )
            assert read_response.status_code == 200
            assert len(read_response.json()) == 3
            assert summary_response.status_code == 200
            assert summary_response.json()["recommended_verdict"] == "ACCEPT"
    finally:
        app.dependency_overrides.clear()


def test_submitted_validation_task_runs_candidate_validation_idempotently(
    database_engine,
) -> None:
    foundation = _persist_foundation(database_engine)
    with Session(database_engine) as session:
        target = session.get(OptimizationTarget, foundation["target_id"])
        baseline = session.get(EvaluationRun, foundation["baseline_id"])
        assert target is not None
        assert baseline is not None
        second_problem = Problem(
            evaluation_run_id=baseline.id,
            scenario="Refund",
            definition="Second target issue",
            mapping_key=build_problem_mapping_key("Refund", "Second target issue"),
            mapping_version="PRIMARY-PROBLEM-EXACT-V1",
        )
        session.add(second_problem)
        session.flush()
        target.problem_ids = [str(target.problem_id), str(second_problem.id)]
        target.problem_set_key = hashlib.sha256(
            "|".join(sorted(target.problem_ids)).encode()
        ).hexdigest()
        target.target_case_ids = ["CASE-001", "CASE-002"]
        target.regression_case_ids = []
        target.baseline_affected_case_ids = ["CASE-001", "CASE-002"]
        baseline_before = (
            baseline.status,
            baseline.response_set_key,
            session.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id == baseline.id)
            ),
        )
        session.commit()

    provider = ScriptedProvider([_output("success")] * 3)

    def override_db_session():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_candidate_runner] = lambda: CandidateRunner(provider)
    try:
        with TestClient(app) as client:
            pending = client.post(
                f"/api/optimization-targets/{foundation['target_id']}/validation-tasks"
            ).json()
            rejected = client.post(
                f"/api/validation-tasks/{pending['task_id']}/candidate-validation",
                json={"candidate_label": "Candidate A", "change_summary": None},
            )
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == (
                "validation_task_not_submitted"
            )

            task = client.post(
                f"/api/optimization-targets/{foundation['target_id']}/validation-tasks"
            ).json()
            responses = [
                {
                    "case_id": case_id,
                    "assistant_content": f"Candidate response for {case_id}",
                }
                for case_id in ("CASE-001", "CASE-002", "CASE-003")
            ]
            submitted = client.post(
                f"/api/validation-tasks/{task['task_id']}/responses",
                headers={"Authorization": f"Bearer {task['runner_token']}"},
                json={"responses": responses},
            )
            assert submitted.status_code == 200

            start_url = (
                f"/api/validation-tasks/{task['task_id']}/candidate-validation"
            )
            start_payload = {
                "candidate_label": "Candidate from runner",
                "change_summary": "Prompt update",
            }
            first = client.post(start_url, json=start_payload)
            second = client.post(start_url, json=start_payload)
            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json()["id"] == first.json()["id"]
            assert first.json()["status"] == "completed"
            assert first.json()["target_id"] == str(foundation["target_id"])
            assert first.json()["baseline_run_id"] == str(foundation["baseline_id"])
            assert first.json()["candidate_label"] == "Candidate from runner"
            assert first.json()["candidate_change_summary"] == "Prompt update"
            response_snapshot = first.json()["candidate_responses_snapshot"]
            assert len(response_snapshot) == 3
            assert first.json()["response_set_hash"] == build_response_set_hash(
                response_snapshot
            )
            assert len(provider.requests) == 3

            status = client.get(
                f"/api/validation-tasks/{task['task_id']}"
            ).json()
            assert status["candidate_run_id"] == first.json()["id"]
            comparisons = client.get(
                f"/api/evaluation-runs/{first.json()['id']}/case-comparisons"
            )
            summary = client.get(
                f"/api/evaluation-runs/{first.json()['id']}/candidate-validation-summary"
            )
            assert comparisons.status_code == 200
            assert len(comparisons.json()) == 3
            assert summary.status_code == 200
            assert summary.json()["recommended_verdict"] in {
                "ACCEPT",
                "CONTINUE",
                "INCONCLUSIVE",
            }

        with Session(database_engine) as session:
            baseline = session.get(EvaluationRun, foundation["baseline_id"])
            assert baseline is not None
            assert (
                baseline.status,
                baseline.response_set_key,
                session.scalar(
                    select(func.count())
                    .select_from(EvaluationResult)
                    .where(EvaluationResult.evaluation_run_id == baseline.id)
                ),
            ) == baseline_before
            assert session.scalar(
                select(func.count())
                .select_from(EvaluationRun)
                .where(
                    EvaluationRun.run_type == "candidate",
                    EvaluationRun.target_id == foundation["target_id"],
                )
            ) == 1
    finally:
        app.dependency_overrides.clear()


def test_validation_task_candidate_link_migration_round_trip(database_engine) -> None:
    from pathlib import Path
    from runpy import run_path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    foundation = _persist_foundation(database_engine)
    with Session(database_engine) as session:
        task = ValidationTask(
            optimization_target_id=foundation["target_id"],
            baseline_run_id=foundation["baseline_id"],
            status="pending",
            case_scope_snapshot=[],
            candidate_responses=None,
            runner_token_hash="a" * 64,
            runner_token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(task)
        session.commit()
        task_id = task.id

    migration = run_path(
        str(
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "b3c4d5e6f7a8_link_validation_tasks_to_candidate_runs.py"
        )
    )
    with database_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with connection.begin():
            with Operations.context(MigrationContext.configure(connection)):
                migration["downgrade"]()
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(validation_tasks)"
                    )
                }
                assert "candidate_run_id" not in columns
                migration["upgrade"]()
        row = connection.exec_driver_sql(
            "SELECT candidate_run_id FROM validation_tasks WHERE id = ?",
            (task_id.hex,),
        ).one()
        assert row[0] is None
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_human_final_decision_persists_and_is_immutable(database_engine) -> None:
    foundation = _persist_foundation(database_engine)
    candidate_id = _create_candidate(database_engine, foundation)
    _persist_candidate_results(
        database_engine,
        candidate_id,
        [_output("success"), _output("success"), _output("success")],
    )
    with Session(database_engine) as session:
        CandidateComparisonService().generate(candidate_id, session)

    def override_db_session():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/evaluation-runs/{candidate_id}/final-decision",
                json={
                    "final_decision": "accept",
                    "decided_by": "decision-owner",
                    "reason": "All Accept gates passed.",
                    "override_reason": None,
                },
            )
            assert response.status_code == 200
            assert response.json()["final_decision"] == "accept"
            assert response.json()["decided_at"] is not None

            loaded = client.get(f"/api/evaluation-runs/{candidate_id}")
            assert loaded.json()["decided_by"] == "decision-owner"
            assert loaded.json()["reason"] == "All Accept gates passed."

            duplicate = client.post(
                f"/api/evaluation-runs/{candidate_id}/final-decision",
                json={
                    "final_decision": "continue",
                    "decided_by": "other-owner",
                    "reason": "Try to overwrite.",
                    "override_reason": "Different from machine.",
                },
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["code"] == (
                "candidate_final_decision_already_completed"
            )
    finally:
        app.dependency_overrides.clear()


def test_human_final_decision_enforces_override_and_accept_gate(
    database_engine,
) -> None:
    accept_foundation = _persist_foundation(database_engine)
    accept_candidate_id = _create_candidate(database_engine, accept_foundation)
    _persist_candidate_results(
        database_engine,
        accept_candidate_id,
        [_output("success"), _output("success"), _output("success")],
    )
    continue_foundation = _persist_foundation(database_engine)
    continue_candidate_id = _create_candidate(database_engine, continue_foundation)
    _persist_candidate_results(
        database_engine,
        continue_candidate_id,
        [
            _output("failure", problem="Target issue", severity="high"),
            _output("success"),
            _output("success"),
        ],
    )
    with Session(database_engine) as session:
        service = CandidateComparisonService()
        service.generate(accept_candidate_id, session)
        service.generate(continue_candidate_id, session)

    def override_db_session():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as client:
            missing_override = client.post(
                f"/api/evaluation-runs/{accept_candidate_id}/final-decision",
                json={
                    "final_decision": "continue",
                    "decided_by": "decision-owner",
                    "reason": "Continue iterating.",
                },
            )
            assert missing_override.status_code == 409
            assert missing_override.json()["error"]["code"] == (
                "candidate_final_decision_override_reason_required"
            )

            overridden = client.post(
                f"/api/evaluation-runs/{accept_candidate_id}/final-decision",
                json={
                    "final_decision": "continue",
                    "decided_by": "decision-owner",
                    "reason": "Continue iterating.",
                    "override_reason": "Additional review is required.",
                },
            )
            assert overridden.status_code == 200
            assert overridden.json()["override_reason"] == (
                "Additional review is required."
            )

            blocked_accept = client.post(
                f"/api/evaluation-runs/{continue_candidate_id}/final-decision",
                json={
                    "final_decision": "accept",
                    "decided_by": "decision-owner",
                    "reason": "Attempt blocked Accept.",
                    "override_reason": "Disagree with machine.",
                },
            )
            assert blocked_accept.status_code == 409
            assert blocked_accept.json()["error"]["code"] == (
                "candidate_final_decision_accept_blocked"
            )
    finally:
        app.dependency_overrides.clear()
