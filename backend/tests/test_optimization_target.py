from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
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
    OptimizationTarget,
    Problem,
    ResultProblemLink,
)
from app.problem_aggregation import (
    PROBLEM_MAPPING_VERSION,
    build_problem_mapping_key,
)


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'optimization-target-api.db'}",
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


CREATE_PAYLOAD = {
    "definition": "Improve refund eligibility accuracy.",
    "inclusion_criteria": "Core cases affected by the selected refund problem.",
    "exclusion_criteria": "Unrelated logistics and product questions.",
    "expected_observable_change": "The selected problem no longer appears.",
    "hypothesis_statement": "Explicit eligibility checks may reduce the problem.",
    "hypothesis_evidence_refs": ["CASE-A", "CASE-B"],
    "change_surface": "Agent instruction",
    "planned_change": "Add an explicit eligibility check.",
    "guardrails": ["Do not change logistics behavior."],
    "protected_capabilities": ["Logistics"],
    "policy_version": "CANDIDATE-DECISION-POLICY-V1",
}


def _machine_output(
    *,
    failure_mode: str = "incorrect_information",
    review_required: bool = False,
    include_reference: bool = True,
) -> dict[str, object]:
    evidence = []
    if include_reference:
        evidence.append(
            {
                "evidence_type": "reference",
                "content": "Refund eligibility depends on the frozen reference rule.",
                "source_ref": "NOVAMART-RULES-V1#REF-002",
            }
        )
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": failure_mode,
            "secondary_flags": [],
            "problem": "The assistant gives incorrect refund eligibility terms.",
            "severity": "medium",
            "evidence": evidence,
            "uncertainty": None,
            "review_required": review_required,
            "rationale": "The answer conflicts with the reference.",
        }
    ).model_dump(mode="json")


def _seed_run(
    engine,
    *,
    run_type: str = "baseline",
    status: str = "completed",
    aggregation_completed: bool = True,
) -> dict[str, UUID]:
    with Session(engine) as session:
        dataset = Dataset(
            name=f"Optimization target dataset {uuid4()}",
            source="user_upload",
            privacy_status="unknown",
        )
        run = EvaluationRun(
            dataset=dataset,
            run_type=run_type,
            status=status,
            judge_model="test-judge",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key=f"optimization-target:{uuid4()}",
            business_reference_snapshot="Frozen business reference.",
            problem_aggregation_completed_at=(
                datetime.now(UTC) if aggregation_completed else None
            ),
        )
        case_specs = [
            ("CASE-A", "core", True),
            ("CASE-B", "core", True),
            ("CASE-C", "core", False),
            ("CASE-D", "challenge", False),
        ]
        results: dict[str, EvaluationResult] = {}
        for case_id, case_set, _affected in case_specs:
            conversation = Conversation(
                dataset=dataset,
                external_id=case_id,
                messages=[
                    {"role": "user", "content": "Can I return this item?"},
                    {"role": "assistant", "content": "It is always eligible."},
                ],
                metadata_={
                    "scenario": "Refund",
                    "business_context": f"Context for {case_id}.",
                    "reference_evidence": "Frozen refund reference.",
                    "metadata": {"case_set": case_set},
                },
            )
            result = EvaluationResult(
                evaluation_run=run,
                conversation=conversation,
                raw_judge_output={"case_id": case_id},
                **_machine_output(),
            )
            session.add(result)
            results[case_id] = result

        problem_definition = (
            "The assistant gives incorrect refund eligibility terms."
        )
        problem = Problem(
            evaluation_run=run,
            scenario="Refund",
            definition=problem_definition,
            mapping_key=build_problem_mapping_key(
                "Refund",
                problem_definition,
            ),
            mapping_version=PROBLEM_MAPPING_VERSION,
        )
        session.add(problem)
        session.flush()
        for case_id in ("CASE-A", "CASE-B"):
            session.add(
                ResultProblemLink(
                    problem=problem,
                    evaluation_result=results[case_id],
                    role="primary",
                )
            )
        session.commit()
        return {
            "run_id": run.id,
            "problem_id": problem.id,
            "result_id": results["CASE-A"].id,
            "pending_result_id": results["CASE-D"].id,
        }


def _create(client: TestClient, ids: dict[str, UUID], payload=None):
    return client.post(
        "/api/evaluation-runs/"
        f"{ids['run_id']}/problems/{ids['problem_id']}/optimization-targets",
        json=payload or CREATE_PAYLOAD,
    )


def test_create_derives_case_sets_metric_snapshot_and_lineage(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)

    response = _create(client, ids)

    assert response.status_code == 201
    body = response.json()
    assert body["baseline_run_id"] == str(ids["run_id"])
    assert body["problem_id"] == str(ids["problem_id"])
    assert body["version"] == 1
    assert body["status"] == "draft"
    assert body["change_status"] == "planned"
    assert body["confirmed_by"] is None
    assert body["confirmed_at"] is None
    assert body["baseline_affected_case_ids"] == ["CASE-A", "CASE-B"]
    assert body["target_case_ids"] == ["CASE-A", "CASE-B"]
    assert body["regression_case_ids"] == ["CASE-C"]
    assert body["challenge_case_ids"] == ["CASE-D"]
    assert body["baseline_metric"] == {
        "affected_core_cases": 2,
        "core_denominator": 3,
        "frequency": {"numerator": 2, "denominator": 3},
    }
    assert body["failure_mode"] == "incorrect_information"
    assert {item["case_id"] for item in body["reference_basis"]} == {
        "CASE-A",
        "CASE-B",
    }
    assert all(
        item["evidence_type"] == "reference"
        for item in body["reference_basis"]
    )
    assert body["baseline_snapshot"] == {
        "problem_id": str(ids["problem_id"]),
        "definition": "The assistant gives incorrect refund eligibility terms.",
        "scenario": "Refund",
        "priority_severity": "medium",
        "business_impact": None,
        "frequency": {"numerator": 2, "denominator": 3},
        "pattern_consistency": "moderate",
        "evidence_confidence": None,
        "affected_case_ids": ["CASE-A", "CASE-B"],
    }
    assert body["evaluation_config_snapshot"] == {
        "baseline_run_id": str(ids["run_id"]),
        "dataset_id": body["evaluation_config_snapshot"]["dataset_id"],
        "judge_model": "test-judge",
        "judge_contract_version": "JUDGE-CONTRACT-V1",
        "run_source": "live",
        "response_set_key": body["evaluation_config_snapshot"]["response_set_key"],
        "business_reference_snapshot": "Frozen business reference.",
    }


def test_baseline_snapshot_is_stable_after_problem_changes(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    created = _create(client, ids).json()

    with Session(engine) as session:
        problem = session.get(Problem, ids["problem_id"])
        assert problem is not None
        problem.definition = "A later definition that must not change the snapshot."
        session.commit()

    loaded = client.get(f"/api/optimization-targets/{created['id']}")

    assert loaded.status_code == 200
    assert loaded.json()["baseline_snapshot"] == created["baseline_snapshot"]


def test_cross_run_problem_is_rejected(api_context) -> None:
    client, engine = api_context
    first = _seed_run(engine)
    second = _seed_run(engine)

    response = client.post(
        "/api/evaluation-runs/"
        f"{first['run_id']}/problems/{second['problem_id']}/optimization-targets",
        json=CREATE_PAYLOAD,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "optimization_target_problem_run_mismatch"
    )


def test_pending_review_is_rejected(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        result = session.get(EvaluationResult, ids["pending_result_id"])
        assert result is not None
        result.review_required = True
        session.commit()

    response = _create(client, ids)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "optimization_target_pending_review"
    )


def test_aggregation_not_completed_is_rejected(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine, aggregation_completed=False)

    response = _create(client, ids)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "optimization_target_aggregation_not_completed"
    )


def test_problem_without_affected_cases_is_rejected(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        links = session.scalars(
            select(ResultProblemLink).where(
                ResultProblemLink.problem_id == ids["problem_id"]
            )
        ).all()
        for link in links:
            session.delete(link)
        session.commit()

    response = _create(client, ids)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "optimization_target_problem_has_no_affected_cases"
    )


@pytest.mark.parametrize(
    ("run_type", "status", "expected_code"),
    [
        ("candidate", "completed", "optimization_target_run_not_baseline"),
        ("baseline", "running", "optimization_target_run_not_completed"),
    ],
)
def test_run_preconditions_are_enforced(
    api_context,
    run_type: str,
    status: str,
    expected_code: str,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine, run_type=run_type, status=status)

    response = _create(client, ids)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code


def test_duplicate_target_is_rejected_without_overwrite(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    first = _create(client, ids)

    second_payload = deepcopy(CREATE_PAYLOAD)
    second_payload["definition"] = "A replacement must not overwrite history."
    second = _create(client, ids, second_payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "optimization_target_already_exists"
    with Session(engine) as session:
        targets = session.scalars(select(OptimizationTarget)).all()
        assert len(targets) == 1
        assert targets[0].definition == CREATE_PAYLOAD["definition"]


def test_system_derived_fields_are_forbidden_in_create_request(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    payload = {**CREATE_PAYLOAD, "version": 9, "baseline_metric": {}}

    response = _create(client, ids, payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request_validation_failed"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OptimizationTarget)) == 0


def test_failure_mode_must_be_unique_and_traceable(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        result = session.scalar(
            select(EvaluationResult)
            .join(Conversation)
            .where(Conversation.external_id == "CASE-B")
        )
        assert result is not None
        result.primary_failure_mode = "other"
        session.commit()

    response = _create(client, ids)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "optimization_target_failure_mode_not_unique"
    )


def test_failure_mode_uses_human_corrected_final_result(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        result = session.scalar(
            select(EvaluationResult)
            .join(Conversation)
            .where(Conversation.external_id == "CASE-B")
        )
        assert result is not None
        result.primary_failure_mode = "other"
        result.review_required = True
        original_result = {
            field: deepcopy(getattr(result, field))
            for field in JudgeOutput.model_fields
        }
        final_result = deepcopy(original_result)
        final_result["primary_failure_mode"] = "incorrect_information"
        session.add(
            HumanDecision(
                evaluation_result=result,
                reviewer="reviewer@example.com",
                original_result=original_result,
                final_result=final_result,
                change_reason="Correct the traceable failure mode.",
            )
        )
        session.commit()

    response = _create(client, ids)

    assert response.status_code == 201
    assert response.json()["failure_mode"] == "incorrect_information"
    with Session(engine) as session:
        result = session.scalar(
            select(EvaluationResult)
            .join(Conversation)
            .where(Conversation.external_id == "CASE-B")
        )
        assert result is not None
        assert result.primary_failure_mode == "other"


def test_reference_basis_does_not_invent_missing_reference_evidence(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        results = session.scalars(
            select(EvaluationResult)
            .join(ResultProblemLink)
            .where(ResultProblemLink.problem_id == ids["problem_id"])
        ).all()
        for result in results:
            result.evidence = []
        session.commit()

    response = _create(client, ids)

    assert response.status_code == 201
    assert response.json()["reference_basis"] == []


def test_get_by_id_and_list_by_run_return_complete_draft(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    created = _create(client, ids)
    assert created.status_code == 201
    body = created.json()

    by_id = client.get(f"/api/optimization-targets/{body['id']}")
    by_run = client.get(
        f"/api/evaluation-runs/{ids['run_id']}/optimization-targets"
    )

    assert by_id.status_code == 200
    assert by_id.json() == body
    assert by_run.status_code == 200
    assert by_run.json() == [body]


def test_creation_does_not_modify_run_problem_or_result(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        run = session.get(EvaluationRun, ids["run_id"])
        problem = session.get(Problem, ids["problem_id"])
        result = session.get(EvaluationResult, ids["result_id"])
        assert run is not None and problem is not None and result is not None
        before = {
            "run": (run.status, run.problem_aggregation_completed_at),
            "problem": (problem.definition, problem.mapping_key),
            "result": (
                result.judgment,
                result.primary_failure_mode,
                deepcopy(result.evidence),
            ),
        }

    assert _create(client, ids).status_code == 201

    with Session(engine) as session:
        run = session.get(EvaluationRun, ids["run_id"])
        problem = session.get(Problem, ids["problem_id"])
        result = session.get(EvaluationResult, ids["result_id"])
        assert run is not None and problem is not None and result is not None
        assert (run.status, run.problem_aggregation_completed_at) == before["run"]
        assert (problem.definition, problem.mapping_key) == before["problem"]
        assert (
            result.judgment,
            result.primary_failure_mode,
            result.evidence,
        ) == before["result"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 0),
        ("status", "frozen"),
        ("change_status", "applied"),
        ("confirmed_by", "reviewer@example.com"),
    ],
)
def test_database_rejects_invalid_target_state(
    api_context,
    field: str,
    value: object,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    created = _create(client, ids)
    assert created.status_code == 201

    with Session(engine) as session:
        target = session.get(OptimizationTarget, UUID(created.json()["id"]))
        assert target is not None
        setattr(target, field, value)
        with pytest.raises(IntegrityError):
            session.commit()
