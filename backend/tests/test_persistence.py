from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Conversation, Dataset
from app.schemas import ConversationRead


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
        dataset = Dataset(name="NovaMart support review")
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


def test_duplicate_external_id_is_rejected_within_dataset(database_engine) -> None:
    with Session(database_engine) as session:
        dataset = Dataset(name="Duplicate constraint")
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
        first = Dataset(name="First")
        second = Dataset(name="Second")
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
