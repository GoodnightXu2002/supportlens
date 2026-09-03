import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.import_parser import MAX_FILE_SIZE_BYTES, ImportErrorCode
from app.import_service import ImportService
from app.main import app, get_db_session, get_import_service
from app.models import Conversation, Dataset


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


@pytest.fixture
def api_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'import-api.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False)
    clock = MutableClock()
    import_service = ImportService(
        snapshot_directory=tmp_path / "snapshots",
        clock=clock,
    )

    def override_db_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_import_service] = lambda: import_service
    with TestClient(app) as client:
        yield client, engine, clock
    app.dependency_overrides.clear()
    engine.dispose()


def _csv_bytes(conversation_count: int = 1) -> bytes:
    header = "case_id,scenario,user_message,assistant_response\n"
    rows = "".join(
        (
            f"CASE-{index:03d},{'returns' if index % 2 else 'shipping'},"
            f"Question {index},Answer {index}\n"
        )
        for index in range(1, conversation_count + 1)
    )
    return (header + rows).encode()


def _json_bytes() -> bytes:
    return json.dumps(
        [
            {
                "case_id": "CASE-JSON-001",
                "scenario": "billing",
                "messages": [
                    {"role": "user", "content": "Why was I charged?"},
                    {"role": "assistant", "content": "I will check."},
                ],
                "metadata": {"channel": "chat"},
            }
        ]
    ).encode()


def _preview(client: TestClient, data: bytes, filename: str = "cases.csv"):
    return client.post(
        "/api/dataset-imports/preview",
        files={"file": (filename, data)},
        data={"name": "API import"},
    )


def test_csv_preview_returns_token_summary_and_does_not_write_database(
    api_context,
) -> None:
    client, engine, _clock = api_context

    response = _preview(client, _csv_bytes(25))

    assert response.status_code == 200
    body = response.json()
    assert body["import_token"]
    assert body["dataset_identity"]["name"] == "API import"
    assert body["dataset_identity"]["version"] == "v1.0"
    assert body["dataset_identity"]["source"] == "user_upload"
    assert body["dataset_identity"]["privacy_status"] == "unknown"
    assert body["total_conversation_count"] == 25
    assert body["scenario_distribution"] == {"returns": 13, "shipping": 12}
    assert len(body["preview_conversations"]) == 20
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_json_preview_confirm_e2e_persists_dataset_and_conversations(
    api_context,
) -> None:
    client, engine, _clock = api_context
    preview_response = client.post(
        "/api/dataset-imports/preview",
        files={"file": ("cases.json", _json_bytes(), "application/json")},
        data={
            "name": "Fixture API import",
            "version": "v2.0",
            "source": "fixture_import",
            "privacy_status": "synthetic",
            "representativeness_statement": "Synthetic test data only.",
        },
    )

    assert preview_response.status_code == 200
    token = preview_response.json()["import_token"]
    confirm_response = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": token},
    )

    assert confirm_response.status_code == 200
    body = confirm_response.json()
    assert body["name"] == "Fixture API import"
    assert body["version"] == "v2.0"
    assert body["source"] == "fixture_import"
    assert body["privacy_status"] == "synthetic"
    assert body["representativeness_statement"] == "Synthetic test data only."
    assert body["conversation_count"] == 1
    assert body["created_at"]

    with Session(engine) as session:
        dataset_id = UUID(body["dataset_id"])
        dataset = session.get(Dataset, dataset_id)
        conversations = session.scalars(
            select(Conversation).where(Conversation.dataset_id == dataset_id)
        ).all()
        assert dataset is not None
        assert len(conversations) == 1
        assert conversations[0].external_id == "CASE-JSON-001"
        assert conversations[0].messages[0] == {
            "role": "user",
            "content": "Why was I charged?",
        }
        assert conversations[0].metadata_ == {
            "scenario": "billing",
            "metadata": {"channel": "chat"},
        }

    second_confirm = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": token},
    )
    assert second_confirm.status_code == 404
    assert second_confirm.json()["error"]["code"] == "import_token_not_found"


@pytest.mark.parametrize(
    ("filename", "data", "expected_code"),
    [
        ("cases.txt", b"invalid", ImportErrorCode.UNSUPPORTED_FILE_TYPE),
        (
            "cases.json",
            b"x" * (MAX_FILE_SIZE_BYTES + 1),
            ImportErrorCode.FILE_TOO_LARGE,
        ),
        ("cases.json", b"[{", ImportErrorCode.MALFORMED_JSON),
        (
            "cases.csv",
            (
                b"case_id,scenario,user_message,assistant_response\n"
                b"CASE-001,billing,Question,Answer\n"
                b"CASE-001,billing,Question,Answer\n"
            ),
            ImportErrorCode.DUPLICATE_CASE_ID,
        ),
        (
            "cases.json",
            json.dumps(
                [
                    {
                        "case_id": "CASE-001",
                        "scenario": "billing",
                        "messages": [
                            {"role": "user", "content": "Question"},
                            {"role": "assistant", "content": "Answer"},
                        ],
                        "metadata": "not-an-object",
                    }
                ]
            ).encode(),
            ImportErrorCode.INVALID_METADATA_SCHEMA,
        ),
    ],
    ids=[
        "unsupported-file-type",
        "file-too-large",
        "malformed-json",
        "duplicate-case-id",
        "invalid-metadata",
    ],
)
def test_invalid_import_files_return_stable_parser_errors(
    api_context, filename, data, expected_code
) -> None:
    client, _engine, _clock = api_context

    response = _preview(client, data, filename)

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "import_validation_failed"
    assert expected_code.value in {
        detail["code"] for detail in body["error"]["details"]
    }
    for detail in body["error"]["details"]:
        assert {"row", "item_index", "field", "code", "message"} <= detail.keys()


def test_missing_required_preview_input_uses_error_contract(api_context) -> None:
    client, _engine, _clock = api_context

    response = client.post("/api/dataset-imports/preview")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request_validation_failed"


def test_unknown_token_returns_not_found(api_context) -> None:
    client, _engine, _clock = api_context

    response = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": "unknown-token"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "import_token_not_found",
            "message": "Import token was not found.",
            "details": None,
        }
    }


def test_expired_token_returns_gone(api_context) -> None:
    client, _engine, clock = api_context
    preview_response = _preview(client, _csv_bytes())
    token = preview_response.json()["import_token"]
    clock.current += timedelta(minutes=30)

    response = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": token},
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "import_token_expired"


def test_persistence_failure_is_atomic_and_does_not_leak_internal_error(
    api_context,
) -> None:
    client, engine, _clock = api_context
    preview_response = _preview(client, _csv_bytes(2))
    token = preview_response.json()["import_token"]

    def fail_during_conversation_insert(_mapper, _connection, target) -> None:
        if target.external_id == "CASE-002":
            raise RuntimeError("secret database failure")

    event.listen(Conversation, "after_insert", fail_during_conversation_insert)
    try:
        response = client.post(
            "/api/dataset-imports/confirm",
            json={"import_token": token},
        )
    finally:
        event.remove(Conversation, "after_insert", fail_during_conversation_insert)

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "dataset_persistence_failed"
    assert "secret" not in response.text
    assert "database" not in body["error"]["message"].lower()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0

    retry_response = client.post(
        "/api/dataset-imports/confirm",
        json={"import_token": token},
    )
    assert retry_response.status_code == 200
    assert retry_response.json()["conversation_count"] == 2
