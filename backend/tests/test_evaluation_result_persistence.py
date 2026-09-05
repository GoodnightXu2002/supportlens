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


def test_alembic_upgrade_creates_evaluation_results_table(tmp_path) -> None:
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
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
    finally:
        engine.dispose()

    assert "evaluation_results" in table_names
    assert revision == "e8d2f4a6b901"
