from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.judge_contract import FailureMode, JudgeInput, JudgeOutput, Severity
from app.judge_rules import judge_runtime_rules_prompt_payload
from app.llm_provider import (
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    ProviderMessage,
    ProviderMessageRole,
)

FAILURE_VERIFIER_PROMPT_VERSION = "FAILURE-VERIFIER-PROMPT-V1"
MAX_FAILURE_VERIFIER_ATTEMPTS = 2


class FailureVerifierOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    secondary_flags: list[FailureMode]

    @field_validator("secondary_flags")
    @classmethod
    def deduplicate_secondary_flags(
        cls, values: list[FailureMode]
    ) -> list[FailureMode]:
        return list(dict.fromkeys(values))


def assemble_failure_verifier_request(
    judge_input: JudgeInput,
    primary_output: JudgeOutput,
) -> LLMRequest:
    runtime_rules = judge_runtime_rules_prompt_payload()
    user_payload = {
        "case": {
            "messages": [
                message.model_dump(mode="json") for message in judge_input.messages
            ],
            "business_context": judge_input.business_context,
            "reference_evidence": judge_input.reference_evidence,
        },
        "primary_failure": {
            "primary_failure_mode": primary_output.primary_failure_mode,
            "problem": primary_output.problem,
        },
        "frozen_rules": {
            "failure_modes": runtime_rules["failure_modes"],
            "failure_mode_rules": runtime_rules["failure_mode_rules"],
            "severity_principle": runtime_rules["severity_principle"],
            "severity_evaluation_basis": runtime_rules[
                "severity_evaluation_basis"
            ],
            "severity_does_not_measure": runtime_rules[
                "severity_does_not_measure"
            ],
            "severity_definitions": runtime_rules["severity_definitions"],
            "severity_boundary_rules": runtime_rules["severity_boundary_rules"],
        },
        "failure_verifier_output_schema": (
            FailureVerifierOutput.model_json_schema()
        ),
    }
    return LLMRequest(
        messages=[
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content=(
                    "Verify only the case-level severity and independent secondary "
                    "failure modes for a primary judgment already fixed as failure. "
                    "Do not reconsider the judgment, primary_failure_mode, or problem. "
                    "Apply the supplied frozen severity contract semantically to the "
                    "current case; do not map keywords or scenario names to severity. "
                    "A secondary flag must represent a genuinely independent "
                    "additional failure, must not duplicate the primary_failure_mode, "
                    "and must not be repeated. Return only JSON matching the supplied "
                    "schema."
                ),
            ),
            ProviderMessage(
                role=ProviderMessageRole.USER,
                content=json.dumps(user_payload, ensure_ascii=False),
            ),
        ],
        response_schema_name="FailureVerifierOutput",
        response_schema=FailureVerifierOutput.model_json_schema(),
        metadata={
            "failure_verifier_prompt_version": FAILURE_VERIFIER_PROMPT_VERSION,
        },
    )


def validate_failure_verifier_output(
    payload: Any,
    *,
    primary_failure_mode: FailureMode | None,
) -> FailureVerifierOutput:
    output = FailureVerifierOutput.model_validate(payload)
    if (
        primary_failure_mode is not None
        and primary_failure_mode in output.secondary_flags
    ):
        raise ValueError(
            "secondary_flags must not contain the primary_failure_mode"
        )
    return output


def apply_failure_verifier(
    *,
    judge_input: JudgeInput,
    primary_output: JudgeOutput,
    provider: LLMProvider,
) -> JudgeOutput:
    request = assemble_failure_verifier_request(judge_input, primary_output)

    for attempt in range(1, MAX_FAILURE_VERIFIER_ATTEMPTS + 1):
        try:
            response = provider.complete(request)
            verifier_output = validate_failure_verifier_output(
                response.structured_payload,
                primary_failure_mode=primary_output.primary_failure_mode,
            )
        except LLMProviderError as error:
            if not error.retryable or attempt == MAX_FAILURE_VERIFIER_ATTEMPTS:
                return primary_output
            continue
        except (ValidationError, ValueError):
            if attempt == MAX_FAILURE_VERIFIER_ATTEMPTS:
                return primary_output
            continue

        return primary_output.model_copy(
            update={
                "severity": verifier_output.severity,
                "secondary_flags": verifier_output.secondary_flags,
            }
        )

    return primary_output
