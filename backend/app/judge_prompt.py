from __future__ import annotations

import json
from dataclasses import dataclass

from app.judge_contract import (
    JUDGE_CONTRACT_VERSION,
    EvidenceType,
    FailureMode,
    JudgeInput,
    JudgeOutput,
    Judgment,
    Severity,
)
from app.judge_rules import judge_runtime_rules_prompt_payload
from app.llm_provider import LLMRequest, ProviderMessage, ProviderMessageRole

JUDGE_PROMPT_VERSION = "JUDGE-PROMPT-V1.5"

JUDGE_OUTPUT_EXAMPLE = {
    "judgment": "success",
    "primary_failure_mode": None,
    "secondary_flags": [],
    "problem": None,
    "severity": None,
    "evidence": [
        {
            "evidence_type": "response",
            "content": "从助手回复中逐字复制的可追溯原文片段。",
            "source_ref": "assistant_response",
        }
    ],
    "uncertainty": None,
    "review_required": False,
    "rationale": "基于所提供证据的简明说明。",
}


@dataclass(frozen=True)
class JudgePromptAssets:
    business_reference: str


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
            "The response must be one JSON object with every required key.",
            "Do not provide chain-of-thought. Keep rationale concise.",
            "Write every non-null problem and uncertainty value, and every rationale "
            "value, in Simplified Chinese.",
            "Keep the JSON schema and field names unchanged. Keep judgment, "
            "primary_failure_mode, secondary_flags, severity, evidence_type, "
            "source_ref, and review_required as the contract values defined by the "
            "response schema; do not translate them.",
            f"Judgment values: {', '.join(Judgment)}.",
            f"Failure mode values: {', '.join(FailureMode)}.",
            f"Severity values: {', '.join(Severity)}.",
            f"Evidence type values: {', '.join(EvidenceType)}.",
            "Before returning JSON, self-check the judgment and severity invariant: "
            "success, warning, and uncertain each require severity=null. Only failure "
            "allows severity=low, medium, high, or critical. Never assign a severity "
            "grade to a warning.",
            "Treat the supplied judge_runtime_rules as authoritative. The following "
            "instructions clarify those frozen rules without adding business rules.",
            "Decide warning versus failure by whether relying on the response would "
            "produce a materially wrong result or action for the user.",
            "Use warning when the core response remains usable or advances the task, "
            "does not directly cause a clearly wrong or high-impact action, and its "
            "main issue is an optional next step omitted, mild overcommitment, weak "
            "qualification, or localized precision gap.",
            "Use failure when the core task is actually unresolved, relying on the "
            "response would cause a materially wrong action, or a core fact, rights "
            "outcome, or process conclusion is explicitly wrong.",
            "When the supplied context already contains the information required to "
            "complete the task, but the response repeats requests for that information "
            "and refuses to continue so the core task remains wholly unresolved, use "
            "failure with primary_failure_mode=incomplete_unresolved.",
            "Do not automatically make every difference from reference evidence a "
            "failure, and do not make a safety-related topic a failure by itself. "
            "Assess the response's actual action and material risk against the frozen "
            "failure threshold.",
            "In a safety-sensitive case involving children, newborns, food, drinking "
            "water, batteries, or comparable risk, use failure when the response gives "
            "an unsupported safety assurance, encourages continued use or consumption, "
            "or omits an explicit high-risk stop action, and that guidance could alter "
            "the user's behavior.",
            "For a failure, assign severity only from the frozen case-level impact "
            "definitions and the impact and recoverability in this case.",
            "Failure frequency, how obvious the error is, model confidence, and the "
            "strength of review need do not increase severity. Insufficient evidence "
            "must not increase severity.",
            "Keep medium for materially delayed or wrong but usually recoverable "
            "handling; use high for significant harm or severe process failure that "
            "usually needs human recovery; reserve critical for severe, direct, or "
            "hard-to-recover harm requiring immediate blocking or escalation.",
            "Critical does not require harm to have already occurred. Use critical "
            "when the response would let the user continue conduct that must be "
            "stopped immediately and creates a direct severe danger, such as fire or "
            "explosion risk, consumption of food whose safety cannot be confirmed, or "
            "another mandatory-stop high-risk action. Use high for serious impact or "
            "material safety or rights risk without that immediate direct danger.",
            "Decide review_required independently from severity using only the "
            "supplied frozen rules. Do not copy severity into review_required. When "
            "the frozen rules require immediate blocking, escalation, or human "
            "intervention for a high-risk safety case, do not omit required review.",
            "Every evidence.content must be copied as a contiguous original excerpt "
            "from its corresponding case input source. Do not translate, paraphrase, "
            "summarize, alter capitalization, or remove punctuation in an evidence "
            "excerpt.",
            "For response evidence use an assistant message and source_ref "
            "assistant_response; for case_fact use business_context and source_ref "
            "business_context; for reference use reference_evidence and source_ref "
            "reference_evidence. source_ref may be null.",
            "Do not invent reference evidence that is absent from the case input.",
            "Choose exactly one primary_failure_mode for the main failure. Use "
            "incorrect_information when the core error is a wrong fact, capability, "
            "state, compatibility claim, safety judgment, or funds rule, even when the "
            "incorrect fact creates risk.",
            "Use policy_procedure_violation when the core error instructs an action "
            "that an explicit rule prohibits, requires blocking, or places outside a "
            "formal safety, refund, logistics, or after-sales procedure.",
            "Use incomplete_unresolved when necessary case information exists but the "
            "response does not resolve the user's task or omits a necessary next step. "
            "Do not promote incompleteness alone to policy_procedure_violation.",
            "When one response has two or more genuinely independent failure problems, "
            "keep primary_failure_mode for the most important problem, describe that "
            "main actionable problem in problem, and record additional independent "
            "problems with existing allowed values in secondary_flags.",
            "Do not leave secondary_flags empty merely because a primary failure mode "
            "was selected, but do not invent a secondary flag unless a genuinely "
            "independent second problem exists.",
            "Schema, input, and provider errors are execution errors, not judgments.",
            "Use no context beyond the supplied case and rule assets.",
        ]
    )
    user_payload = {
        "case": judge_input.model_dump(mode="json"),
        "judge_runtime_rules": judge_runtime_rules_prompt_payload(),
        "business_reference": assets.business_reference,
        "judge_output_schema": JudgeOutput.model_json_schema(),
        "judge_output_example": JUDGE_OUTPUT_EXAMPLE,
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
