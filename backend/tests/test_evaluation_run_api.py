from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.main import (
    BASELINE_JUDGE_CONTRACT_VERSION,
    BASELINE_JUDGE_MODEL,
    app,
    get_db_session,
)
from app.models import Dataset, EvaluationRun


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'evaluation-run-api.db'}",
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


def _persist_dataset(engine, name: str = "Evaluation dataset") -> Dataset:
    with Session(engine) as session:
        dataset = Dataset(
            name=name,
            description="Dataset for EvaluationRun API tests.",
            source="user_upload",
            privacy_status="unknown",
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        session.expunge(dataset)
        return dataset


def _create_baseline(client: TestClient, dataset_id: UUID):
    return client.post(
        "/api/evaluation-runs",
        json={"dataset_id": str(dataset_id), "run_type": "baseline"},
    )


def _stored_run(
    *,
    run_id: UUID,
    dataset_id: UUID,
    created_at: datetime,
) -> EvaluationRun:
    return EvaluationRun(
        id=run_id,
        dataset_id=dataset_id,
        run_type="baseline",
        status="pending",
        judge_model=BASELINE_JUDGE_MODEL,
        judge_contract_version=BASELINE_JUDGE_CONTRACT_VERSION,
        run_source="live",
        response_set_key=f"dataset:{dataset_id}:conversations",
        created_at=created_at,
    )


def test_create_baseline_persists_pending_live_run(api_context) -> None:
    client, engine = api_context
    dataset = _persist_dataset(engine)

    response = _create_baseline(client, dataset.id)

    assert response.status_code == 201
    body = response.json()
    assert body["dataset_id"] == str(dataset.id)
    assert body["run_type"] == "baseline"
    assert body["status"] == "pending"
    assert body["run_source"] == "live"
    assert body["judge_model"] == BASELINE_JUDGE_MODEL
    assert body["judge_contract_version"] == BASELINE_JUDGE_CONTRACT_VERSION
    assert body["response_set_key"] == f"dataset:{dataset.id}:conversations"
    assert body["baseline_run_id"] is None
    assert body["target_id"] is None
    assert body["candidate_label"] is None
    assert body["candidate_change_summary"] is None
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert body["created_at"]
    assert "evaluation_results" not in Base.metadata.tables

    run_id = UUID(body["id"])
    with Session(engine) as new_session:
        stored = new_session.get(EvaluationRun, run_id)
        assert stored is not None
        assert stored.dataset_id == dataset.id
        assert stored.status == "pending"

    get_response = client.get(f"/api/evaluation-runs/{run_id}")
    assert get_response.status_code == 200
    assert get_response.json() == body


def test_create_baseline_requires_existing_dataset(api_context) -> None:
    client, engine = api_context

    response = _create_baseline(client, uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EvaluationRun)) == 0


def test_missing_run_uses_stable_error_envelope(api_context) -> None:
    client, _engine = api_context
    run_id = uuid4()

    response = client.get(f"/api/evaluation-runs/{run_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "evaluation_run_not_found",
            "message": f"Evaluation run '{run_id}' was not found.",
            "details": None,
        }
    }


def test_dataset_run_list_is_scoped_and_stably_sorted(api_context) -> None:
    client, engine = api_context
    selected_dataset = _persist_dataset(engine, "Selected dataset")
    other_dataset = _persist_dataset(engine, "Other dataset")
    tied_time = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    older_time = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    tied_lower_id = UUID("00000000-0000-0000-0000-000000000001")
    tied_higher_id = UUID("00000000-0000-0000-0000-000000000002")
    older_id = UUID("00000000-0000-0000-0000-000000000003")
    other_id = UUID("00000000-0000-0000-0000-000000000004")

    with Session(engine) as session:
        session.add_all(
            [
                _stored_run(
                    run_id=tied_lower_id,
                    dataset_id=selected_dataset.id,
                    created_at=tied_time,
                ),
                _stored_run(
                    run_id=tied_higher_id,
                    dataset_id=selected_dataset.id,
                    created_at=tied_time,
                ),
                _stored_run(
                    run_id=older_id,
                    dataset_id=selected_dataset.id,
                    created_at=older_time,
                ),
                _stored_run(
                    run_id=other_id,
                    dataset_id=other_dataset.id,
                    created_at=tied_time,
                ),
            ]
        )
        session.commit()

    response = client.get(
        f"/api/datasets/{selected_dataset.id}/evaluation-runs"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        str(tied_higher_id),
        str(tied_lower_id),
        str(older_id),
    ]


def test_same_dataset_allows_multiple_baselines_without_overwrite(
    api_context,
) -> None:
    client, engine = api_context
    dataset = _persist_dataset(engine)

    first = _create_baseline(client, dataset.id)
    second = _create_baseline(client, dataset.id)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    with Session(engine) as session:
        runs = session.scalars(
            select(EvaluationRun).where(EvaluationRun.dataset_id == dataset.id)
        ).all()
        assert len(runs) == 2


def test_baseline_create_rejects_invalid_requests(api_context) -> None:
    client, engine = api_context
    dataset = _persist_dataset(engine)
    invalid_payloads = [
        {"run_type": "baseline"},
        {"dataset_id": str(dataset.id), "run_type": "candidate"},
        {"dataset_id": str(dataset.id), "run_type": "other"},
    ]

    for payload in invalid_payloads:
        response = client.post("/api/evaluation-runs", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "request_validation_failed"
        assert isinstance(body["error"]["details"], list)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EvaluationRun)) == 0


def test_creation_failure_rolls_back_without_leaking_database_error(
    api_context,
) -> None:
    client, engine = api_context
    dataset = _persist_dataset(engine)

    def fail_insert(_mapper, _connection, _target) -> None:
        raise RuntimeError("secret evaluation database failure")

    event.listen(EvaluationRun, "before_insert", fail_insert)
    try:
        response = _create_baseline(client, dataset.id)
    finally:
        event.remove(EvaluationRun, "before_insert", fail_insert)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "evaluation_run_creation_failed",
            "message": "Evaluation run could not be created.",
            "details": None,
        }
    }
    assert "secret" not in response.text
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EvaluationRun)) == 0
