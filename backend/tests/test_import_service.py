import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.import_parser import ImportErrorCode
from app.import_service import (
    ImportFileValidationError,
    ImportService,
    ImportServiceError,
    ImportServiceErrorCode,
)
from app.models import Conversation, Dataset
from app.schemas import PrivacyStatus


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'import-service.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def snapshot_directory(tmp_path):
    return tmp_path / "snapshots"


@pytest.fixture
def import_service(snapshot_directory, clock) -> ImportService:
    return ImportService(snapshot_directory=snapshot_directory, clock=clock)


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
                "business_context": "Priority customer",
                "metadata": {"channel": "chat"},
            }
        ]
    ).encode()


def _preview_csv(import_service: ImportService, **identity_overrides):
    identity = {
        "dataset_name": "Support cases",
        "source": "user_upload",
    }
    identity.update(identity_overrides)
    return import_service.preview_import(
        _csv_bytes(),
        filename="cases.csv",
        **identity,
    )


def test_valid_csv_preview_uses_full_dataset_for_summary_and_limits_rows(
    import_service,
) -> None:
    preview = import_service.preview_import(
        _csv_bytes(25),
        filename="cases.csv",
        dataset_name="Support cases",
        description="September sample",
        source="user_upload",
    )

    assert preview.import_token
    assert preview.dataset_identity.name == "Support cases"
    assert preview.dataset_identity.description == "September sample"
    assert preview.dataset_identity.version == "v1.0"
    assert preview.dataset_identity.privacy_status is PrivacyStatus.UNKNOWN
    assert preview.total_conversation_count == 25
    assert preview.scenario_distribution == {"returns": 13, "shipping": 12}
    assert len(preview.preview_conversations) == 20
    assert preview.preview_conversations[0].external_id == "CASE-001"


def test_valid_json_preview(import_service) -> None:
    preview = import_service.preview_import(
        _json_bytes(),
        filename="cases.json",
        dataset_name="JSON cases",
        source="user_upload",
    )

    assert preview.total_conversation_count == 1
    assert preview.scenario_distribution == {"billing": 1}
    assert preview.preview_conversations[0].metadata == {
        "scenario": "billing",
        "business_context": "Priority customer",
        "metadata": {"channel": "chat"},
    }


def test_parser_failure_does_not_create_snapshot(
    import_service, snapshot_directory
) -> None:
    with pytest.raises(ImportFileValidationError) as error:
        import_service.preview_import(
            b"case_id,scenario,user_message\nCASE-1,test,Question\n",
            filename="cases.csv",
            dataset_name="Invalid cases",
            source="user_upload",
        )

    assert error.value.errors[0].code is ImportErrorCode.REQUIRED_FIELD_MISSING
    assert list(snapshot_directory.iterdir()) == []


def test_preview_does_not_write_business_tables(
    import_service, database_engine
) -> None:
    _preview_csv(import_service)

    with Session(database_engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_unknown_token_is_rejected(import_service, database_engine) -> None:
    with Session(database_engine) as session:
        with pytest.raises(ImportServiceError) as error:
            import_service.confirm_import("unknown-token", session)

    assert error.value.code is ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND


def test_expired_token_is_rejected_and_cleaned_up(
    import_service, database_engine, clock, snapshot_directory
) -> None:
    preview = _preview_csv(import_service)
    clock.current += timedelta(minutes=30)

    with Session(database_engine) as session:
        with pytest.raises(ImportServiceError) as error:
            import_service.confirm_import(preview.import_token, session)

    assert error.value.code is ImportServiceErrorCode.IMPORT_TOKEN_EXPIRED
    assert list(snapshot_directory.iterdir()) == []


def test_confirm_persists_dataset_identity_conversations_and_json(
    import_service, database_engine
) -> None:
    preview = import_service.preview_import(
        _json_bytes(),
        filename="cases.json",
        dataset_name="Fixture cases",
        description="Validated fixture",
        version="v2.0",
        source="fixture_import",
        privacy_status="synthetic",
        representativeness_statement="Synthetic test conversations only.",
    )

    with Session(database_engine) as session:
        result = import_service.confirm_import(preview.import_token, session)

    with Session(database_engine) as session:
        dataset = session.get(Dataset, result.dataset_id)
        conversations = session.scalars(
            select(Conversation).where(Conversation.dataset_id == result.dataset_id)
        ).all()

        assert dataset is not None
        assert dataset.name == "Fixture cases"
        assert dataset.description == "Validated fixture"
        assert dataset.version == "v2.0"
        assert dataset.source == "fixture_import"
        assert dataset.privacy_status == "synthetic"
        assert (
            dataset.representativeness_statement
            == "Synthetic test conversations only."
        )
        assert result.total_conversation_count == 1
        assert result.conversation_ids == [conversations[0].id]
        assert conversations[0].external_id == "CASE-JSON-001"
        assert conversations[0].messages == [
            {"role": "user", "content": "Why was I charged?"},
            {"role": "assistant", "content": "I will check."},
        ]
        assert conversations[0].metadata_ == {
            "scenario": "billing",
            "business_context": "Priority customer",
            "metadata": {"channel": "chat"},
        }


def test_user_upload_defaults_are_persisted(import_service, database_engine) -> None:
    preview = _preview_csv(import_service)

    with Session(database_engine) as session:
        result = import_service.confirm_import(preview.import_token, session)

    with Session(database_engine) as session:
        dataset = session.get(Dataset, result.dataset_id)
        assert dataset is not None
        assert dataset.privacy_status == "unknown"
        assert dataset.representativeness_statement is None


@pytest.mark.parametrize(
    "identity",
    [
        {
            "privacy_status": "unknown",
            "representativeness_statement": "Synthetic fixture.",
        },
        {
            "privacy_status": "synthetic",
            "representativeness_statement": "   ",
        },
    ],
)
def test_fixture_import_service_rules_are_enforced(import_service, identity) -> None:
    with pytest.raises(ValidationError):
        import_service.preview_import(
            _csv_bytes(),
            filename="cases.csv",
            dataset_name="Invalid fixture",
            source="fixture_import",
            **identity,
        )


def test_successful_confirm_consumes_token(import_service, database_engine) -> None:
    preview = _preview_csv(import_service)

    with Session(database_engine) as session:
        import_service.confirm_import(preview.import_token, session)

    with Session(database_engine) as session:
        with pytest.raises(ImportServiceError) as error:
            import_service.confirm_import(preview.import_token, session)

    assert error.value.code is ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND


def test_persistence_failure_rolls_back_everything_and_preserves_token_for_retry(
    import_service, database_engine
) -> None:
    preview = import_service.preview_import(
        _csv_bytes(2),
        filename="cases.csv",
        dataset_name="Atomic import",
        source="user_upload",
    )

    def fail_during_conversation_insert(_mapper, _connection, target) -> None:
        if target.external_id == "CASE-002":
            raise RuntimeError("forced persistence failure")

    event.listen(Conversation, "after_insert", fail_during_conversation_insert)
    try:
        with Session(database_engine) as session:
            with pytest.raises(ImportServiceError) as error:
                import_service.confirm_import(preview.import_token, session)
    finally:
        event.remove(Conversation, "after_insert", fail_during_conversation_insert)

    assert error.value.code is ImportServiceErrorCode.DATASET_PERSISTENCE_FAILED
    with Session(database_engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0

    with Session(database_engine) as session:
        retry_result = import_service.confirm_import(preview.import_token, session)

    assert retry_result.total_conversation_count == 2
    with Session(database_engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1
        assert session.scalar(select(func.count()).select_from(Conversation)) == 2
