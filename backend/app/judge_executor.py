from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.judge_contract import (
    JUDGE_CONTRACT_VERSION,
    JudgeOutput,
    assemble_judge_input,
    validate_judge_output,
)
from app.judge_prompt import (
    JUDGE_PROMPT_VERSION,
    JudgePromptAssets,
    assemble_judge_request,
)
from app.judge_rules import require_judge_rules_ready_for_execution
from app.llm_provider import (
    LLMProvider,
    LLMProviderError,
    LLMProviderErrorCode,
)
from app.models import Conversation

MAX_JUDGE_ATTEMPTS = 2


class JudgeExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    contract_version: str
    attempts: int
    output: JudgeOutput
    provider_response_id: str | None
    token_usage: dict[str, int] | None
    raw_json_text: str
    raw_judge_output: dict[str, Any]


class JudgeExecutionError(RuntimeError):
    def __init__(
        self,
        *,
        attempts: int,
        error_code: str,
        raw_judge_output: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Judge execution failed after {attempts} attempt(s).")
        self.attempts = attempts
        self.error_code = error_code
        self.raw_judge_output = raw_judge_output


def execute_judge(
    conversation: Conversation,
    *,
    business_reference: str,
    provider: LLMProvider,
) -> JudgeExecutionResult:
    require_judge_rules_ready_for_execution()
    judge_input = assemble_judge_input(conversation)
    request = assemble_judge_request(
        judge_input,
        assets=JudgePromptAssets(business_reference=business_reference),
    )

    last_raw_judge_output: dict[str, Any] | None = None
    for attempt in range(1, MAX_JUDGE_ATTEMPTS + 1):
        try:
            response = provider.complete(request)
            last_raw_judge_output = response.structured_payload
            output = validate_judge_output(response.structured_payload)
        except LLMProviderError as error:
            if not error.retryable or attempt == MAX_JUDGE_ATTEMPTS:
                raise JudgeExecutionError(
                    attempts=attempt,
                    error_code=error.code.value,
                    raw_judge_output=last_raw_judge_output,
                ) from error
            continue
        except ValidationError as error:
            if attempt == MAX_JUDGE_ATTEMPTS:
                raise JudgeExecutionError(
                    attempts=attempt,
                    error_code="judge_output_invalid",
                    raw_judge_output=response.structured_payload,
                ) from error
            continue

        return JudgeExecutionResult(
            provider=response.provider,
            model=response.model,
            prompt_version=JUDGE_PROMPT_VERSION,
            contract_version=JUDGE_CONTRACT_VERSION,
            attempts=attempt,
            output=output,
            provider_response_id=response.request_id,
            token_usage=response.token_usage,
            raw_json_text=response.raw_json_text,
            raw_judge_output=response.structured_payload,
        )

    raise JudgeExecutionError(
        attempts=MAX_JUDGE_ATTEMPTS,
        error_code=LLMProviderErrorCode.MALFORMED_RESPONSE.value,
        raw_judge_output=last_raw_judge_output,
    )
