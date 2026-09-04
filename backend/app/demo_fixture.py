from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.import_service import ImportFileValidationError, ImportService
from app.models import Conversation, Dataset
from app.schemas import DatasetCreate, DatasetSource, PrivacyStatus


class DemoFixtureStatus(StrEnum):
    SEEDED = "seeded"
    ALREADY_SEEDED = "already_seeded"
    RESET = "reset"


@dataclass(frozen=True)
class DemoFixtureResult:
    status: DemoFixtureStatus
    dataset_id: UUID
    conversation_count: int


def seed_demo_fixture(
    fixture_path: Path | str,
    *,
    name: str,
    description: str,
    version: str,
    representativeness_statement: str,
    db_session: Session,
    import_service: ImportService | None = None,
    reset: bool = False,
) -> DemoFixtureResult:
    """Seed or reset one explicitly identified Demo fixture through ImportService."""
    identity = DatasetCreate.model_validate(
        {
            "name": name,
            "description": description,
            "version": version,
            "source": DatasetSource.FIXTURE_IMPORT,
            "privacy_status": PrivacyStatus.SYNTHETIC,
            "representativeness_statement": representativeness_statement,
        }
    )
    matching_datasets = list(
        db_session.scalars(
            select(Dataset)
            .where(
                Dataset.source == DatasetSource.FIXTURE_IMPORT.value,
                Dataset.name == identity.name,
                Dataset.version == identity.version,
                Dataset.description == identity.description,
                Dataset.privacy_status == PrivacyStatus.SYNTHETIC.value,
                Dataset.representativeness_statement
                == identity.representativeness_statement,
            )
            .order_by(Dataset.created_at.desc(), Dataset.id.desc())
        )
    )

    if matching_datasets and not reset:
        existing = matching_datasets[0]
        conversation_count = db_session.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.dataset_id == existing.id
            )
        )
        return DemoFixtureResult(
            status=DemoFixtureStatus.ALREADY_SEEDED,
            dataset_id=existing.id,
            conversation_count=conversation_count or 0,
        )

    if reset and matching_datasets:
        _delete_demo_fixture_datasets(db_session, matching_datasets)

    path = Path(fixture_path)
    service = import_service or ImportService()
    preview = service.preview_import(
        path.read_bytes(),
        filename=path.name,
        dataset_name=identity.name,
        description=identity.description,
        version=identity.version,
        source=identity.source,
        privacy_status=identity.privacy_status,
        representativeness_statement=identity.representativeness_statement,
    )
    confirmed = service.confirm_import(preview.import_token, db_session)
    return DemoFixtureResult(
        status=DemoFixtureStatus.RESET if reset else DemoFixtureStatus.SEEDED,
        dataset_id=confirmed.dataset_id,
        conversation_count=confirmed.total_conversation_count,
    )


def _delete_demo_fixture_datasets(
    db_session: Session,
    datasets: list[Dataset],
) -> None:
    dataset_ids = [dataset.id for dataset in datasets]
    try:
        db_session.execute(
            delete(Conversation).where(Conversation.dataset_id.in_(dataset_ids))
        )
        db_session.execute(
            delete(Dataset).where(
                Dataset.id.in_(dataset_ids),
                Dataset.source == DatasetSource.FIXTURE_IMPORT.value,
            )
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed or reset one SupportLens Demo fixture through ImportService."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "reset"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("fixture", type=Path)
        command_parser.add_argument("--name", required=True)
        command_parser.add_argument("--description", required=True)
        command_parser.add_argument("--version", required=True)
        command_parser.add_argument(
            "--representativeness-statement",
            required=True,
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as db_session:
            result = seed_demo_fixture(
                args.fixture,
                name=args.name,
                description=args.description,
                version=args.version,
                representativeness_statement=args.representativeness_statement,
                db_session=db_session,
                reset=args.command == "reset",
            )
    except ImportFileValidationError as exc:
        errors = [
            {
                "field": error.field,
                "code": error.code,
                "message": error.message,
            }
            for error in exc.errors
        ]
        print(
            json.dumps({"status": "invalid_fixture", "errors": errors}),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValidationError) as exc:
        print(
            json.dumps({"status": "fixture_seed_failed", "message": str(exc)}),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": result.status,
                "dataset_id": str(result.dataset_id),
                "conversation_count": result.conversation_count,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
