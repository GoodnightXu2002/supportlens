from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Conversation, Dataset
from app.schemas import (
    ConversationRead,
    DatasetCreate,
    DatasetRead,
    DatasetSource,
    PrivacyStatus,
)


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'persistence.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_dataset_with_multiple_conversations_and_json_round_trip(
    database_engine,
) -> None:
    with Session(database_engine) as session:
        dataset = Dataset(
            name="NovaMart support review",
            source="fixture_import",
            privacy_status="synthetic",
            representativeness_statement="Synthetic evaluation fixture only.",
        )
        dataset.conversations.extend(
            [
                Conversation(
                    external_id="CASE-001",
                    messages=[
                        {"role": "user", "content": "Where is my order?"},
                        {"role": "assistant", "content": "I can help."},
                    ],
                    metadata_={"scenario": "logistics"},
                ),
                Conversation(
                    external_id="CASE-002",
                    messages=[{"role": "user", "content": "Can I get a refund?"}],
                ),
            ]
        )
        session.add(dataset)
        session.commit()

        stored_dataset = session.scalar(select(Dataset).where(Dataset.id == dataset.id))
        assert stored_dataset is not None
        assert stored_dataset.version == "v1.0"
        assert stored_dataset.source == "fixture_import"
        assert stored_dataset.privacy_status == "synthetic"
        assert (
            stored_dataset.representativeness_statement
            == "Synthetic evaluation fixture only."
        )
        assert len(stored_dataset.conversations) == 2
        assert stored_dataset.conversations[0].messages[0] == {
            "role": "user",
            "content": "Where is my order?",
        }
        assert stored_dataset.conversations[0].metadata_ == {"scenario": "logistics"}
        conversation_schema = ConversationRead.model_validate(
            stored_dataset.conversations[0]
        )
        assert conversation_schema.metadata == {"scenario": "logistics"}
        dataset_schema = DatasetRead.model_validate(stored_dataset)
        assert dataset_schema.source is DatasetSource.FIXTURE_IMPORT
        assert dataset_schema.privacy_status is PrivacyStatus.SYNTHETIC


def test_user_upload_uses_dataset_defaults(database_engine) -> None:
    dataset_input = DatasetCreate(name="User upload", source="user_upload")
    assert dataset_input.privacy_status is PrivacyStatus.UNKNOWN
    assert dataset_input.representativeness_statement is None

    with Session(database_engine) as session:
        dataset = Dataset(name=dataset_input.name, source=dataset_input.source.value)
        session.add(dataset)
        session.commit()
        session.refresh(dataset)

        assert dataset.privacy_status == "unknown"
        assert dataset.representativeness_statement is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "manual_entry"),
        ("privacy_status", "private"),
    ],
)
def test_dataset_enum_values_are_constrained_by_database(
    database_engine, field: str, value: str
) -> None:
    values = {"source": "user_upload", "privacy_status": "unknown"}
    values[field] = value

    with Session(database_engine) as session:
        session.add(Dataset(name="Invalid enum", **values))

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    "values",
    [
        {"source": None, "privacy_status": "unknown"},
        {"source": "user_upload", "privacy_status": None},
    ],
)
def test_dataset_required_fields_reject_null(
    database_engine, values: dict[str, str | None]
) -> None:
    with Session(database_engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                insert(Dataset.__table__).values(name="Null field", **values)
            )


def test_fixture_import_schema_rules() -> None:
    valid = DatasetCreate(
        name="Fixture",
        source="fixture_import",
        privacy_status="synthetic",
        representativeness_statement=(
            "Synthetic fixture; not production-representative."
        ),
    )
    assert valid.privacy_status is PrivacyStatus.SYNTHETIC

    with pytest.raises(ValueError, match="privacy_status=synthetic"):
        DatasetCreate(
            name="Fixture",
            source="fixture_import",
            representativeness_statement="Synthetic fixture.",
        )

    with pytest.raises(ValueError, match="non-empty"):
        DatasetCreate(
            name="Fixture",
            source="fixture_import",
            privacy_status="synthetic",
            representativeness_statement="   ",
        )


def test_duplicate_external_id_is_rejected_within_dataset(database_engine) -> None:
    with Session(database_engine) as session:
        dataset = Dataset(name="Duplicate constraint", source="user_upload")
        dataset.conversations.extend(
            [
                Conversation(external_id="CASE-001", messages=[]),
                Conversation(external_id="CASE-001", messages=[]),
            ]
        )
        session.add(dataset)

        with pytest.raises(IntegrityError):
            session.commit()


def test_same_external_id_is_allowed_across_datasets(database_engine) -> None:
    with Session(database_engine) as session:
        first = Dataset(name="First", source="user_upload")
        second = Dataset(name="Second", source="user_upload")
        first.conversations.append(Conversation(external_id="CASE-001", messages=[]))
        second.conversations.append(Conversation(external_id="CASE-001", messages=[]))
        session.add_all([first, second])
        session.commit()


def test_conversation_requires_an_existing_dataset(database_engine) -> None:
    with Session(database_engine) as session:
        session.add(
            Conversation(
                dataset_id=uuid4(),
                external_id="ORPHAN",
                messages=[],
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
