import json

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.judge_contract import (
    JUDGE_CONTRACT_VERSION,
    JUDGE_PROMPT_VERSION,
    JudgeInput,
    Judgment,
    validate_judge_output,
)
from app.judge_prompt import JudgePromptAssets, assemble_judge_request
from app.llm_provider import (
    DeepSeekProvider,
    LLMProviderError,
    LLMProviderErrorCode,
    LLMRequest,
    LLMResponse,
)


def _judge_input() -> JudgeInput:
    return JudgeInput(
        case_id="CASE-20",
        scenario="After-sales",
        messages=[
            {"role": "user", "content": "The device will not start."},
            {
                "role": "assistant",
                "content": "Please disconnect it and share the order number.",
            },
        ],
        business_context={"purchase_age_days": 20},
        reference_evidence=None,
    )


def _valid_payload() -> dict:
    return {
        "judgment": "success",
        "primary_failure_mode": None,
        "secondary_flags": [],
        "problem": None,
        "severity": None,
        "evidence": [
            {
                "evidence_type": "response",
                "content": "Please disconnect it and share the order number.",
                "source_ref": "messages[1]",
            }
        ],
        "uncertainty": None,
        "review_required": False,
        "rationale": "The response gives a safe and relevant next step.",
    }


class FakeProvider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            provider="fake",
            model="fake-judge",
            structured_payload=self.payload,
            request_id="fake-request-1",
        )


def test_prompt_assembly_uses_whitelisted_case_and_versioned_schema() -> None:
    request = assemble_judge_request(
        _judge_input(),
        assets=JudgePromptAssets(
            business_reference="BUSINESS-REFERENCE-ASSET",
        ),
    )

    assert request.metadata == {
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "judge_contract_version": JUDGE_CONTRACT_VERSION,
    }
    assert request.response_schema_name == "JudgeOutput"
    assert request.response_schema["additionalProperties"] is False
    payload = json.loads(request.messages[1].content)
    assert set(payload["case"]) == {
        "case_id",
        "scenario",
        "messages",
        "business_context",
        "reference_evidence",
    }
    assert payload["business_reference"] == "BUSINESS-REFERENCE-ASSET"
    assert payload["judge_runtime_rules"]["severity_rules_status"] == "ready"
    assert len(payload["judge_runtime_rules"]["severity_definitions"]) == 4
    assert payload["judge_runtime_rules"]["ready_for_execution"] is True
    assert "run_type" not in payload["case"]
    assert "gold" not in payload["case"]
    assert "target" not in payload["case"]


def test_fake_provider_payload_validates_as_judge_output() -> None:
    request = assemble_judge_request(
        _judge_input(),
        assets=JudgePromptAssets(business_reference="business reference"),
    )
    provider = FakeProvider(_valid_payload())

    response = provider.complete(request)
    output = validate_judge_output(response.structured_payload)

    assert output.judgment is Judgment.SUCCESS
    assert provider.requests == [request]


def test_fake_provider_malformed_payload_is_validation_error() -> None:
    request = assemble_judge_request(
        _judge_input(),
        assets=JudgePromptAssets(business_reference="business reference"),
    )
    provider = FakeProvider({"judgment": "success"})

    response = provider.complete(request)

    with pytest.raises(ValidationError):
        validate_judge_output(response.structured_payload)


def test_missing_deepseek_key_does_not_break_settings_or_app_import(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key is None

    from app.main import app

    assert app.title
    with pytest.raises(LLMProviderError) as exc_info:
        DeepSeekProvider(settings)
    assert exc_info.value.code is (
        LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR
    )


def test_deepseek_provider_configuration_does_not_make_a_request() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="secret-key",
        deepseek_base_url="https://deepseek.invalid",
        deepseek_model="test-model",
    )

    provider = DeepSeekProvider(settings)

    assert provider.base_url == "https://deepseek.invalid"
    assert provider.model == "test-model"
    assert provider._api_key.get_secret_value() == "secret-key"


@pytest.mark.parametrize("error_code", list(LLMProviderErrorCode))
def test_provider_error_codes_are_stable(error_code: LLMProviderErrorCode) -> None:
    error = LLMProviderError(error_code, "safe provider error")

    assert error.code is error_code
    assert str(error) == "safe provider error"
