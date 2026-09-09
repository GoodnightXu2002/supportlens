import json

import pytest

from app.judge_contract import JUDGE_CONTRACT_VERSION
from app.judge_executor import JudgeExecutionError, execute_judge
from app.judge_prompt import JUDGE_PROMPT_VERSION
from app.llm_provider import (
    LLMProviderError,
    LLMProviderErrorCode,
    LLMRequest,
    LLMResponse,
)
from app.models import Conversation


def _conversation() -> Conversation:
    return Conversation(
        external_id="CASE-EXECUTOR-1",
        messages=[
            {"role": "user", "content": "Where is my order?"},
            {
                "role": "assistant",
                "content": "The latest scan is at the regional hub.",
            },
        ],
        metadata_={
            "scenario": "Logistics",
            "business_context": {"status": "in_transit"},
            "reference_evidence": {"latest_scan": "regional hub"},
        },
    )


def _payload(judgment: str = "success") -> dict:
    is_failure = judgment == "failure"
    return {
        "judgment": judgment,
        "primary_failure_mode": "other" if is_failure else None,
        "secondary_flags": [],
        "problem": "A quality failure." if is_failure else None,
        "severity": "low" if is_failure else None,
        "evidence": [],
        "uncertainty": (
            "Evidence is insufficient." if judgment == "uncertain" else None
        ),
        "review_required": False,
        "rationale": "Concise evidence-grounded judgment.",
    }


def _response(payload: dict, *, request_id: str = "response-1") -> LLMResponse:
    return LLMResponse(
        provider="fake",
        model="deepseek-v4-pro",
        structured_payload=payload,
        raw_json_text=json.dumps(payload),
        request_id=request_id,
        token_usage={"total_tokens": 10},
    )


class ScriptedProvider:
    model = "deepseek-v4-pro"

    def __init__(self, outcomes: list[LLMResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self.outcomes[len(self.requests) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_structured_validation_failure_retries_once_with_frozen_request() -> None:
    provider = ScriptedProvider(
        [
            _response({"judgment": "success"}, request_id="bad-response"),
            _response(_payload(), request_id="good-response"),
        ]
    )

    result = execute_judge(
        _conversation(),
        business_reference="Use the supplied tracking evidence.",
        provider=provider,
    )

    assert result.attempts == 2
    assert result.provider_response_id == "good-response"
    assert len(provider.requests) == 2
    assert provider.requests[0] is provider.requests[1]
    assert provider.requests[0].metadata == {
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "judge_contract_version": JUDGE_CONTRACT_VERSION,
    }
    assert JUDGE_PROMPT_VERSION == "JUDGE-PROMPT-V1.5"
    assert result.prompt_version == provider.requests[0].metadata[
        "judge_prompt_version"
    ]


def test_timeout_retries_once_then_succeeds() -> None:
    provider = ScriptedProvider(
        [
            LLMProviderError(
                LLMProviderErrorCode.TIMEOUT,
                "safe timeout",
                retryable=True,
            ),
            _response(_payload()),
        ]
    )

    result = execute_judge(
        _conversation(),
        business_reference="tracking reference",
        provider=provider,
    )

    assert result.attempts == 2
    assert provider.requests[0] is provider.requests[1]


def test_two_retryable_failures_return_final_execution_failure() -> None:
    provider = ScriptedProvider(
        [
            LLMProviderError(
                LLMProviderErrorCode.TRANSPORT_ERROR,
                "safe transport failure",
                retryable=True,
            ),
            LLMProviderError(
                LLMProviderErrorCode.TRANSPORT_ERROR,
                "safe transport failure",
                retryable=True,
            ),
        ]
    )

    with pytest.raises(JudgeExecutionError) as exc_info:
        execute_judge(
            _conversation(),
            business_reference="tracking reference",
            provider=provider,
        )

    assert exc_info.value.attempts == 2
    assert exc_info.value.error_code == "transport_error"
    assert len(provider.requests) == 2


def test_non_retryable_provider_error_stops_after_one_attempt() -> None:
    provider = ScriptedProvider(
        [
            LLMProviderError(
                LLMProviderErrorCode.AUTHENTICATION_CONFIG_ERROR,
                "safe authentication failure",
            )
        ]
    )

    with pytest.raises(JudgeExecutionError) as exc_info:
        execute_judge(
            _conversation(),
            business_reference="tracking reference",
            provider=provider,
        )

    assert exc_info.value.attempts == 1
    assert len(provider.requests) == 1


@pytest.mark.parametrize("judgment", ["failure", "uncertain"])
def test_valid_quality_judgment_is_never_retried(judgment: str) -> None:
    provider = ScriptedProvider([_response(_payload(judgment))])

    result = execute_judge(
        _conversation(),
        business_reference="tracking reference",
        provider=provider,
    )

    assert result.attempts == 1
    assert result.output.judgment.value == judgment
    assert len(provider.requests) == 1


def test_two_invalid_outputs_fail_with_stable_execution_error() -> None:
    provider = ScriptedProvider(
        [
            _response({"judgment": "failure"}),
            _response({"judgment": "failure"}),
        ]
    )

    with pytest.raises(JudgeExecutionError) as exc_info:
        execute_judge(
            _conversation(),
            business_reference="tracking reference",
            provider=provider,
        )

    assert exc_info.value.attempts == 2
    assert exc_info.value.error_code == "judge_output_invalid"


def test_failure_preserves_last_available_raw_judge_output() -> None:
    invalid_payload = {"judgment": "success"}
    provider = ScriptedProvider(
        [
            _response(invalid_payload),
            LLMProviderError(
                LLMProviderErrorCode.TRANSPORT_ERROR,
                "safe transport failure",
                retryable=True,
            ),
        ]
    )

    with pytest.raises(JudgeExecutionError) as exc_info:
        execute_judge(
            _conversation(),
            business_reference="tracking reference",
            provider=provider,
        )

    assert exc_info.value.raw_judge_output == invalid_payload
