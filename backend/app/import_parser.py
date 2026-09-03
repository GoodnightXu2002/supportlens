from __future__ import annotations

import csv
import io
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from pydantic import BaseModel, Field

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
MAX_CONVERSATIONS = 1000

CSV_REQUIRED_FIELDS = (
    "case_id",
    "scenario",
    "user_message",
    "assistant_response",
)
OPTIONAL_METADATA_FIELDS = (
    "business_context",
    "reference_evidence",
    "metadata",
)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ImportErrorCode(StrEnum):
    REQUIRED_FIELD_MISSING = "required_field_missing"
    REQUIRED_VALUE_EMPTY = "required_value_empty"
    DUPLICATE_CASE_ID = "duplicate_case_id"
    INVALID_MESSAGE_SCHEMA = "invalid_message_schema"
    UNSUPPORTED_MESSAGE_ROLE = "unsupported_message_role"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_TOO_LARGE = "file_too_large"
    CONVERSATION_LIMIT_EXCEEDED = "conversation_limit_exceeded"
    EMPTY_DATASET = "empty_dataset"
    MALFORMED_CSV = "malformed_csv"
    MALFORMED_JSON = "malformed_json"
    INVALID_JSON_SCHEMA = "invalid_json_schema"
    INVALID_METADATA_SCHEMA = "invalid_metadata_schema"
    INVALID_FILE_ENCODING = "invalid_file_encoding"


class ImportValidationError(BaseModel):
    row: int | None = None
    item_index: int | None = None
    field: str
    code: ImportErrorCode
    message: str


class NormalizedMessage(BaseModel):
    role: MessageRole
    content: str


class NormalizedConversation(BaseModel):
    external_id: str
    messages: list[NormalizedMessage]
    metadata: dict[str, Any]


class ImportParseResult(BaseModel):
    success: bool
    total_conversation_count: int = Field(ge=0)
    conversations: list[NormalizedConversation]
    errors: list[ImportValidationError]


FileData = bytes | bytearray | memoryview | BinaryIO | TextIO


def parse_import_file(data: FileData, *, filename: str) -> ImportParseResult:
    """Parse and validate a CSV or JSON dataset without persistence side effects."""
    file_type = Path(filename).suffix.lower()
    if file_type not in {".csv", ".json"}:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.UNSUPPORTED_FILE_TYPE,
                message="Only CSV and JSON files are supported.",
            )
        )

    payload = _read_file_data(data)
    if len(payload) > MAX_FILE_SIZE_BYTES:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.FILE_TOO_LARGE,
                message="File exceeds the 5 MB size limit.",
            )
        )

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.INVALID_FILE_ENCODING,
                message="File must be UTF-8 encoded.",
            )
        )

    if file_type == ".csv":
        return _parse_csv(text)
    return _parse_json(text)


def _read_file_data(data: FileData) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)

    value = data.read()
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    raise TypeError("file-like data must return str or bytes")


def _parse_csv(text: str) -> ImportParseResult:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            return _failure(
                _error(
                    row=1,
                    field="header",
                    code=ImportErrorCode.REQUIRED_FIELD_MISSING,
                    message="CSV header row is required.",
                )
            )

        missing_fields = [
            field for field in CSV_REQUIRED_FIELDS if field not in fieldnames
        ]
        if missing_fields:
            return _failure(
                *[
                    _error(
                        row=1,
                        field=field,
                        code=ImportErrorCode.REQUIRED_FIELD_MISSING,
                        message=f"Required CSV column '{field}' is missing.",
                    )
                    for field in missing_fields
                ]
            )

        rows = list(reader)
    except csv.Error as exc:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.MALFORMED_CSV,
                message=f"Malformed CSV: {exc}.",
            )
        )

    if not rows:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.EMPTY_DATASET,
                message="Dataset must contain at least one conversation.",
            )
        )
    if len(rows) > MAX_CONVERSATIONS:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.CONVERSATION_LIMIT_EXCEEDED,
                message="Dataset exceeds the 1000 conversation limit.",
            )
        )

    errors: list[ImportValidationError] = []
    conversations: list[NormalizedConversation] = []
    first_case_rows: dict[str, int] = {}

    for row_number, row in enumerate(rows, start=2):
        for field in CSV_REQUIRED_FIELDS:
            if _is_empty(row.get(field)):
                errors.append(
                    _error(
                        row=row_number,
                        field=field,
                        code=ImportErrorCode.REQUIRED_VALUE_EMPTY,
                        message=f"Required value '{field}' must not be empty.",
                    )
                )

        case_id = row.get("case_id")
        if not _is_empty(case_id):
            assert case_id is not None
            if case_id in first_case_rows:
                errors.append(
                    _error(
                        row=row_number,
                        field="case_id",
                        code=ImportErrorCode.DUPLICATE_CASE_ID,
                        message=(
                            f"Duplicate case_id '{case_id}'; first seen at row "
                            f"{first_case_rows[case_id]}."
                        ),
                    )
                )
            else:
                first_case_rows[case_id] = row_number

        if any(_is_empty(row.get(field)) for field in CSV_REQUIRED_FIELDS):
            continue

        assert case_id is not None
        scenario = row["scenario"]
        user_message = row["user_message"]
        assistant_response = row["assistant_response"]
        assert scenario is not None
        assert user_message is not None
        assert assistant_response is not None

        parsed_metadata: dict[str, Any] | None = None
        metadata_value = row.get("metadata")
        if not _is_empty(metadata_value):
            assert metadata_value is not None
            try:
                decoded_metadata = json.loads(metadata_value)
            except json.JSONDecodeError:
                errors.append(
                    _error(
                        row=row_number,
                        field="metadata",
                        code=ImportErrorCode.INVALID_METADATA_SCHEMA,
                        message="CSV metadata must be a serialized JSON object.",
                    )
                )
                continue
            if not isinstance(decoded_metadata, dict):
                errors.append(
                    _error(
                        row=row_number,
                        field="metadata",
                        code=ImportErrorCode.INVALID_METADATA_SCHEMA,
                        message="CSV metadata must decode to a JSON object.",
                    )
                )
                continue
            parsed_metadata = decoded_metadata

        metadata: dict[str, Any] = {"scenario": scenario}
        for field in ("business_context", "reference_evidence"):
            if field in row and not _is_empty(row[field]):
                metadata[field] = row[field]
        if parsed_metadata is not None:
            metadata["metadata"] = parsed_metadata

        conversations.append(
            NormalizedConversation(
                external_id=case_id,
                messages=[
                    NormalizedMessage(
                        role=MessageRole.USER,
                        content=user_message,
                    ),
                    NormalizedMessage(
                        role=MessageRole.ASSISTANT,
                        content=assistant_response,
                    ),
                ],
                metadata=metadata,
            )
        )

    if errors:
        return _failure(*errors)
    return _success(conversations)


def _parse_json(text: str) -> ImportParseResult:
    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.MALFORMED_JSON,
                message=f"Malformed JSON at line {exc.lineno}, column {exc.colno}.",
            )
        )

    if not isinstance(items, list):
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.INVALID_JSON_SCHEMA,
                message="JSON dataset must be an array of conversations.",
            )
        )
    if not items:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.EMPTY_DATASET,
                message="Dataset must contain at least one conversation.",
            )
        )
    if len(items) > MAX_CONVERSATIONS:
        return _failure(
            _error(
                field="file",
                code=ImportErrorCode.CONVERSATION_LIMIT_EXCEEDED,
                message="Dataset exceeds the 1000 conversation limit.",
            )
        )

    errors: list[ImportValidationError] = []
    conversations: list[NormalizedConversation] = []
    first_case_items: dict[str, int] = {}

    for item_index, item in enumerate(items):
        item_errors, conversation = _validate_json_item(item, item_index)
        errors.extend(item_errors)

        if isinstance(item, dict):
            case_id = item.get("case_id")
            if isinstance(case_id, str) and case_id.strip():
                if case_id in first_case_items:
                    errors.append(
                        _error(
                            item_index=item_index,
                            field="case_id",
                            code=ImportErrorCode.DUPLICATE_CASE_ID,
                            message=(
                                f"Duplicate case_id '{case_id}'; first seen at item "
                                f"{first_case_items[case_id]}."
                            ),
                        )
                    )
                else:
                    first_case_items[case_id] = item_index

        if conversation is not None:
            conversations.append(conversation)

    if errors:
        return _failure(*errors)
    return _success(conversations)


def _validate_json_item(
    item: Any, item_index: int
) -> tuple[list[ImportValidationError], NormalizedConversation | None]:
    if not isinstance(item, dict):
        return [
            _error(
                item_index=item_index,
                field="item",
                code=ImportErrorCode.INVALID_JSON_SCHEMA,
                message="Conversation item must be an object.",
            )
        ], None

    errors: list[ImportValidationError] = []
    for field in ("case_id", "scenario", "messages"):
        if field not in item:
            errors.append(
                _error(
                    item_index=item_index,
                    field=field,
                    code=ImportErrorCode.REQUIRED_FIELD_MISSING,
                    message=f"Required field '{field}' is missing.",
                )
            )

    for field in ("case_id", "scenario"):
        if field in item and (
            not isinstance(item[field], str) or not item[field].strip()
        ):
            errors.append(
                _error(
                    item_index=item_index,
                    field=field,
                    code=ImportErrorCode.REQUIRED_VALUE_EMPTY,
                    message=f"Required value '{field}' must be a non-empty string.",
                )
            )

    messages = item.get("messages")
    normalized_messages: list[NormalizedMessage] = []
    if "messages" in item:
        message_errors, normalized_messages = _validate_messages(
            messages, item_index
        )
        errors.extend(message_errors)

    item_metadata = item.get("metadata")
    if item_metadata is not None and not isinstance(item_metadata, dict):
        errors.append(
            _error(
                item_index=item_index,
                field="metadata",
                code=ImportErrorCode.INVALID_METADATA_SCHEMA,
                message="JSON metadata must be an object when provided.",
            )
        )

    if errors:
        return errors, None

    metadata: dict[str, Any] = {"scenario": item["scenario"]}
    for field in ("business_context", "reference_evidence"):
        if field in item:
            metadata[field] = item[field]
    if item_metadata is not None:
        metadata["metadata"] = item_metadata

    return [], NormalizedConversation(
        external_id=item["case_id"],
        messages=normalized_messages,
        metadata=metadata,
    )


def _validate_messages(
    messages: Any, item_index: int
) -> tuple[list[ImportValidationError], list[NormalizedMessage]]:
    if not isinstance(messages, list) or not messages:
        return [
            _error(
                item_index=item_index,
                field="messages",
                code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                message="messages must be a non-empty array.",
            )
        ], []

    errors: list[ImportValidationError] = []
    normalized: list[NormalizedMessage] = []
    roles: set[MessageRole] = set()

    for message_index, message in enumerate(messages):
        field_prefix = f"messages[{message_index}]"
        if not isinstance(message, dict):
            errors.append(
                _error(
                    item_index=item_index,
                    field=field_prefix,
                    code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                    message="Message must be an object with role and content.",
                )
            )
            continue
        if "role" not in message or "content" not in message:
            errors.append(
                _error(
                    item_index=item_index,
                    field=field_prefix,
                    code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                    message="Message must contain role and content.",
                )
            )
            continue

        role = message["role"]
        content = message["content"]
        if not isinstance(role, str):
            errors.append(
                _error(
                    item_index=item_index,
                    field=f"{field_prefix}.role",
                    code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                    message="Message role must be a string.",
                )
            )
        elif role not in {MessageRole.USER.value, MessageRole.ASSISTANT.value}:
            errors.append(
                _error(
                    item_index=item_index,
                    field=f"{field_prefix}.role",
                    code=ImportErrorCode.UNSUPPORTED_MESSAGE_ROLE,
                    message=f"Unsupported message role '{role}'.",
                )
            )

        if not isinstance(content, str):
            errors.append(
                _error(
                    item_index=item_index,
                    field=f"{field_prefix}.content",
                    code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                    message="Message content must be a string.",
                )
            )
        elif not content.strip():
            errors.append(
                _error(
                    item_index=item_index,
                    field=f"{field_prefix}.content",
                    code=ImportErrorCode.REQUIRED_VALUE_EMPTY,
                    message="Message content must not be empty.",
                )
            )

        if (
            isinstance(role, str)
            and role in {MessageRole.USER.value, MessageRole.ASSISTANT.value}
            and isinstance(content, str)
            and content.strip()
        ):
            normalized_role = MessageRole(role)
            roles.add(normalized_role)
            normalized.append(
                NormalizedMessage(role=normalized_role, content=content)
            )

    for required_role in (MessageRole.USER, MessageRole.ASSISTANT):
        if required_role not in roles:
            errors.append(
                _error(
                    item_index=item_index,
                    field="messages",
                    code=ImportErrorCode.INVALID_MESSAGE_SCHEMA,
                    message=(
                        f"messages must contain at least one "
                        f"{required_role.value} message."
                    ),
                )
            )

    return errors, normalized


def _is_empty(value: str | None) -> bool:
    return value is None or not value.strip()


def _error(
    *,
    field: str,
    code: ImportErrorCode,
    message: str,
    row: int | None = None,
    item_index: int | None = None,
) -> ImportValidationError:
    return ImportValidationError(
        row=row,
        item_index=item_index,
        field=field,
        code=code,
        message=message,
    )


def _failure(*errors: ImportValidationError) -> ImportParseResult:
    return ImportParseResult(
        success=False,
        total_conversation_count=0,
        conversations=[],
        errors=list(errors),
    )


def _success(
    conversations: list[NormalizedConversation],
) -> ImportParseResult:
    return ImportParseResult(
        success=True,
        total_conversation_count=len(conversations),
        conversations=conversations,
        errors=[],
    )
