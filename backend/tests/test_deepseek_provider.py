import json

import httpx
import pytest

from app.config import Settings
from app.judge_contract import JudgeInput
from app.judge_prompt import JudgePromptAssets, assemble_judge_request
from app.llm_provider import (
    DeepSeekProvider,
    LLMProviderError,
    LLMProviderErrorCode,
)

TEST_API_KEY = "test-only-api-key"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        deepseek_api_key=TEST_API_KEY,
        deepseek_base_url="https://deepseek.invalid/v1",
        deepseek_model="deepseek-v4-pro",
    )


def _request():
    judge_input = JudgeInput(
        case_id="CASE-PROVIDER-1",
        scenario="Refund",
        messages=[
            {"role": "user", "content": "When will my refund arrive?"},
            {
                "role": "assistant",
                "content": "It returns to the original payment method.",
            },
        ],
        reference_evidence="Refunds return to the original payment method.",
    )
    return assemble_judge_request(
        judge_input,
        assets=JudgePromptAssets(
            business_reference="Use the supplied refund policy."
        ),
    )


def _valid_judge_payload() -> dict:
    return {
        "judgment": "success",
        "primary_failure_mode": None,
        "secondary_flags": [],
        "problem": None,
        "severity": None,
        "evidence": [
            {
                "evidence_type": "response",
                "content": "It returns to the original payment method.",
                "source_ref": "messages[1]",
            }
        ],
        "uncertainty": None,
        "review_required": False,
        "rationale": "The response is consistent with the supplied policy.",
    }


def _success_response() -> dict:
    return {
        "id": "response-1",
        "choices": [
            {
                "message": {
                    "content": json.dumps(_valid_judge_payload()),
                    "reasoning_content": "must-not-be-retained",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }


def test_deepseek_request_contract_and_success_extraction() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success_response())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(_settings(), client=client)

    response = provider.complete(_request())

    assert captured["url"] == "https://deepseek.invalid/v1/chat/completions"
    assert captured["authorization"] == f"Bearer {TEST_API_KEY}"
    assert captured["payload"]["model"] == "deepseek-v4-pro"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    prompt_text = "\n".join(
        message["content"] for message in captured["payload"]["messages"]
    )
    assert "judge_output_example" in prompt_text
    assert "judge_output_schema" in prompt_text
    assert response.structured_payload == _valid_judge_payload()
    assert response.request_id == "response-1"
    assert response.token_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    assert response.raw_response is None
    assert "reasoning_content" not in response.model_dump_json()


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR, False),
        (400, LLMProviderErrorCode.PROVIDER_HTTP_ERROR, False),
        (429, LLMProviderErrorCode.PROVIDER_HTTP_ERROR, True),
        (500, LLMProviderErrorCode.PROVIDER_HTTP_ERROR, True),
    ],
)
def test_http_errors_are_normalized(
    status_code: int,
    expected_code: LLMProviderErrorCode,
    retryable: bool,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"secret": "body"})
        )
    )
    provider = DeepSeekProvider(_settings(), client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_request())

    assert exc_info.value.code is expected_code
    assert exc_info.value.status_code == status_code
    assert exc_info.value.retryable is retryable
    assert TEST_API_KEY not in str(exc_info.value)
    assert "body" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("transport_error", "expected_code"),
    [
        (httpx.ReadTimeout("timeout"), LLMProviderErrorCode.TIMEOUT),
        (httpx.ConnectError("network"), LLMProviderErrorCode.TRANSPORT_ERROR),
    ],
)
def test_transport_errors_are_normalized(
    transport_error: httpx.TransportError,
    expected_code: LLMProviderErrorCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        transport_error.request = request
        raise transport_error

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(_settings(), client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_request())

    assert exc_info.value.code is expected_code
    assert exc_info.value.retryable is True
    assert TEST_API_KEY not in str(exc_info.value)


@pytest.mark.parametrize(
    "response_payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": "[]"}}]},
    ],
)
def test_malformed_deepseek_response_is_rejected(response_payload) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=response_payload)
        )
    )
    provider = DeepSeekProvider(_settings(), client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_request())

    assert exc_info.value.code is LLMProviderErrorCode.MALFORMED_RESPONSE
    assert exc_info.value.retryable is True


def test_non_object_http_json_is_malformed_response() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=[])
        )
    )
    provider = DeepSeekProvider(_settings(), client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete(_request())

    assert exc_info.value.code is LLMProviderErrorCode.MALFORMED_RESPONSE

