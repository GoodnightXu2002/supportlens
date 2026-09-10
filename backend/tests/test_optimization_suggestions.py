import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.judge_contract import JudgeOutput
from app.llm_provider import LLMRequest, LLMResponse
from app.main import app, get_db_session, get_optimization_suggestions_service
from app.models import (
    Conversation,
    Dataset,
    EvaluationResult,
    EvaluationRun,
    Problem,
    ResultProblemLink,
)
from app.optimization_suggestions import OptimizationSuggestionsService
from app.problem_aggregation import (
    PROBLEM_MAPPING_VERSION,
    build_problem_mapping_key,
)


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'optimization-suggestions-api.db'}",
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


class SuggestionProvider:
    def __init__(self, mutate=None) -> None:
        self.requests: list[LLMRequest] = []
        self.mutate = mutate

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        problems = json.loads(request.messages[1].content)["problems"]
        payload = {
            "suggestions": [
                {
                    "problem_id": problem["problem_id"],
                    "suggestion": (
                        f"针对场景「{problem['scenario']}」的问题，建议客服在回答时"
                        "先核对上下文再给出结论。"
                    ),
                }
                for problem in problems
            ]
        }
        if self.mutate is not None:
            payload = self.mutate(payload)
        return LLMResponse(
            provider="fake",
            model="fake-suggester",
            structured_payload=payload,
            raw_json_text=json.dumps(payload, ensure_ascii=False),
        )


def _use_provider(client: TestClient, provider: SuggestionProvider) -> None:
    app.dependency_overrides[get_optimization_suggestions_service] = (
        lambda: OptimizationSuggestionsService(provider)
    )


def _machine_output() -> dict[str, object]:
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": "incorrect_information",
            "secondary_flags": [],
            "problem": "The assistant gives incorrect refund eligibility terms.",
            "severity": "medium",
            "evidence": [
                {
                    "evidence_type": "reference",
                    "content": (
                        "Refund eligibility depends on the frozen reference rule."
                    ),
                    "source_ref": "NOVAMART-RULES-V1#REF-002",
                }
            ],
            "uncertainty": None,
            "review_required": False,
            "rationale": "The answer conflicts with the reference.",
        }
    ).model_dump(mode="json")


def _seed_run(engine) -> dict[str, UUID]:
    with Session(engine) as session:
        dataset = Dataset(
            name=f"Suggestion dataset {uuid4()}",
            source="user_upload",
            privacy_status="unknown",
        )
        run = EvaluationRun(
            dataset=dataset,
            run_type="baseline",
            status="completed",
            judge_model="test-judge",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key=f"optimization-suggestions:{uuid4()}",
            business_reference_snapshot="Frozen business reference.",
            problem_aggregation_completed_at=datetime.now(UTC),
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
            mapping_key=build_problem_mapping_key("Refund", problem_definition),
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
        return {"run_id": run.id, "problem_id": problem.id}


def _add_problem_for_case(engine, ids: dict[str, UUID], case_id: str) -> UUID:
    with Session(engine) as session:
        result = session.scalar(
            select(EvaluationResult)
            .join(Conversation)
            .where(Conversation.external_id == case_id)
        )
        assert result is not None
        definition = f"A second problem affects {case_id}."
        problem = Problem(
            evaluation_run_id=ids["run_id"],
            scenario="Product",
            definition=definition,
            mapping_key=build_problem_mapping_key("Product", definition),
            mapping_version=PROBLEM_MAPPING_VERSION,
        )
        session.add(problem)
        session.flush()
        session.add(
            ResultProblemLink(
                problem=problem,
                evaluation_result=result,
                role="primary",
            )
        )
        session.commit()
        return problem.id


def _create_multi_problem_target(
    client: TestClient,
    engine,
    ids: dict[str, UUID],
) -> dict[str, object]:
    second_problem_id = _add_problem_for_case(engine, ids, "CASE-C")
    response = client.post(
        f"/api/evaluation-runs/{ids['run_id']}/optimization-targets",
        json={
            **CREATE_PAYLOAD,
            "problem_ids": [str(ids["problem_id"]), str(second_problem_id)],
        },
    )
    assert response.status_code == 201
    return response.json()


def _confirm_and_freeze_target(
    client: TestClient,
    target_id: str,
    *,
    actor: str = "owner@example.com",
) -> dict[str, object]:
    confirmed = client.post(
        f"/api/optimization-targets/{target_id}/confirm-target",
        json={"actor": actor},
    )
    assert confirmed.status_code == 200
    frozen = client.post(
        f"/api/optimization-targets/{target_id}/freeze",
        json={"actor": actor},
    )
    assert frozen.status_code == 200
    return frozen.json()


def _generate(client: TestClient, target_id: str):
    return client.post(
        f"/api/optimization-targets/{target_id}/optimization-suggestions"
    )


def test_generate_uses_one_llm_call_and_persists_one_suggestion_per_problem(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    provider = SuggestionProvider()
    _use_provider(client, provider)

    response = _generate(client, target["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["optimization_target_id"] == target["id"]
    assert body["generated"] is True
    assert [item["problem_id"] for item in body["suggestions"]] == (
        target["problem_ids"]
    )
    assert all(item["suggestion"].strip() for item in body["suggestions"])

    assert len(provider.requests) == 1
    user_payload = json.loads(provider.requests[0].messages[1].content)
    assert [
        {
            "problem_id": item["problem_id"],
            "scenario": item["scenario"],
            "definition": item["definition"],
        }
        for item in user_payload["problems"]
    ] == [
        {
            "problem_id": problem_id,
            "scenario": "Refund" if index == 0 else "Product",
            "definition": (
                "The assistant gives incorrect refund eligibility terms."
                if index == 0
                else "A second problem affects CASE-C."
            ),
        }
        for index, problem_id in enumerate(target["problem_ids"])
    ]

    stored = client.get(f"/api/optimization-targets/{target['id']}").json()
    assert stored["optimization_suggestions"] == body["suggestions"]
    assert stored["status"] == "draft"
    assert stored["confirmed_by"] is None
    assert stored["hypothesis_confirmed_by"] is None


def test_stored_suggestions_are_returned_without_repeated_llm_call(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    provider = SuggestionProvider()
    _use_provider(client, provider)
    first = _generate(client, target["id"])
    assert first.status_code == 200

    second = _generate(client, target["id"])

    assert second.status_code == 200
    assert second.json()["generated"] is False
    assert second.json()["suggestions"] == first.json()["suggestions"]
    assert len(provider.requests) == 1


def test_frozen_target_returns_stored_suggestions_without_overwrite(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    provider = SuggestionProvider()
    _use_provider(client, provider)
    generated = _generate(client, target["id"])
    assert generated.status_code == 200
    frozen = _confirm_and_freeze_target(client, target["id"])

    response = _generate(client, target["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is False
    assert body["suggestions"] == generated.json()["suggestions"]
    assert len(provider.requests) == 1
    stored = client.get(f"/api/optimization-targets/{target['id']}").json()
    assert stored["optimization_suggestions"] == generated.json()["suggestions"]
    assert stored["status"] == "frozen"
    assert stored["plan_hash"] == frozen["plan_hash"]


def test_frozen_target_without_suggestions_generates_without_state_changes(
    api_context,
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    frozen = _confirm_and_freeze_target(client, target["id"])
    provider = SuggestionProvider()
    _use_provider(client, provider)

    response = _generate(client, target["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    assert [item["problem_id"] for item in body["suggestions"]] == (
        target["problem_ids"]
    )
    assert len(provider.requests) == 1
    stored = client.get(f"/api/optimization-targets/{target['id']}").json()
    assert stored["optimization_suggestions"] == body["suggestions"]
    assert stored["status"] == "frozen"
    assert stored["plan_hash"] == frozen["plan_hash"]
    assert stored["hypothesis_confirmed_by"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: {"suggestions": payload["suggestions"][:-1]},
        lambda payload: {
            "suggestions": [
                *payload["suggestions"],
                {"problem_id": str(uuid4()), "suggestion": "多余的建议。"},
            ]
        },
        lambda payload: {
            "suggestions": [
                payload["suggestions"][0],
                payload["suggestions"][0],
                payload["suggestions"][1],
            ]
        },
        lambda payload: {
            "suggestions": [
                {
                    "problem_id": payload["suggestions"][0]["problem_id"],
                    "suggestion": " ",
                },
                *payload["suggestions"][1:],
            ]
        },
    ],
    ids=["missing_problem", "extra_problem", "duplicate_problem", "blank_suggestion"],
)
def test_invalid_llm_output_is_rejected_and_not_persisted(
    api_context, mutate
) -> None:
    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    _use_provider(client, SuggestionProvider(mutate=mutate))

    response = _generate(client, target["id"])

    assert response.status_code == 502
    assert (
        response.json()["error"]["code"]
        == "optimization_suggestions_llm_output_invalid"
    )
    stored = client.get(f"/api/optimization-targets/{target['id']}").json()
    assert stored["optimization_suggestions"] is None

    _use_provider(client, SuggestionProvider())
    recovered = _generate(client, target["id"])
    assert recovered.status_code == 200
    assert recovered.json()["generated"] is True


def test_unknown_target_returns_404(api_context) -> None:
    client, _engine = api_context
    _use_provider(client, SuggestionProvider())

    response = _generate(client, str(uuid4()))

    assert response.status_code == 404
    assert (
        response.json()["error"]["code"] == "optimization_target_not_found"
    )


def test_suggestions_column_migration_round_trip(api_context) -> None:
    from pathlib import Path
    from runpy import run_path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    client, engine = api_context
    ids = _seed_run(engine)
    target = _create_multi_problem_target(client, engine, ids)
    migration = run_path(str(
        Path(__file__).parents[1] / "alembic" / "versions"
        / "e7b9d1f5a3c2_add_optimization_suggestions.py"
    ))
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with connection.begin():
            with Operations.context(MigrationContext.configure(connection)):
                migration["downgrade"]()
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info('optimization_targets')"
                )
            }
            assert "optimization_suggestions" not in columns
        with connection.begin():
            with Operations.context(MigrationContext.configure(connection)):
                migration["upgrade"]()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert client.get(f"/api/optimization-targets/{target['id']}").status_code == 200
