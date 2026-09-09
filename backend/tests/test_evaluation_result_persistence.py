import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.judge_contract import JudgeOutput
from app.models import Conversation, Dataset, EvaluationResult, EvaluationRun


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'evaluation-results.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _judge_output() -> JudgeOutput:
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": "incorrect_information",
            "secondary_flags": ["policy_procedure_violation"],
            "problem": "The response applies the wrong refund rule.",
            "severity": "high",
            "evidence": [
                {
                    "evidence_type": "response",
                    "content": "A refund is always available after 30 days.",
                    "source_ref": "messages[1]",
                },
                {
                    "evidence_type": "reference",
                    "content": "Refund requests must be made within 7 days.",
                    "source_ref": "REF-002",
                },
            ],
            "uncertainty": None,
            "review_required": True,
            "rationale": "The answer conflicts with the applicable refund window.",
        }
    )


def _persist_inputs(session: Session) -> tuple[EvaluationRun, Conversation]:
    dataset = Dataset(
        name="Evaluation result dataset",
        source="user_upload",
        privacy_status="unknown",
    )
    conversation = Conversation(
        dataset=dataset,
        external_id="CASE-001",
        messages=[
            {"role": "user", "content": "Can I get a refund?"},
            {
                "role": "assistant",
                "content": "A refund is always available after 30 days.",
            },
        ],
    )
    evaluation_run = EvaluationRun(
        dataset=dataset,
        run_type="baseline",
        status="completed",
        judge_model="test-judge",
        judge_contract_version="JUDGE-CONTRACT-V1",
        run_source="live",
        response_set_key="dataset:test:conversations",
    )
    session.add_all([conversation, evaluation_run])
    session.flush()
    return evaluation_run, conversation


def _result_values(output: JudgeOutput) -> dict[str, object]:
    return output.model_dump(mode="json")


def test_valid_judge_output_round_trips_as_evaluation_result(
    database_engine,
) -> None:
    output = _judge_output()

    with Session(database_engine) as session:
        evaluation_run, conversation = _persist_inputs(session)
        result = EvaluationResult(
            evaluation_run=evaluation_run,
            conversation=conversation,
            **_result_values(output),
        )
        session.add(result)
        session.commit()
        result_id = result.id
        run_id = evaluation_run.id
        conversation_id = conversation.id

    with Session(database_engine) as session:
        stored = session.get(EvaluationResult, result_id)
        assert stored is not None
        assert stored.evaluation_run_id == run_id
        assert stored.conversation_id == conversation_id
        assert stored in stored.evaluation_run.evaluation_results
        assert stored in stored.conversation.evaluation_results

        restored_output = JudgeOutput.model_validate(
            {
                field: getattr(stored, field)
                for field in JudgeOutput.model_fields
            }
        )
        assert restored_output == output


def test_run_and_conversation_pair_has_only_one_result(database_engine) -> None:
    output_values = _result_values(_judge_output())

    with Session(database_engine) as session:
        evaluation_run, conversation = _persist_inputs(session)
        session.add_all(
            [
                EvaluationResult(
                    evaluation_run=evaluation_run,
                    conversation=conversation,
                    **output_values,
                ),
                EvaluationResult(
                    evaluation_run=evaluation_run,
                    conversation=conversation,
                    **output_values,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_new_run_can_store_a_new_result_for_the_same_conversation(
    database_engine,
) -> None:
    output_values = _result_values(_judge_output())

    with Session(database_engine) as session:
        first_run, conversation = _persist_inputs(session)
        second_run = EvaluationRun(
            dataset=first_run.dataset,
            run_type="baseline",
            status="completed",
            judge_model="test-judge",
            judge_contract_version="JUDGE-CONTRACT-V1",
            run_source="live",
            response_set_key="dataset:test:conversations",
        )
        session.add_all(
            [
                second_run,
                EvaluationResult(
                    evaluation_run=first_run,
                    conversation=conversation,
                    **output_values,
                ),
                EvaluationResult(
                    evaluation_run=second_run,
                    conversation=conversation,
                    **output_values,
                ),
            ]
        )
        session.commit()

        stored_results = session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.conversation_id == conversation.id
            )
        ).all()

    assert len(stored_results) == 2


@pytest.mark.parametrize("missing_parent", ["run", "conversation"])
def test_result_requires_existing_run_and_conversation(
    database_engine,
    missing_parent: str,
) -> None:
    with Session(database_engine) as session:
        evaluation_run, conversation = _persist_inputs(session)
        values = {
            "evaluation_run_id": (
                uuid4() if missing_parent == "run" else evaluation_run.id
            ),
            "conversation_id": (
                uuid4() if missing_parent == "conversation" else conversation.id
            ),
            **_result_values(_judge_output()),
        }
        session.add(EvaluationResult(**values))

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"judgment": "passed"},
        {"judgment": "failure", "severity": None},
        {"judgment": "success", "severity": "low"},
        {"severity": "urgent"},
        {"primary_failure_mode": "root_cause"},
        {"rationale": "   "},
    ],
)
def test_frozen_scalar_contract_is_constrained_by_database(
    database_engine,
    overrides: dict[str, object],
) -> None:
    with Session(database_engine) as session:
        evaluation_run, conversation = _persist_inputs(session)
        values = _result_values(_judge_output())
        values.update(overrides)
        session.add(
            EvaluationResult(
                evaluation_run=evaluation_run,
                conversation=conversation,
                **values,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("field", ["secondary_flags", "evidence", "rationale"])
def test_required_judge_output_fields_reject_null(
    database_engine,
    field: str,
) -> None:
    with Session(database_engine) as session:
        evaluation_run, conversation = _persist_inputs(session)
        values = _result_values(_judge_output())
        values[field] = None

        with pytest.raises(IntegrityError):
            session.execute(
                insert(EvaluationResult.__table__).values(
                    evaluation_run_id=evaluation_run.id,
                    conversation_id=conversation.id,
                    **values,
                )
            )


def test_alembic_upgrade_creates_evaluation_pipeline_fields(
    tmp_path,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    engine = create_engine(environment["DATABASE_URL"])
    try:
        table_names = inspect(engine).get_table_names()
        run_columns = {
            column["name"]
            for column in inspect(engine).get_columns("evaluation_runs")
        }
        problem_columns = {
            column["name"] for column in inspect(engine).get_columns("problems")
        }
        link_columns = {
            column["name"]
            for column in inspect(engine).get_columns("result_problem_links")
        }
        problem_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints("problems")
        }
        problem_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints("problems")
        }
        link_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "result_problem_links"
            )
        }
        link_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints(
                "result_problem_links"
            )
        }
        link_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspect(engine).get_foreign_keys(
                "result_problem_links"
            )
        }
        result_columns = {
            column["name"]
            for column in inspect(engine).get_columns("evaluation_results")
        }
        decision_columns = {
            column["name"]
            for column in inspect(engine).get_columns("human_decisions")
        }
        decision_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "human_decisions"
            )
        }
        decision_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspect(engine).get_foreign_keys("human_decisions")
        }
        target_columns = {
            column["name"]
            for column in inspect(engine).get_columns("optimization_targets")
        }
        target_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "optimization_targets"
            )
        }
        target_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspect(engine).get_foreign_keys(
                "optimization_targets"
            )
        }
        target_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints(
                "optimization_targets"
            )
        }
        comparison_columns = {
            column["name"]
            for column in inspect(engine).get_columns("case_comparisons")
        }
        comparison_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "case_comparisons"
            )
        }
        run_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints(
                "evaluation_runs"
            )
        }
        run_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspect(engine).get_foreign_keys("evaluation_runs")
        }
        task_columns = {
            column["name"]
            for column in inspect(engine).get_columns("validation_tasks")
        }
        task_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "validation_tasks"
            )
        }
        task_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspect(engine).get_foreign_keys("validation_tasks")
        }
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
    finally:
        engine.dispose()

    assert "evaluation_results" in table_names
    assert "human_decisions" in table_names
    assert {"problems", "result_problem_links"} <= set(table_names)
    assert "optimization_targets" in table_names
    assert "case_comparisons" in table_names
    assert "validation_tasks" in table_names
    assert "candidate_run_id" in task_columns
    assert ("candidate_run_id",) in task_uniques
    assert (
        ("candidate_run_id",),
        "evaluation_runs",
        ("id",),
    ) in task_foreign_keys
    assert {
        "case_errors",
        "business_reference_snapshot",
        "problem_aggregation_completed_at",
        "candidate_responses_snapshot",
        "response_set_hash",
        "candidate_manifest_snapshot",
        "candidate_validation_summary",
        "final_decision",
        "decided_by",
        "decided_at",
        "reason",
        "override_reason",
    } <= run_columns
    assert comparison_columns == {
        "id",
        "baseline_run_id",
        "candidate_run_id",
        "target_id",
        "conversation_id",
        "case_id",
        "baseline_evaluation_result_id",
        "candidate_evaluation_result_id",
        "movement",
        "target_problem_status",
        "target_worse",
        "regression_level",
        "evidence_snapshot",
        "rule_result_snapshot",
        "created_at",
    }
    assert (
        "baseline_run_id",
        "candidate_run_id",
        "conversation_id",
    ) in comparison_uniques
    assert (("target_id",), "optimization_targets", ("id",)) in run_foreign_keys
    assert "raw_judge_output" in result_columns
    assert decision_columns == {
        "id",
        "evaluation_result_id",
        "reviewer",
        "reviewed_at",
        "original_result",
        "final_result",
        "change_reason",
    }
    assert ("evaluation_result_id",) in decision_uniques
    assert (
        ("evaluation_result_id",),
        "evaluation_results",
        ("id",),
    ) in decision_foreign_keys
    assert problem_columns == {
        "id",
        "evaluation_run_id",
        "scenario",
        "definition",
        "mapping_key",
        "mapping_version",
        "created_at",
    }
    assert link_columns == {
        "id",
        "problem_id",
        "evaluation_result_id",
        "role",
    }
    assert ("evaluation_run_id", "mapping_key") in problem_uniques
    assert "length(trim(definition)) > 0" in problem_checks[
        "ck_problems_definition_not_empty"
    ]
    assert "PRIMARY-PROBLEM-EXACT-V1" in problem_checks[
        "ck_problems_mapping_version"
    ]
    assert ("evaluation_result_id", "role") in link_uniques
    assert "role = 'primary'" in link_checks["ck_result_problem_links_role"]
    assert (
        ("problem_id",),
        "problems",
        ("id",),
    ) in link_foreign_keys
    assert (
        ("evaluation_result_id",),
        "evaluation_results",
        ("id",),
    ) in link_foreign_keys
    assert target_columns == {
        "id",
        "baseline_run_id",
        "problem_id",
        "problem_ids",
        "problem_set_key",
        "version",
        "status",
        "definition",
        "inclusion_criteria",
        "exclusion_criteria",
        "baseline_affected_case_ids",
        "reference_basis",
        "failure_mode",
        "baseline_metric",
        "expected_observable_change",
        "confirmed_by",
        "confirmed_at",
        "hypothesis_confirmed_by",
        "hypothesis_confirmed_at",
        "hypothesis_statement",
        "hypothesis_evidence_refs",
        "change_surface",
        "planned_change",
        "guardrails",
        "change_status",
        "target_case_ids",
        "regression_case_ids",
        "challenge_case_ids",
        "protected_capabilities",
        "baseline_snapshot",
        "evaluation_config_snapshot",
        "policy_version",
        "plan_hash",
        "frozen_by",
        "frozen_at",
        "created_at",
        "updated_at",
    }
    assert (
        "baseline_run_id",
        "problem_set_key",
        "version",
    ) in target_uniques
    assert (("baseline_run_id",), "evaluation_runs", ("id",)) in (
        target_foreign_keys
    )
    assert (("problem_id",), "problems", ("id",)) in target_foreign_keys
    assert "version >= 1" in target_checks[
        "ck_optimization_targets_version_positive"
    ]
    assert "draft" in target_checks["ck_optimization_targets_status"]
    assert "confirmed" in target_checks["ck_optimization_targets_status"]
    assert "frozen" in target_checks["ck_optimization_targets_status"]
    assert "planned" in target_checks[
        "ck_optimization_targets_change_status"
    ]
    assert "status = 'frozen'" in target_checks[
        "ck_optimization_targets_frozen_state"
    ]
    assert "length(plan_hash) = 64" in target_checks[
        "ck_optimization_targets_plan_hash_length"
    ]
    assert "partial_failure" in run_checks["ck_evaluation_runs_status"]
    assert "invalid" in run_checks["ck_evaluation_runs_status"]
    assert revision == "b3c4d5e6f7a8"


def test_candidate_migration_preserves_populated_evaluation_run_references(
    tmp_path,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "populated-migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    to_freeze_revision = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "d8e1f4a6b203",
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert to_freeze_revision.returncode == 0, (
        to_freeze_revision.stdout + to_freeze_revision.stderr
    )

    dataset_id = uuid4().hex
    conversation_id = uuid4().hex
    run_id = uuid4().hex
    result_id = uuid4().hex
    engine = create_engine(environment["DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO datasets "
                    "(id, name, version, source, privacy_status, created_at) "
                    "VALUES (:id, 'Migration dataset', 'v1.0', "
                    "'user_upload', 'unknown', CURRENT_TIMESTAMP)"
                ),
                {"id": dataset_id},
            )
            connection.execute(
                text(
                    "INSERT INTO conversations "
                    "(id, dataset_id, external_id, messages, metadata, created_at) "
                    "VALUES (:id, :dataset_id, 'CASE-001', :messages, "
                    ":metadata, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": conversation_id,
                    "dataset_id": dataset_id,
                    "messages": '[{"role":"user","content":"Q"},'
                    '{"role":"assistant","content":"A"}]',
                    "metadata": '{"scenario":"Test"}',
                },
            )
            connection.execute(
                text(
                    "INSERT INTO evaluation_runs "
                    "(id, dataset_id, run_type, status, judge_model, "
                    "judge_contract_version, run_source, response_set_key, "
                    "case_errors, business_reference_snapshot, created_at) "
                    "VALUES (:id, :dataset_id, 'baseline', 'completed', "
                    "'judge', 'contract', 'live', 'response-set', '[]', "
                    "'reference', CURRENT_TIMESTAMP)"
                ),
                {"id": run_id, "dataset_id": dataset_id},
            )
            connection.execute(
                text(
                    "INSERT INTO evaluation_results "
                    "(id, evaluation_run_id, conversation_id, judgment, "
                    "primary_failure_mode, secondary_flags, problem, severity, "
                    "evidence, uncertainty, review_required, rationale, "
                    "raw_judge_output, created_at) VALUES "
                    "(:id, :run_id, :conversation_id, 'success', NULL, '[]', "
                    "NULL, NULL, '[]', NULL, 0, 'Valid result.', NULL, "
                    "CURRENT_TIMESTAMP)"
                ),
                {
                    "id": result_id,
                    "run_id": run_id,
                    "conversation_id": conversation_id,
                },
            )
    finally:
        engine.dispose()

    to_head = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert to_head.returncode == 0, to_head.stdout + to_head.stderr

    engine = create_engine(environment["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM evaluation_runs WHERE id = :id"),
                    {"id": run_id},
                )
                == 1
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM evaluation_results WHERE id = :id"),
                    {"id": result_id},
                )
                == 1
            )
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "b3c4d5e6f7a8"
            )
    finally:
        engine.dispose()
