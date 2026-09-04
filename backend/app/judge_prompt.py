from __future__ import annotations

import json
from dataclasses import dataclass

from app.judge_contract import (
    JUDGE_CONTRACT_VERSION,
    JUDGE_PROMPT_VERSION,
    EvidenceType,
    FailureMode,
    JudgeInput,
    JudgeOutput,
    Judgment,
    Severity,
)
from app.judge_rules import judge_runtime_rules_prompt_payload
from app.llm_provider import LLMRequest, ProviderMessage, ProviderMessageRole


@dataclass(frozen=True)
class JudgePromptAssets:
    business_reference: str
    severity_rules: str | None = None


def assemble_judge_request(
    judge_input: JudgeInput,
    *,
    assets: JudgePromptAssets,
) -> LLMRequest:
    system_prompt = "\n".join(
        [
            "Evaluate one support conversation using only the supplied case input "
            "and frozen evaluation assets.",
            "Return only structured JSON matching the supplied response schema.",
            "Do not provide chain-of-thought. Keep rationale concise.",
            f"Judgment values: {', '.join(Judgment)}.",
            f"Failure mode values: {', '.join(FailureMode)}.",
            f"Severity values: {', '.join(Severity)}.",
            f"Evidence type values: {', '.join(EvidenceType)}.",
            "Do not invent reference evidence that is absent from the case input.",
            "Schema, input, and provider errors are execution errors, not judgments.",
            "Use no context beyond the supplied case and rule assets.",
        ]
    )
    user_payload = {
        "case": judge_input.model_dump(mode="json"),
        "judge_runtime_rules": judge_runtime_rules_prompt_payload(),
        "business_reference": assets.business_reference,
        "severity_rules": assets.severity_rules,
    }
    return LLMRequest(
        messages=[
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content=system_prompt,
            ),
            ProviderMessage(
                role=ProviderMessageRole.USER,
                content=json.dumps(user_payload, ensure_ascii=False),
            ),
        ],
        response_schema_name="JudgeOutput",
        response_schema=JudgeOutput.model_json_schema(),
        metadata={
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_contract_version": JUDGE_CONTRACT_VERSION,
        },
    )
