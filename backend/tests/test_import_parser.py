import io
import json

import pytest

from app.import_parser import (
    MAX_FILE_SIZE_BYTES,
    ImportErrorCode,
    MessageRole,
    parse_import_file,
)


def _error_codes(result) -> set[ImportErrorCode]:
    return {error.code for error in result.errors}


def _valid_json_item(case_id: str = "CASE-001") -> dict:
    return {
        "case_id": case_id,
        "scenario": "returns",
        "messages": [
            {"role": "user", "content": "  Can I return this?  "},
            {"role": "assistant", "content": "Yes, within 30 days."},
        ],
    }


def test_valid_csv_is_normalized() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message,assistant_response\n"
        b"CASE-001,shipping,Where is my order?,It is on the way.\n",
        filename="cases.csv",
    )

    assert result.success is True
    assert result.total_conversation_count == 1
    assert result.errors == []
    conversation = result.conversations[0]
    assert conversation.external_id == "CASE-001"
    assert [message.role for message in conversation.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert [message.content for message in conversation.messages] == [
        "Where is my order?",
        "It is on the way.",
    ]
    assert conversation.metadata == {"scenario": "shipping"}


def test_csv_missing_required_column_fails_batch() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message\nCASE-001,shipping,Hello\n",
        filename="cases.csv",
    )

    assert result.success is False
    assert result.conversations == []
    assert result.errors[0].row == 1
    assert result.errors[0].field == "assistant_response"
    assert result.errors[0].code is ImportErrorCode.REQUIRED_FIELD_MISSING


def test_csv_empty_required_value_fails_batch() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message,assistant_response\n"
        b"CASE-001,shipping,   ,Response\n",
        filename="cases.csv",
    )

    assert result.success is False
    assert result.conversations == []
    assert result.errors[0].row == 2
    assert result.errors[0].field == "user_message"
    assert result.errors[0].code is ImportErrorCode.REQUIRED_VALUE_EMPTY


def test_csv_duplicate_case_id_fails_batch() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message,assistant_response\n"
        b"CASE-001,shipping,First,Response\n"
        b"CASE-001,returns,Second,Response\n",
        filename="cases.csv",
    )

    assert result.success is False
    assert result.conversations == []
    duplicate = next(
        error
        for error in result.errors
        if error.code is ImportErrorCode.DUPLICATE_CASE_ID
    )
    assert duplicate.row == 3
    assert duplicate.field == "case_id"


def test_csv_optional_fields_are_nested_in_metadata() -> None:
    csv_data = (
        "case_id,scenario,user_message,assistant_response,"
        "business_context,reference_evidence,metadata\n"
        'CASE-001,returns,Question,Answer,VIP customer,Policy 7,"{""tier"": 1}"\n'
    )

    result = parse_import_file(io.StringIO(csv_data), filename="cases.csv")

    assert result.success is True
    assert result.conversations[0].metadata == {
        "scenario": "returns",
        "business_context": "VIP customer",
        "reference_evidence": "Policy 7",
        "metadata": {"tier": 1},
    }


def test_csv_empty_metadata_is_not_provided() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message,assistant_response,metadata\n"
        b"CASE-001,returns,Question,Answer,\n",
        filename="cases.csv",
    )

    assert result.success is True
    assert result.conversations[0].metadata == {"scenario": "returns"}


@pytest.mark.parametrize("metadata", ["not-json", "[]", '"text"'])
def test_csv_metadata_must_be_a_serialized_json_object(metadata: str) -> None:
    csv_data = (
        "case_id,scenario,user_message,assistant_response,metadata\n"
        f"CASE-001,returns,Question,Answer,{metadata}\n"
    )

    result = parse_import_file(csv_data.encode(), filename="cases.csv")

    assert result.success is False
    assert result.conversations == []
    assert result.errors[0].row == 2
    assert result.errors[0].field == "metadata"
    assert result.errors[0].code is ImportErrorCode.INVALID_METADATA_SCHEMA


def test_empty_csv_dataset_is_invalid() -> None:
    result = parse_import_file(
        b"case_id,scenario,user_message,assistant_response\n",
        filename="cases.csv",
    )

    assert result.success is False
    assert _error_codes(result) == {ImportErrorCode.EMPTY_DATASET}


def test_valid_json_is_normalized_and_preserves_message_order_and_content() -> None:
    item = _valid_json_item()
    item.update(
        {
            "business_context": "VIP customer",
            "reference_evidence": {"policy": "returns"},
            "metadata": {"channel": "chat"},
        }
    )

    result = parse_import_file(
        json.dumps([item]).encode(),
        filename="cases.json",
    )

    assert result.success is True
    assert result.total_conversation_count == 1
    conversation = result.conversations[0]
    assert conversation.external_id == "CASE-001"
    assert [message.role for message in conversation.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert conversation.messages[0].content == "  Can I return this?  "
    assert conversation.metadata == {
        "scenario": "returns",
        "business_context": "VIP customer",
        "reference_evidence": {"policy": "returns"},
        "metadata": {"channel": "chat"},
    }


def test_json_document_wrapper_is_invalid() -> None:
    result = parse_import_file(
        json.dumps({"conversations": [_valid_json_item()]}).encode(),
        filename="cases.json",
    )

    assert result.success is False
    assert result.conversations == []
    assert _error_codes(result) == {ImportErrorCode.INVALID_JSON_SCHEMA}


def test_json_null_metadata_is_not_provided() -> None:
    item = _valid_json_item()
    item["metadata"] = None

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is True
    assert result.conversations[0].metadata == {"scenario": "returns"}


@pytest.mark.parametrize("metadata", ["text", [], [1], 1, True])
def test_json_metadata_must_be_an_object(metadata) -> None:
    item = _valid_json_item()
    item["metadata"] = metadata

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert result.conversations == []
    assert result.errors[0].item_index == 0
    assert result.errors[0].field == "metadata"
    assert result.errors[0].code is ImportErrorCode.INVALID_METADATA_SCHEMA


def test_malformed_json_is_invalid() -> None:
    result = parse_import_file(b"[{", filename="cases.json")

    assert result.success is False
    assert result.conversations == []
    assert _error_codes(result) == {ImportErrorCode.MALFORMED_JSON}


def test_json_missing_case_id_is_invalid() -> None:
    item = _valid_json_item()
    del item["case_id"]

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert result.errors[0].item_index == 0
    assert result.errors[0].field == "case_id"
    assert result.errors[0].code is ImportErrorCode.REQUIRED_FIELD_MISSING


@pytest.mark.parametrize("messages", ["not-an-array", {}, [], None])
def test_json_invalid_messages_type_or_empty_array_is_invalid(messages) -> None:
    item = _valid_json_item()
    item["messages"] = messages

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert result.conversations == []
    assert ImportErrorCode.INVALID_MESSAGE_SCHEMA in _error_codes(result)


@pytest.mark.parametrize(
    "message",
    [
        {"content": "Hello"},
        {"role": "user"},
    ],
)
def test_json_message_missing_role_or_content_is_invalid(message) -> None:
    item = _valid_json_item()
    item["messages"] = [
        message,
        {"role": "assistant", "content": "Response"},
    ]

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert ImportErrorCode.INVALID_MESSAGE_SCHEMA in _error_codes(result)


@pytest.mark.parametrize("role", ["User", "system", "tool", "developer"])
def test_json_unsupported_or_non_lowercase_role_is_invalid(role: str) -> None:
    item = _valid_json_item()
    item["messages"][0]["role"] = role

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert result.conversations == []
    assert ImportErrorCode.UNSUPPORTED_MESSAGE_ROLE in _error_codes(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", 1),
        ("content", 1),
    ],
)
def test_json_message_role_and_content_must_be_strings(field: str, value) -> None:
    item = _valid_json_item()
    item["messages"][0][field] = value

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert ImportErrorCode.INVALID_MESSAGE_SCHEMA in _error_codes(result)


def test_json_empty_message_content_is_invalid() -> None:
    item = _valid_json_item()
    item["messages"][1]["content"] = " \t "

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    content_error = next(
        error
        for error in result.errors
        if error.code is ImportErrorCode.REQUIRED_VALUE_EMPTY
    )
    assert content_error.field == "messages[1].content"


def test_json_missing_user_is_invalid() -> None:
    item = _valid_json_item()
    item["messages"] = [{"role": "assistant", "content": "Response"}]

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert ImportErrorCode.INVALID_MESSAGE_SCHEMA in _error_codes(result)
    assert any("user message" in error.message for error in result.errors)


def test_json_missing_assistant_is_invalid() -> None:
    item = _valid_json_item()
    item["messages"] = [{"role": "user", "content": "Question"}]

    result = parse_import_file(json.dumps([item]).encode(), filename="cases.json")

    assert result.success is False
    assert ImportErrorCode.INVALID_MESSAGE_SCHEMA in _error_codes(result)
    assert any("assistant message" in error.message for error in result.errors)


def test_json_duplicate_case_id_fails_batch() -> None:
    result = parse_import_file(
        json.dumps([_valid_json_item(), _valid_json_item()]).encode(),
        filename="cases.json",
    )

    assert result.success is False
    assert result.conversations == []
    duplicate = next(
        error
        for error in result.errors
        if error.code is ImportErrorCode.DUPLICATE_CASE_ID
    )
    assert duplicate.item_index == 1
    assert duplicate.field == "case_id"


def test_unsupported_file_extension_is_invalid() -> None:
    result = parse_import_file(b"anything", filename="cases.txt")

    assert result.success is False
    assert _error_codes(result) == {ImportErrorCode.UNSUPPORTED_FILE_TYPE}


def test_file_larger_than_five_mb_is_invalid() -> None:
    result = parse_import_file(
        b"x" * (MAX_FILE_SIZE_BYTES + 1),
        filename="cases.json",
    )

    assert result.success is False
    assert _error_codes(result) == {ImportErrorCode.FILE_TOO_LARGE}


@pytest.mark.parametrize("filename", ["cases.csv", "cases.json"])
def test_more_than_one_thousand_conversations_is_invalid(filename: str) -> None:
    if filename.endswith(".csv"):
        header = "case_id,scenario,user_message,assistant_response\n"
        rows = "".join(
            f"CASE-{index},scenario,Question,Answer\n" for index in range(1001)
        )
        data = (header + rows).encode()
    else:
        data = json.dumps(
            [_valid_json_item(f"CASE-{index}") for index in range(1001)]
        ).encode()

    result = parse_import_file(data, filename=filename)

    assert result.success is False
    assert result.conversations == []
    assert _error_codes(result) == {
        ImportErrorCode.CONVERSATION_LIMIT_EXCEEDED
    }
