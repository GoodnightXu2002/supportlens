from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.import_service import ImportService
from app.main import app, get_db_session, get_import_service
from app.models import Conversation, Dataset


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dataset-read-api.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)
    import_service = ImportService(snapshot_directory=tmp_path / "snapshots")

    def override_db_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_import_service] = lambda: import_service
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def _conversation(external_id: str, scenario: str) -> Conversation:
    return Conversation(
        external_id=external_id,
        messages=[
            {"role": "user", "content": f"Question for {external_id}"},
            {"role": "assistant", "content": f"Answer for {external_id}"},
        ],
        metadata_={"scenario": scenario, "channel": "chat"},
    )


def _persist_dataset(
    engine,
    *,
    name: str,
    created_at: datetime,
    conversations: list[Conversation],
) -> Dataset:
    with Session(engine) as session:
        dataset = Dataset(
            name=name,
            description=f"Description for {name}",
            source="user_upload",
            privacy_status="unknown",
            created_at=created_at,
        )
        dataset.conversations.extend(conversations)
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        session.expunge(dataset)
        return dataset


def test_dataset_list_returns_empty_array(api_context) -> None:
    client, _engine = api_context

    response = client.get("/api/datasets")

    assert response.status_code == 200
    assert response.json() == []


def test_dataset_list_returns_counts_and_newest_first(api_context) -> None:
    client, engine = api_context
    older = _persist_dataset(
        engine,
        name="Older dataset",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        conversations=[_conversation("CASE-001", "billing")],
    )
    newer = _persist_dataset(
        engine,
        name="Newer dataset",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        conversations=[
            _conversation("CASE-002", "returns"),
            _conversation("CASE-003", "returns"),
        ],
    )

    response = client.get("/api/datasets")

    assert response.status_code == 200
    items = response.json()
    assert [item["dataset_id"] for item in items] == [str(newer.id), str(older.id)]
    assert [item["conversation_count"] for item in items] == [2, 1]
    assert items[0]["description"] == "Description for Newer dataset"
    assert items[0]["version"] == "v1.0"
    assert items[0]["source"] == "user_upload"
    assert items[0]["privacy_status"] == "unknown"


def test_dataset_detail_returns_scenario_distribution(api_context) -> None:
    client, engine = api_context
    dataset = _persist_dataset(
        engine,
        name="Scenario dataset",
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
        conversations=[
            _conversation("CASE-001", "billing"),
            _conversation("CASE-002", "returns"),
            _conversation("CASE-003", "billing"),
        ],
    )

    response = client.get(f"/api/datasets/{dataset.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == str(dataset.id)
    assert body["name"] == "Scenario dataset"
    assert body["conversation_count"] == 3
    assert body["scenario_distribution"] == {"billing": 2, "returns": 1}
    assert body["created_at"]


def test_dataset_detail_not_found_uses_stable_error(api_context) -> None:
    client, _engine = api_context

    response = client.get(f"/api/datasets/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_conversation_list_is_complete_sorted_and_does_not_cross_datasets(
    api_context,
) -> None:
    client, engine = api_context
    dataset = _persist_dataset(
        engine,
        name="Selected dataset",
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
        conversations=[
            _conversation("CASE-002", "returns"),
            _conversation("CASE-001", "billing"),
        ],
    )
    _persist_dataset(
        engine,
        name="Other dataset",
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
        conversations=[_conversation("CASE-000", "other")],
    )

    response = client.get(f"/api/datasets/{dataset.id}/conversations")

    assert response.status_code == 200
    conversations = response.json()
    assert [item["external_id"] for item in conversations] == [
        "CASE-001",
        "CASE-002",
    ]
    assert conversations[0]["messages"] == [
        {"role": "user", "content": "Question for CASE-001"},
        {"role": "assistant", "content": "Answer for CASE-001"},
    ]
    assert conversations[0]["metadata"] == {
        "scenario": "billing",
        "channel": "chat",
    }
    assert conversations[0]["created_at"]


def test_conversation_list_requires_existing_dataset(api_context) -> None:
    client, _engine = api_context

    response = client.get(f"/api/datasets/{uuid4()}/conversations")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_preview_confirm_read_e2e(api_context) -> None:
    client, _engine = api_context
    preview_response = client.post(
        "/api/dataset-imports/preview",
        files={
            "file": (
                "cases.csv",
                b"case_id,scenario,user_message,assistant_response\n"
                b"CASE-002,returns,Second question,Second answer\n"
                b"CASE-001,billing,First question,First answer\n",
            )
        },
        data={"name": "Read API E2E"},
    )
    assert preview_response.status_code == 200

    confirm_response = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": preview_response.json()["import_token"]},
    )
    assert confirm_response.status_code == 200
    dataset_id = confirm_response.json()["dataset_id"]

    detail_response = client.get(f"/api/datasets/{dataset_id}")
    conversation_response = client.get(
        f"/api/datasets/{dataset_id}/conversations"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["conversation_count"] == 2
    assert detail_response.json()["scenario_distribution"] == {
        "billing": 1,
        "returns": 1,
    }
    assert conversation_response.status_code == 200
    assert [item["external_id"] for item in conversation_response.json()] == [
        "CASE-001",
        "CASE-002",
    ]
