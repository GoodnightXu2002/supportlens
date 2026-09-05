import json

import pytest

from app.failure_verifier import (
    FAILURE_VERIFIER_PROMPT_VERSION,
    assemble_failure_verifier_request,
    validate_failure_verifier_output,
)
from app.judge_contract import FailureMode, JudgeInput, JudgeOutput


def _judge_input() -> JudgeInput:
    return JudgeInput(
        case_id="CASE-VERIFIER-1",
        scenario="After-sales",
        messages=[
            {"role": "user", "content": "What should I do next?"},
            {"role": "assistant", "content": "Continue using the device."},
        ],
        business_context={"device_status": "damaged"},
        reference_evidence="Damaged devices must not be used.",
    )


def _primary_output() -> JudgeOutput:
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": "policy_procedure_violation",
            "secondary_flags": [],
            "problem": "The response gives a prohibited next step.",
            "severity": "high",
            "evidence": [],
            "uncertainty": None,
            "review_required": True,
            "rationale": "The response conflicts with the supplied procedure.",
        }
    )


def test_failure_verifier_request_uses_only_frozen_inputs_and_version() -> None:
    request = assemble_failure_verifier_request(
        _judge_input(),
        _primary_output(),
    )

    assert request.metadata == {
        "failure_verifier_prompt_version": "FAILURE-VERIFIER-PROMPT-V1"
    }
    assert FAILURE_VERIFIER_PROMPT_VERSION == "FAILURE-VERIFIER-PROMPT-V1"
    assert request.response_schema_name == "FailureVerifierOutput"
    assert request.response_schema["additionalProperties"] is False

    payload = json.loads(request.messages[1].content)
    assert set(payload["case"]) == {
        "messages",
        "business_context",
        "reference_evidence",
    }
    assert set(payload["primary_failure"]) == {
        "primary_failure_mode",
        "problem",
    }
    assert "case_id" not in request.messages[1].content
    assert "scenario" not in request.messages[1].content
    assert "gold" not in request.messages[1].content.lower()
    assert "benchmark" not in request.messages[1].content.lower()


def test_secondary_flags_are_deduplicated() -> None:
    output = validate_failure_verifier_output(
        {
            "severity": "medium",
            "secondary_flags": [
                "incorrect_information",
                "incorrect_information",
                "incomplete_unresolved",
            ],
        },
        primary_failure_mode=FailureMode.POLICY_PROCEDURE_VIOLATION,
    )

    assert output.secondary_flags == [
        FailureMode.INCORRECT_INFORMATION,
        FailureMode.INCOMPLETE_UNRESOLVED,
    ]


def test_secondary_flags_reject_primary_failure_mode() -> None:
    with pytest.raises(
        ValueError,
        match="must not contain the primary_failure_mode",
    ):
        validate_failure_verifier_output(
            {
                "severity": "medium",
                "secondary_flags": ["policy_procedure_violation"],
            },
            primary_failure_mode=FailureMode.POLICY_PROCEDURE_VIOLATION,
        )
