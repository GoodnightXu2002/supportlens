from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Conversation

JUDGE_PROMPT_VERSION = "JUDGE-PROMPT-V1.1"
JUDGE_CONTRACT_VERSION = "JUDGE-CONTRACT-V1"


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Judgment(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


class FailureMode(StrEnum):
    INCORRECT_INFORMATION = "incorrect_information"
    INCOMPLETE_UNRESOLVED = "incomplete_unresolved"
    INTENT_RELEVANCE_FAILURE = "intent_relevance_failure"
    IMPROPER_REFUSAL = "improper_refusal"
    POLICY_PROCEDURE_VIOLATION = "policy_procedure_violation"
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceType(StrEnum):
    RESPONSE = "response"
    CASE_FACT = "case_fact"
    REFERENCE = "reference"


class JudgeMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class JudgeMessage(_StrictContractModel):
    role: JudgeMessageRole
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be empty")
        return value


class JudgeInput(_StrictContractModel):
    case_id: str
    scenario: str
    messages: list[JudgeMessage] = Field(min_length=1)
    business_context: Any | None = None
    reference_evidence: Any | None = None

    @field_validator("case_id", "scenario")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def require_user_and_assistant_messages(self) -> Self:
        roles = {message.role for message in self.messages}
        required_roles = {
            JudgeMessageRole.USER,
            JudgeMessageRole.ASSISTANT,
        }
        if not required_roles.issubset(roles):
            raise ValueError("messages must include user and assistant roles")
        return self


class EvidenceItem(_StrictContractModel):
    evidence_type: EvidenceType
    content: str
    source_ref: str | None = None

    @field_validator("content")
    @classmethod
    def evidence_content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence content must not be empty")
        return value


class JudgeOutput(_StrictContractModel):
    judgment: Judgment
    primary_failure_mode: FailureMode | None
    secondary_flags: list[FailureMode]
    problem: str | None
    severity: Severity | None
    evidence: list[EvidenceItem]
    uncertainty: str | None
    review_required: bool | None
    rationale: str

    @field_validator("rationale")
    @classmethod
    def rationale_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be empty")
        return value


def assemble_judge_input(conversation: Conversation) -> JudgeInput:
    metadata = (
        conversation.metadata_ if isinstance(conversation.metadata_, dict) else {}
    )
    return JudgeInput(
        case_id=conversation.external_id,
        scenario=metadata.get("scenario"),
        messages=conversation.messages,
        business_context=metadata.get("business_context"),
        reference_evidence=metadata.get("reference_evidence"),
    )


def validate_judge_output(payload: Any) -> JudgeOutput:
    return JudgeOutput.model_validate(payload)
