import hashlib
import json
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


def _confirm_and_freeze(
    client: TestClient,
    target_id: str,
    *,
    actor: str = "owner@example.com",
):
    target_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-target",
        json={"actor": actor},
    )
    assert target_confirmation.status_code == 200
    hypothesis_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": actor},
    )
    assert hypothesis_confirmation.status_code == 200
    return client.post(
        f"/api/optimization-targets/{target_id}/freeze",
        json={"actor": actor},
    )


def _expected_plan_hash(body: dict[str, object]) -> str:
    payload = {
        "target_contract": {
            "definition": body["definition"],
            "inclusion_criteria": body["inclusion_criteria"],
            "exclusion_criteria": body["exclusion_criteria"],
            "baseline_affected_case_ids": body["baseline_affected_case_ids"],
            "reference_basis": body["reference_basis"],
            "failure_mode": body["failure_mode"],
            "baseline_metric": body["baseline_metric"],
            "expected_observable_change": body[
                "expected_observable_change"
            ],
        },
        "hypothesis": {
            "hypothesis_statement": body["hypothesis_statement"],
            "hypothesis_evidence_refs": body["hypothesis_evidence_refs"],
        },
        "planned_change": {
            "change_surface": body["change_surface"],
            "planned_change": body["planned_change"],
        },
        "guardrails": body["guardrails"],
        "target_case_ids": body["target_case_ids"],
        "regression_case_ids": body["regression_case_ids"],
        "challenge_case_ids": body["challenge_case_ids"],
        "protected_capabilities": body["protected_capabilities"],
        "baseline_snapshot": body["baseline_snapshot"],
        "evaluation_config_snapshot": body["evaluation_config_snapshot"],
        "policy_version": body["policy_version"],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    assert body["hypothesis_confirmed_by"] is None
    assert body["hypothesis_confirmed_at"] is None
    assert body["plan_hash"] is None
    assert body["frozen_by"] is None
    assert body["frozen_at"] is None
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
        ("status", "archived"),
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


def test_draft_can_patch_only_user_editable_fields(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    created = _create(client, ids).json()

    response = client.patch(
        f"/api/optimization-targets/{created['id']}",
        json={
            "definition": "Improve frozen-reference refund accuracy.",
            "hypothesis_statement": "A scoped rule reminder may help.",
            "guardrails": ["Preserve escalation behavior."],
            "protected_capabilities": ["Escalation"],
            "policy_version": "POLICY-V2",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["definition"] == "Improve frozen-reference refund accuracy."
    assert body["hypothesis_statement"] == "A scoped rule reminder may help."
    assert body["guardrails"] == ["Preserve escalation behavior."]
    assert body["protected_capabilities"] == ["Escalation"]
    assert body["policy_version"] == "POLICY-V2"
    assert body["baseline_run_id"] == created["baseline_run_id"]
    assert body["problem_id"] == created["problem_id"]
    assert body["target_case_ids"] == created["target_case_ids"]

    forbidden = client.patch(
        f"/api/optimization-targets/{created['id']}",
        json={"target_case_ids": ["CASE-D"], "version": 2},
    )
    assert forbidden.status_code == 400
    assert forbidden.json()["error"]["code"] == "request_validation_failed"


def test_target_and_hypothesis_are_confirmed_separately(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target_id = _create(client, ids).json()["id"]

    too_early = client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": "hypothesis-owner@example.com"},
    )
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == (
        "optimization_target_target_not_confirmed"
    )

    target_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-target",
        json={"actor": "target-owner@example.com"},
    )
    assert target_confirmation.status_code == 200
    target_body = target_confirmation.json()
    assert target_body["status"] == "confirmed"
    assert target_body["confirmed_by"] == "target-owner@example.com"
    assert target_body["confirmed_at"] is not None
    assert target_body["hypothesis_confirmed_by"] is None

    hypothesis_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": "hypothesis-owner@example.com"},
    )
    assert hypothesis_confirmation.status_code == 200
    hypothesis_body = hypothesis_confirmation.json()
    assert hypothesis_body["status"] == "confirmed"
    assert hypothesis_body["confirmed_by"] == "target-owner@example.com"
    assert (
        hypothesis_body["hypothesis_confirmed_by"]
        == "hypothesis-owner@example.com"
    )
    assert hypothesis_body["hypothesis_confirmed_at"] is not None


def test_patch_clears_only_affected_confirmations(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target_id = _create(client, ids).json()["id"]
    target_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-target",
        json={"actor": "target-owner@example.com"},
    )
    assert target_confirmation.status_code == 200
    hypothesis_confirmation = client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": "hypothesis-owner@example.com"},
    )
    assert hypothesis_confirmation.status_code == 200

    hypothesis_edit = client.patch(
        f"/api/optimization-targets/{target_id}",
        json={"planned_change": "Use a narrower eligibility reminder."},
    )
    assert hypothesis_edit.status_code == 200
    hypothesis_body = hypothesis_edit.json()
    assert hypothesis_body["status"] == "confirmed"
    assert hypothesis_body["confirmed_by"] == "target-owner@example.com"
    assert hypothesis_body["hypothesis_confirmed_by"] is None
    assert hypothesis_body["hypothesis_confirmed_at"] is None

    reconfirmed = client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": "hypothesis-owner@example.com"},
    )
    assert reconfirmed.status_code == 200
    assert reconfirmed.json()["status"] == "confirmed"

    target_edit = client.patch(
        f"/api/optimization-targets/{target_id}",
        json={"definition": "Improve eligibility accuracy for target cases."},
    )
    assert target_edit.status_code == 200
    target_body = target_edit.json()
    assert target_body["status"] == "draft"
    assert target_body["confirmed_by"] is None
    assert target_body["confirmed_at"] is None
    assert target_body["hypothesis_confirmed_by"] is None
    assert target_body["hypothesis_confirmed_at"] is None


def test_incomplete_plan_cannot_freeze(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    payload = {**CREATE_PAYLOAD, "policy_version": None}
    target_id = _create(client, ids, payload).json()["id"]
    assert client.post(
        f"/api/optimization-targets/{target_id}/confirm-target",
        json={"actor": "owner@example.com"},
    ).status_code == 200
    assert client.post(
        f"/api/optimization-targets/{target_id}/confirm-hypothesis",
        json={"actor": "owner@example.com"},
    ).status_code == 200

    response = client.post(
        f"/api/optimization-targets/{target_id}/freeze",
        json={"actor": "owner@example.com"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "optimization_target_freeze_gate_failed"
    )
    loaded = client.get(f"/api/optimization-targets/{target_id}").json()
    assert loaded["status"] == "confirmed"
    assert loaded["plan_hash"] is None


def test_complete_plan_freezes_with_deterministic_hash_and_is_idempotent(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target_id = _create(client, ids).json()["id"]

    first = _confirm_and_freeze(client, target_id)

    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "frozen"
    assert body["version"] == 1
    assert body["frozen_by"] == "owner@example.com"
    assert body["frozen_at"] is not None
    assert body["plan_hash"] == _expected_plan_hash(body)

    second = client.post(
        f"/api/optimization-targets/{target_id}/freeze",
        json={"actor": "different-actor@example.com"},
    )
    loaded = client.get(f"/api/optimization-targets/{target_id}")

    assert second.status_code == 200
    assert second.json() == body
    assert loaded.status_code == 200
    assert loaded.json() == body
    with Session(engine) as session:
        targets = session.scalars(select(OptimizationTarget)).all()
        assert len(targets) == 1
        assert targets[0].version == 1


def test_frozen_target_rejects_patch_and_confirmation_changes(api_context) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target_id = _create(client, ids).json()["id"]
    frozen = _confirm_and_freeze(client, target_id)
    assert frozen.status_code == 200
    frozen_body = frozen.json()

    responses = [
        client.patch(
            f"/api/optimization-targets/{target_id}",
            json={"definition": "Forbidden replacement."},
        ),
        client.post(
            f"/api/optimization-targets/{target_id}/confirm-target",
            json={"actor": "other@example.com"},
        ),
        client.post(
            f"/api/optimization-targets/{target_id}/confirm-hypothesis",
            json={"actor": "other@example.com"},
        ),
    ]

    assert all(response.status_code == 409 for response in responses)
    assert all(
        response.json()["error"]["code"] == "optimization_target_frozen"
        for response in responses
    )
    assert client.get(
        f"/api/optimization-targets/{target_id}"
    ).json() == frozen_body


def test_confirm_and_freeze_do_not_modify_baseline_lineage(api_context) -> None:
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

    target_id = _create(client, ids).json()["id"]
    assert _confirm_and_freeze(client, target_id).status_code == 200

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


@pytest.mark.parametrize("existing_draft", [False, True])
def test_complete_target_freezes_without_optional_notes(api_context, existing_draft):
    client, engine = api_context
    ids = _seed_run(engine)
    payload = {key: CREATE_PAYLOAD[key] for key in (
        "definition", "inclusion_criteria", "exclusion_criteria",
        "expected_observable_change",
    )}
    draft = _create(client, ids, payload).json() if existing_draft else None
    url = (
        f"/api/evaluation-runs/{ids['run_id']}/problems/"
        f"{ids['problem_id']}/optimization-targets/complete"
    )
    response = client.post(url, json={"actor": " owner ", "target": payload})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "frozen"
    assert body["hypothesis_statement"] is None
    assert body["planned_change"] is None
    assert body["hypothesis_confirmed_at"] is None
    assert body["confirmed_by"] == body["frozen_by"] == "owner"
    assert body["confirmed_at"] and body["frozen_at"]
    assert body["version"] == 1
    assert body["baseline_run_id"] == str(ids["run_id"])
    assert body["problem_id"] == str(ids["problem_id"])
    assert body["target_case_ids"] == ["CASE-A", "CASE-B"]
    assert body["regression_case_ids"] == ["CASE-C"]
    assert body["challenge_case_ids"] == ["CASE-D"]
    assert body["policy_version"] == "CANDIDATE-DECISION-POLICY-V1"
    assert body["plan_hash"] == _expected_plan_hash(body)
    if draft:
        assert body["id"] == draft["id"]
    assert client.get(f"/api/optimization-targets/{body['id']}").json() == body
    assert client.post(url, json={"actor": "other", "target": payload}).json() == body
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OptimizationTarget)) == 1


@pytest.mark.parametrize("existing_draft", [False, True])
@pytest.mark.parametrize("stage", ["confirm_target", "freeze", "commit"])
def test_complete_failure_rolls_back_all_changes(
    api_context, monkeypatch, existing_draft, stage,
):
    from sqlalchemy.exc import SQLAlchemyError

    from app.optimization_target import OptimizationTargetService

    client, engine = api_context
    ids = _seed_run(engine)
    draft = _create(client, ids).json() if existing_draft else None

    def fail(*args, **kwargs):
        raise SQLAlchemyError("simulated persistence failure")

    monkeypatch.setattr(
        Session if stage == "commit" else OptimizationTargetService, stage, fail,
    )
    response = client.post(
        f"/api/evaluation-runs/{ids['run_id']}/problems/"
        f"{ids['problem_id']}/optimization-targets/complete",
        json={"actor": "owner", "target": {**CREATE_PAYLOAD, "definition": "Edited"}},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "optimization_target_persistence_failed"
    if draft:
        assert client.get(f"/api/optimization-targets/{draft['id']}").json() == draft
    else:
        with Session(engine) as session:
            assert session.scalar(
                select(func.count()).select_from(OptimizationTarget)
            ) == 0


@pytest.mark.parametrize("missing_set", ["target", "regression"])
def test_complete_rejects_missing_cases_and_rolls_back(api_context, missing_set):
    client, engine = api_context
    ids = _seed_run(engine)
    with Session(engine) as session:
        cases = session.scalars(select(Conversation)).all()
        for case in cases:
            if (case.external_id in ["CASE-A", "CASE-B"]) == (missing_set == "target"):
                case.metadata_ = {
                    **case.metadata_, "metadata": {"case_set": "challenge"},
                }
        session.commit()
    response = client.post(
        f"/api/evaluation-runs/{ids['run_id']}/problems/"
        f"{ids['problem_id']}/optimization-targets/complete",
        json={"actor": "owner", "target": CREATE_PAYLOAD},
    )
    assert response.status_code == 409
    assert missing_set + "_case_ids" in response.json()["error"]["message"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OptimizationTarget)) == 0


def test_complete_requires_actor_and_reconfirms_changed_target(api_context):
    client, engine = api_context
    ids = _seed_run(engine)
    draft = _create(client, ids).json()
    client.post(
        f"/api/optimization-targets/{draft['id']}/confirm-target",
        json={"actor": "previous"},
    )
    url = (
        f"/api/evaluation-runs/{ids['run_id']}/problems/"
        f"{ids['problem_id']}/optimization-targets/complete"
    )
    payload = {**CREATE_PAYLOAD, "definition": "Updated optimization goal"}
    assert client.post(url, json={"actor": " ", "target": payload}).status_code == 400
    response = client.post(url, json={"actor": "new owner", "target": payload})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == draft["id"]
    assert body["definition"] == payload["definition"]
    assert body["confirmed_by"] == "new owner"
    assert body["hypothesis_statement"] == CREATE_PAYLOAD["hypothesis_statement"]
    assert body["hypothesis_confirmed_by"] is None
    assert body["plan_hash"] == _expected_plan_hash(body)


def test_optional_hypothesis_migration_preserves_existing_records(api_context):
    from pathlib import Path
    from runpy import run_path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    client, engine = api_context
    ids = _seed_run(engine)
    draft = _create(client, ids).json()
    frozen = _confirm_and_freeze(client, draft["id"]).json()
    second_ids = _seed_run(engine)
    second = _create(client, second_ids).json()
    migration = run_path(str(
        Path(__file__).parents[1] / "alembic" / "versions"
        / "b2d4f6a8c013_optional_target_hypothesis.py"
    ))
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with connection.begin():
            with Operations.context(MigrationContext.configure(connection)):
                migration["downgrade"]()
                migration["upgrade"]()
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert client.get(f"/api/optimization-targets/{draft['id']}").json() == frozen
    assert client.get(f"/api/optimization-targets/{second['id']}").json() == second
    response = client.post(
        f"/api/evaluation-runs/{second_ids['run_id']}/problems/"
        f"{second_ids['problem_id']}/optimization-targets/complete",
        json={"actor": "owner", "target": CREATE_PAYLOAD},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "frozen"
    assert response.json()["hypothesis_confirmed_at"] is None
