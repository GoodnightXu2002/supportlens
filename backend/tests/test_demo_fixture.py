import ast
import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app import demo_fixture
from app.database import Base
from app.demo_fixture import DemoFixtureStatus, seed_demo_fixture
from app.import_service import ImportFileValidationError, ImportService
from app.models import Conversation, Dataset


class TrackingImportService:
    def __init__(self, delegate: ImportService) -> None:
        self.delegate = delegate
        self.preview_calls = 0
        self.confirm_calls = 0

    def preview_import(self, *args, **kwargs):
        self.preview_calls += 1
        return self.delegate.preview_import(*args, **kwargs)

    def confirm_import(self, *args, **kwargs):
        self.confirm_calls += 1
        return self.delegate.confirm_import(*args, **kwargs)


@pytest.fixture
def database_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo-fixture.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def fixture_path(tmp_path):
    path = tmp_path / "demo.csv"
    path.write_text(
        "case_id,scenario,user_message,assistant_response\n"
        "DEMO-001,shipping,Where is my order?,It arrives tomorrow.\n"
        "DEMO-002,returns,Can I return it?,Yes within 30 days.\n",
        encoding="utf-8",
    )
    return path


def _identity() -> dict[str, str]:
    return {
        "name": "Small Demo Fixture",
        "description": "Test-only Demo fixture.",
        "version": "v1.0",
        "representativeness_statement": "Synthetic test fixture; not representative.",
    }


def _service(tmp_path, name: str) -> ImportService:
    return ImportService(snapshot_directory=tmp_path / name)


def test_seed_uses_import_service_and_persists_fixture_contract(
    database_engine,
    fixture_path,
    tmp_path,
) -> None:
    tracking_service = TrackingImportService(_service(tmp_path, "seed-snapshots"))

    with Session(database_engine) as session:
        result = seed_demo_fixture(
            fixture_path,
            **_identity(),
            db_session=session,
            import_service=tracking_service,
        )

        dataset = session.get(Dataset, result.dataset_id)
        assert dataset is not None
        assert result.status is DemoFixtureStatus.SEEDED
        assert result.conversation_count == 2
        assert tracking_service.preview_calls == 1
        assert tracking_service.confirm_calls == 1
        assert dataset.source == "fixture_import"
        assert dataset.privacy_status == "synthetic"
        assert dataset.representativeness_statement == (
            "Synthetic test fixture; not representative."
        )
        assert session.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.dataset_id == dataset.id
            )
        ) == 2


def test_duplicate_seed_returns_already_seeded_without_second_import(
    database_engine,
    fixture_path,
    tmp_path,
) -> None:
    tracking_service = TrackingImportService(_service(tmp_path, "duplicate-snapshots"))

    with Session(database_engine) as session:
        first = seed_demo_fixture(
            fixture_path,
            **_identity(),
            db_session=session,
            import_service=tracking_service,
        )
        second = seed_demo_fixture(
            fixture_path,
            **_identity(),
            db_session=session,
            import_service=tracking_service,
        )

        assert second.status is DemoFixtureStatus.ALREADY_SEEDED
        assert second.dataset_id == first.dataset_id
        assert second.conversation_count == 2
        assert tracking_service.preview_calls == 1
        assert tracking_service.confirm_calls == 1
        assert session.scalar(select(func.count(Dataset.id))) == 1


def test_reset_only_replaces_exact_fixture_and_preserves_user_upload(
    database_engine,
    fixture_path,
    tmp_path,
) -> None:
    import_service = _service(tmp_path, "reset-snapshots")

    with Session(database_engine) as session:
        fixture = seed_demo_fixture(
            fixture_path,
            **_identity(),
            db_session=session,
            import_service=import_service,
        )
        user_preview = import_service.preview_import(
            fixture_path.read_bytes(),
            filename=fixture_path.name,
            dataset_name=_identity()["name"],
            description="User-owned dataset with the same name.",
            version=_identity()["version"],
            source="user_upload",
        )
        user_result = import_service.confirm_import(user_preview.import_token, session)
        reset_service = TrackingImportService(
            _service(tmp_path, "reset-reimport-snapshots")
        )

        reset_result = seed_demo_fixture(
            fixture_path,
            **_identity(),
            db_session=session,
            import_service=reset_service,
            reset=True,
        )

        assert reset_result.status is DemoFixtureStatus.RESET
        assert reset_result.dataset_id != fixture.dataset_id
        assert session.get(Dataset, fixture.dataset_id) is None
        assert session.get(Dataset, user_result.dataset_id) is not None
        assert reset_service.preview_calls == 1
        assert reset_service.confirm_calls == 1
        assert session.scalar(
            select(func.count(Dataset.id)).where(Dataset.source == "fixture_import")
        ) == 1
        assert session.scalar(
            select(func.count(Dataset.id)).where(Dataset.source == "user_upload")
        ) == 1
        assert session.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.dataset_id == reset_result.dataset_id
            )
        ) == 2


def test_invalid_fixture_does_not_create_dataset(
    database_engine,
    tmp_path,
) -> None:
    invalid_path = tmp_path / "invalid.csv"
    invalid_path.write_text(
        "case_id,scenario,user_message\nDEMO-001,shipping,Where is it?\n",
        encoding="utf-8",
    )

    with Session(database_engine) as session:
        with pytest.raises(ImportFileValidationError):
            seed_demo_fixture(
                invalid_path,
                **_identity(),
                db_session=session,
                import_service=_service(tmp_path, "invalid-snapshots"),
            )

        assert session.scalar(select(func.count(Dataset.id))) == 0
        assert session.scalar(select(func.count(Conversation.id))) == 0


def test_fixture_identity_rules_are_not_bypassed(
    database_engine,
    fixture_path,
    tmp_path,
) -> None:
    identity = _identity()
    identity["representativeness_statement"] = "   "

    with Session(database_engine) as session:
        with pytest.raises(ValidationError, match="non-empty"):
            seed_demo_fixture(
                fixture_path,
                **identity,
                db_session=session,
                import_service=_service(tmp_path, "identity-snapshots"),
            )

        assert session.scalar(select(func.count(Dataset.id))) == 0


def test_seed_module_has_no_dataset_or_conversation_constructor_calls() -> None:
    tree = ast.parse(inspect.getsource(demo_fixture))
    constructor_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "Dataset" not in constructor_names
    assert "Conversation" not in constructor_names
