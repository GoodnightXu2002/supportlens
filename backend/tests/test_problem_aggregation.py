from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.human_review import HumanReviewService
from app.judge_contract import JudgeOutput
from app.main import app, get_db_session
from app.models import (
    Conversation,
    Dataset,
    EvaluationResult,
    EvaluationRun,
    Problem,
    ResultProblemLink,
)
from app.problem_aggregation import (
    PROBLEM_MAPPING_VERSION,
    build_problem_mapping_key,
)
from app.schemas import HumanReviewAction


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'problem-aggregation-api.db'}",
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


def _output(
    judgment: str,
    problem: str | None,
    *,
    review_required: bool = False,
) -> dict[str, object]:
    is_failure = judgment == "failure"
    return JudgeOutput.model_validate(
        {
            "judgment": judgment,
            "primary_failure_mode": (
                "incorrect_information" if is_failure else None
            ),
            "secondary_flags": (
                ["policy_procedure_violation"] if is_failure else []
            ),
            "problem": problem,
            "severity": "medium" if is_failure else None,
            "evidence": [],
            "uncertainty": (
                "The available evidence is incomplete."
                if judgment == "uncertain"
                else None
            ),
            "review_required": review_required,
            "rationale": f"A valid {judgment} machine judgment.",
        }
    ).model_dump(mode="json")


def _create_run(
    session: Session,
    cases: list[dict[str, object]],
    *,
    run_type: str = "baseline",
    status: str = "completed",
    omit_result_for: set[str] | None = None,
) -> tuple[EvaluationRun, dict[str, EvaluationResult]]:
    dataset = Dataset(
        name=f"Problem aggregation dataset {uuid4()}",
        source="user_upload",
        privacy_status="unknown",
    )
    evaluation_run = EvaluationRun(
        dataset=dataset,
        run_type=run_type,
        status=status,
        judge_model="test-judge",
        judge_contract_version="JUDGE-CONTRACT-V1",
        run_source="live",
        response_set_key=f"problem-aggregation:{uuid4()}",
    )
    results: dict[str, EvaluationResult] = {}
    for case in cases:
        case_id = str(case["case_id"])
        conversation = Conversation(
            dataset=dataset,
            external_id=case_id,
            messages=[
                {"role": "user", "content": "Please help."},
                {"role": "assistant", "content": "Here is an answer."},
            ],
            metadata_={"scenario": case["scenario"]},
        )
        session.add(conversation)
        if omit_result_for and case_id in omit_result_for:
            continue
        result = EvaluationResult(
            evaluation_run=evaluation_run,
            conversation=conversation,
            raw_judge_output={"case_id": case_id},
            **_output(
                str(case["judgment"]),
                case.get("problem"),
                review_required=bool(case.get("review_required", False)),
            ),
        )
        session.add(result)
        results[case_id] = result
    session.flush()
    return evaluation_run, results


def _generate(client: TestClient, run_id: UUID):
    return client.post(f"/api/evaluation-runs/{run_id}/problems")


def test_exact_v1_eligibility_grouping_and_traceability(api_context) -> None:
    client, engine = api_context
    cases = [
        {
            "case_id": "WARNING-NFKC",
            "scenario": "Refund",
            "judgment": "warning",
            "problem": "  Ｒｅｆｕｎｄ\u3000rule  ",
        },
        {
            "case_id": "FAILURE-WHITESPACE",
            "scenario": "Refund",
            "judgment": "failure",
            "problem": "Refund   rule",
        },
        {
            "case_id": "SUCCESS-IGNORED",
            "scenario": "Refund",
            "judgment": "success",
            "problem": "Success must not become a Problem.",
        },
        {
            "case_id": "UNCERTAIN-IGNORED",
            "scenario": "Refund",
            "judgment": "uncertain",
            "problem": "Uncertain must not become a Problem.",
        },
        {
            "case_id": "BLANK-IGNORED",
            "scenario": "Refund",
            "judgment": "warning",
            "problem": "   ",
        },
        {
            "case_id": "OTHER-SCENARIO",
            "scenario": "Logistics",
            "judgment": "warning",
            "problem": "Refund rule",
        },
        {
            "case_id": "OTHER-DEFINITION",
            "scenario": "Refund",
            "judgment": "failure",
            "problem": "Different actionable failure",
        },
    ]
    with Session(engine) as session:
        evaluation_run, results = _create_run(session, cases)
        session.commit()
        run_id = evaluation_run.id
        result_ids = {case_id: result.id for case_id, result in results.items()}

    response = _generate(client, run_id)

    assert response.status_code == 201
    problems = response.json()
    assert len(problems) == 3
    assert {item["mapping_version"] for item in problems} == {
        PROBLEM_MAPPING_VERSION
    }
    grouped = next(
        item
        for item in problems
        if item["scenario"] == "Refund"
        and item["definition"] == "Refund rule"
    )
    assert grouped["mapping_key"] == build_problem_mapping_key(
        "Refund",
        "Refund rule",
    )
    assert grouped["affected_case_count"] == 2
    assert grouped["affected_case_ids"] == [
        "FAILURE-WHITESPACE",
        "WARNING-NFKC",
    ]
    assert set(grouped["affected_evaluation_result_ids"]) == {
        str(result_ids["FAILURE-WHITESPACE"]),
        str(result_ids["WARNING-NFKC"]),
    }
    assert any(
        item["scenario"] == "Logistics"
        and item["definition"] == "Refund rule"
        for item in problems
    )
    assert any(
        item["scenario"] == "Refund"
        and item["definition"] == "Different actionable failure"
        for item in problems
    )
    linked_case_ids = {
        case_id
        for item in problems
        for case_id in item["affected_case_ids"]
    }
    assert linked_case_ids == {
        "WARNING-NFKC",
        "FAILURE-WHITESPACE",
        "OTHER-SCENARIO",
        "OTHER-DEFINITION",
    }

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Problem)) == 3
        links = list(session.scalars(select(ResultProblemLink)).all())
        assert len(links) == 4
        assert {link.role for link in links} == {"primary"}
        assert all(
            link.problem.evaluation_run_id == link.evaluation_result.evaluation_run_id
            for link in links
        )


def test_human_corrected_problem_is_the_only_formal_input(api_context) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, results = _create_run(
            session,
            [
                {
                    "case_id": "HUMAN-CORRECTED",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "Obsolete machine problem",
                    "review_required": True,
                }
            ],
        )
        session.commit()
        run_id = evaluation_run.id
        result_id = results["HUMAN-CORRECTED"].id

    corrected = deepcopy(_output("failure", "Human final problem"))
    corrected["review_required"] = True
    with Session(engine) as session:
        HumanReviewService().submit(
            result_id,
            reviewer="reviewer@example.com",
            action=HumanReviewAction.CORRECT,
            final_result=corrected,
            change_reason="The machine described the wrong actionable behavior.",
            db_session=session,
        )

    response = _generate(client, run_id)

    assert response.status_code == 201
    assert len(response.json()) == 1
    problem = response.json()[0]
    assert problem["definition"] == "Human final problem"
    assert problem["affected_evaluation_result_ids"] == [str(result_id)]
    assert "Obsolete machine problem" not in response.text
    with Session(engine) as session:
        machine = session.get(EvaluationResult, result_id)
        assert machine is not None
        assert machine.problem == "Obsolete machine problem"


def test_pending_review_blocks_aggregation_without_partial_writes(
    api_context,
) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, _results = _create_run(
            session,
            [
                {
                    "case_id": "PENDING",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "Pending problem",
                    "review_required": True,
                }
            ],
        )
        session.commit()
        run_id = evaluation_run.id

    response = _generate(client, run_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "problem_aggregation_pending_review"
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Problem)) == 0
        assert session.scalar(
            select(func.count()).select_from(ResultProblemLink)
        ) == 0
        run = session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.problem_aggregation_completed_at is None


@pytest.mark.parametrize(
    ("run_type", "status", "expected_code"),
    [
        ("candidate", "completed", "problem_aggregation_not_baseline"),
        ("baseline", "running", "problem_aggregation_run_not_completed"),
    ],
)
def test_run_type_and_status_preconditions_are_enforced(
    api_context,
    run_type: str,
    status: str,
    expected_code: str,
) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, _results = _create_run(
            session,
            [
                {
                    "case_id": "PRECONDITION",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "A problem",
                }
            ],
            run_type=run_type,
            status=status,
        )
        session.commit()
        run_id = evaluation_run.id

    response = _generate(client, run_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code


def test_missing_final_result_blocks_aggregation(api_context) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, _results = _create_run(
            session,
            [
                {
                    "case_id": "WITH-RESULT",
                    "scenario": "Refund",
                    "judgment": "success",
                    "problem": None,
                },
                {
                    "case_id": "WITHOUT-RESULT",
                    "scenario": "Refund",
                    "judgment": "success",
                    "problem": None,
                },
            ],
            omit_result_for={"WITHOUT-RESULT"},
        )
        session.commit()
        run_id = evaluation_run.id

    response = _generate(client, run_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "problem_aggregation_final_results_incomplete"
    )


def test_duplicate_aggregation_is_rejected_and_does_not_overwrite(
    api_context,
) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, _results = _create_run(
            session,
            [
                {
                    "case_id": "DUPLICATE",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "Stable problem",
                }
            ],
        )
        session.commit()
        run_id = evaluation_run.id

    first = _generate(client, run_id)
    duplicate = _generate(client, run_id)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == (
        "problem_aggregation_already_completed"
    )
    assert client.get(f"/api/evaluation-runs/{run_id}/problems").json() == (
        first.json()
    )


def test_empty_aggregation_is_also_one_time_only(api_context) -> None:
    client, engine = api_context
    with Session(engine) as session:
        evaluation_run, _results = _create_run(
            session,
            [
                {
                    "case_id": "SUCCESS-ONLY",
                    "scenario": "Refund",
                    "judgment": "success",
                    "problem": None,
                }
            ],
        )
        session.commit()
        run_id = evaluation_run.id

    first = _generate(client, run_id)
    duplicate = _generate(client, run_id)

    assert first.status_code == 201
    assert first.json() == []
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == (
        "problem_aggregation_already_completed"
    )


def test_problem_reads_do_not_cross_evaluation_runs(api_context) -> None:
    client, engine = api_context
    with Session(engine) as session:
        first_run, _first_results = _create_run(
            session,
            [
                {
                    "case_id": "RUN-A",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "Shared text",
                }
            ],
        )
        second_run, _second_results = _create_run(
            session,
            [
                {
                    "case_id": "RUN-B",
                    "scenario": "Refund",
                    "judgment": "failure",
                    "problem": "Shared text",
                }
            ],
        )
        session.commit()
        first_run_id = first_run.id
        second_run_id = second_run.id

    first = _generate(client, first_run_id).json()
    second = _generate(client, second_run_id).json()

    assert first[0]["problem_id"] != second[0]["problem_id"]
    assert first[0]["evaluation_run_id"] == str(first_run_id)
    assert first[0]["affected_case_ids"] == ["RUN-A"]
    assert second[0]["evaluation_run_id"] == str(second_run_id)
    assert second[0]["affected_case_ids"] == ["RUN-B"]
