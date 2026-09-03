from __future__ import annotations

import secrets
import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.import_parser import (
    FileData,
    ImportValidationError,
    NormalizedConversation,
    parse_import_file,
)
from app.models import Conversation, Dataset
from app.schemas import DatasetCreate, DatasetSource, PrivacyStatus

DEFAULT_IMPORT_TTL = timedelta(minutes=30)
MAX_PREVIEW_CONVERSATIONS = 20
IMPORT_TOKEN_BYTES = 32


class ImportServiceErrorCode(StrEnum):
    IMPORT_TOKEN_NOT_FOUND = "import_token_not_found"
    IMPORT_TOKEN_EXPIRED = "import_token_expired"
    DATASET_PERSISTENCE_FAILED = "dataset_persistence_failed"


class ImportServiceError(Exception):
    def __init__(self, code: ImportServiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ImportFileValidationError(Exception):
    def __init__(self, errors: list[ImportValidationError]) -> None:
        super().__init__("Import file validation failed.")
        self.errors = errors


class ImportSnapshot(BaseModel):
    dataset_identity: DatasetCreate
    conversations: list[NormalizedConversation]
    created_at: datetime
    expires_at: datetime


class ImportPreviewResult(BaseModel):
    import_token: str
    dataset_identity: DatasetCreate
    total_conversation_count: int
    scenario_distribution: dict[str, int]
    preview_conversations: list[NormalizedConversation]


class ImportConfirmResult(BaseModel):
    dataset_id: UUID
    conversation_ids: list[UUID]
    total_conversation_count: int


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ImportService:
    def __init__(
        self,
        *,
        snapshot_directory: Path | str | None = None,
        ttl: timedelta = DEFAULT_IMPORT_TTL,
        clock: Clock = _utc_now,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Import snapshot TTL must be positive.")

        default_directory = Path(tempfile.gettempdir()) / "supportlens-import-snapshots"
        self._snapshot_directory = Path(snapshot_directory or default_directory)
        self._snapshot_directory.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl
        self._clock = clock

    def preview_import(
        self,
        file_data: FileData,
        *,
        filename: str,
        dataset_name: str,
        description: str | None = None,
        version: str = "v1.0",
        source: DatasetSource | str,
        privacy_status: PrivacyStatus | str | None = None,
        representativeness_statement: str | None = None,
    ) -> ImportPreviewResult:
        identity_values: dict[str, Any] = {
            "name": dataset_name,
            "description": description,
            "version": version,
            "source": source,
            "representativeness_statement": representativeness_statement,
        }
        if privacy_status is not None:
            identity_values["privacy_status"] = privacy_status
        dataset_identity = DatasetCreate.model_validate(identity_values)

        parse_result = parse_import_file(file_data, filename=filename)
        if not parse_result.success:
            raise ImportFileValidationError(parse_result.errors)

        created_at = self._now()
        snapshot = ImportSnapshot(
            dataset_identity=dataset_identity,
            conversations=parse_result.conversations,
            created_at=created_at,
            expires_at=created_at + self._ttl,
        )
        import_token = self._create_token()
        self._snapshot_path(import_token).write_text(
            snapshot.model_dump_json(),
            encoding="utf-8",
        )

        scenario_distribution = Counter(
            conversation.metadata["scenario"]
            for conversation in parse_result.conversations
        )
        return ImportPreviewResult(
            import_token=import_token,
            dataset_identity=dataset_identity,
            total_conversation_count=parse_result.total_conversation_count,
            scenario_distribution=dict(scenario_distribution),
            preview_conversations=parse_result.conversations[
                :MAX_PREVIEW_CONVERSATIONS
            ],
        )

    def confirm_import(
        self,
        import_token: str,
        db_session: Session,
    ) -> ImportConfirmResult:
        snapshot = self._load_snapshot(import_token)
        identity = snapshot.dataset_identity
        dataset = Dataset(
            name=identity.name,
            description=identity.description,
            version=identity.version,
            source=identity.source.value,
            privacy_status=identity.privacy_status.value,
            representativeness_statement=identity.representativeness_statement,
        )
        dataset.conversations.extend(
            [
                Conversation(
                    external_id=conversation.external_id,
                    messages=[
                        message.model_dump(mode="json")
                        for message in conversation.messages
                    ],
                    metadata_=conversation.metadata,
                )
                for conversation in snapshot.conversations
            ]
        )

        try:
            db_session.add(dataset)
            db_session.flush()
            dataset_id = dataset.id
            conversation_ids = [
                conversation.id for conversation in dataset.conversations
            ]
            db_session.commit()
        except Exception as exc:
            db_session.rollback()
            raise ImportServiceError(
                ImportServiceErrorCode.DATASET_PERSISTENCE_FAILED,
                "Dataset import could not be persisted.",
            ) from exc

        self._snapshot_path(import_token).unlink(missing_ok=True)
        return ImportConfirmResult(
            dataset_id=dataset_id,
            conversation_ids=conversation_ids,
            total_conversation_count=len(conversation_ids),
        )

    def _create_token(self) -> str:
        while True:
            token = secrets.token_hex(IMPORT_TOKEN_BYTES)
            if not self._snapshot_path(token).exists():
                return token

    def _load_snapshot(self, import_token: str) -> ImportSnapshot:
        if len(import_token) != IMPORT_TOKEN_BYTES * 2 or any(
            character not in "0123456789abcdef" for character in import_token
        ):
            raise ImportServiceError(
                ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND,
                "Import token was not found.",
            )
        path = self._snapshot_path(import_token)
        if not path.is_file():
            raise ImportServiceError(
                ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND,
                "Import token was not found.",
            )

        try:
            snapshot = ImportSnapshot.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise ImportServiceError(
                ImportServiceErrorCode.IMPORT_TOKEN_NOT_FOUND,
                "Import token was not found.",
            ) from exc

        if self._now() >= snapshot.expires_at:
            path.unlink(missing_ok=True)
            raise ImportServiceError(
                ImportServiceErrorCode.IMPORT_TOKEN_EXPIRED,
                "Import token has expired.",
            )
        return snapshot

    def _snapshot_path(self, import_token: str) -> Path:
        return self._snapshot_directory / f"{import_token}.json"

    def _now(self) -> datetime:
        current_time = self._clock()
        if current_time.tzinfo is None:
            raise ValueError("Import service clock must return a timezone-aware value.")
        return current_time
