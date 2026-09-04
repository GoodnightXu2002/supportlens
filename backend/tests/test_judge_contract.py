import pytest
from pydantic import ValidationError

from app.judge_contract import (
    EvidenceItem,
    EvidenceType,
    FailureMode,
    JudgeInput,
    JudgeOutput,
    Judgment,
    Severity,
    assemble_judge_input,
    validate_judge_output,
)
from app.models import Conversation


def _valid_output_payload() -> dict:
    return {
        "judgment": "failure",
        "primary_failure_mode": "incorrect_information",
        "secondary_flags": ["incomplete_unresolved"],
        "problem": "The response states an unsupported delivery date.",
        "severity": "medium",
        "evidence": [
            {
                "evidence_type": "response",
                "content": "It will arrive tomorrow.",
                "source_ref": "messages[1]",
            },
            {
                "evidence_type": "reference",
                "content": "The carrier has not provided an estimated date.",
                "source_ref": "reference_evidence",
            },
        ],
        "uncertainty": None,
        "review_required": False,
        "rationale": "The promised date is not supported by the supplied tracking.",
    }


def test_assemble_judge_input_preserves_order_and_whitelists_context() -> None:
    conversation = Conversation(
        external_id="CASE-17",
        messages=[
            {"role": "user", "content": "Where is my parcel?"},
            {"role": "assistant", "content": "Which order do you mean?"},
            {"role": "user", "content": "Order NM-17."},
            {"role": "assistant", "content": "It will arrive tomorrow."},
        ],
        metadata_={
            "scenario": "Logistics",
            "business_context": {"order_status": "in_transit"},
            "reference_evidence": {"latest_scan": "hub departure"},
            "metadata": {
                "case_set": "challenge",
                "gold_label": "must-not-leak",
            },
            "target": "must-not-leak",
            "candidate_outcome": "must-not-leak",
        },
    )

    judge_input = assemble_judge_input(conversation)

    assert judge_input.case_id == "CASE-17"
    assert judge_input.scenario == "Logistics"
    assert [message.content for message in judge_input.messages] == [
        "Where is my parcel?",
        "Which order do you mean?",
        "Order NM-17.",
        "It will arrive tomorrow.",
    ]
    assert judge_input.business_context == {"order_status": "in_transit"}
    assert judge_input.reference_evidence == {"latest_scan": "hub departure"}
    assert set(judge_input.model_dump()) == {
        "case_id",
        "scenario",
        "messages",
        "business_context",
        "reference_evidence",
    }


def test_judge_input_allows_absent_optional_context() -> None:
    conversation = Conversation(
        external_id="CASE-18",
        messages=[
            {"role": "user", "content": "Can I return this?"},
            {"role": "assistant", "content": "Please share the order date."},
        ],
        metadata_={"scenario": "Refund"},
    )

    judge_input = assemble_judge_input(conversation)

    assert judge_input.business_context is None
    assert judge_input.reference_evidence is None

    direct_input = JudgeInput(
        case_id="CASE-18",
        scenario="Refund",
        messages=conversation.messages,
    )
    assert direct_input.business_context is None
    assert direct_input.reference_evidence is None


@pytest.mark.parametrize("judgment", list(Judgment))
def test_all_frozen_judgments_are_valid(judgment: Judgment) -> None:
    payload = _valid_output_payload()
    payload["judgment"] = judgment
    payload["severity"] = "medium" if judgment is Judgment.FAILURE else None

    assert JudgeOutput.model_validate(payload).judgment is judgment


def test_invalid_judgment_is_rejected() -> None:
    payload = _valid_output_payload()
    payload["judgment"] = "schema_error"

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(payload)


@pytest.mark.parametrize("failure_mode", list(FailureMode))
def test_all_frozen_failure_modes_are_valid(failure_mode: FailureMode) -> None:
    payload = _valid_output_payload()
    payload["primary_failure_mode"] = failure_mode

    assert JudgeOutput.model_validate(payload).primary_failure_mode is failure_mode


@pytest.mark.parametrize(
    "invalid_mode",
    ["review_required", "evidence_insufficient", "uncertain", "new_mode"],
)
def test_non_failure_modes_are_rejected(invalid_mode: str) -> None:
    payload = _valid_output_payload()
    payload["primary_failure_mode"] = invalid_mode

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(payload)


@pytest.mark.parametrize("severity", list(Severity))
def test_all_frozen_severities_are_valid(severity: Severity) -> None:
    payload = _valid_output_payload()
    payload["severity"] = severity

    assert JudgeOutput.model_validate(payload).severity is severity


def test_invalid_severity_is_rejected() -> None:
    payload = _valid_output_payload()
    payload["severity"] = "urgent"

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(payload)


@pytest.mark.parametrize(
    ("judgment", "severity"),
    [
        ("success", None),
        ("warning", None),
        ("failure", "low"),
        ("failure", "medium"),
        ("failure", "high"),
        ("failure", "critical"),
        ("uncertain", None),
    ],
)
def test_judgment_severity_valid_combinations_pass(
    judgment: str,
    severity: str | None,
) -> None:
    payload = _valid_output_payload()
    payload["judgment"] = judgment
    payload["severity"] = severity

    output = JudgeOutput.model_validate(payload)

    assert output.judgment.value == judgment
    assert output.severity is None or output.severity.value == severity


@pytest.mark.parametrize(
    ("judgment", "severity"),
    [
        ("success", "low"),
        ("warning", "low"),
        ("uncertain", "low"),
        ("failure", None),
    ],
)
def test_judgment_severity_invalid_combinations_are_rejected(
    judgment: str,
    severity: str | None,
) -> None:
    payload = _valid_output_payload()
    payload["judgment"] = judgment
    payload["severity"] = severity

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(payload)


@pytest.mark.parametrize("evidence_type", list(EvidenceType))
def test_all_frozen_evidence_types_are_valid(evidence_type: EvidenceType) -> None:
    evidence = EvidenceItem(
        evidence_type=evidence_type,
        content="Traceable excerpt",
        source_ref="messages[1]",
    )

    assert evidence.evidence_type is evidence_type


def test_invalid_evidence_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_type="dashboard",
            content="Not valid evidence",
            source_ref=None,
        )


def test_complete_structured_output_passes_and_unknown_fields_fail() -> None:
    output = validate_judge_output(_valid_output_payload())
    assert output.judgment is Judgment.FAILURE
    assert output.severity is Severity.MEDIUM

    extra_payload = {**_valid_output_payload(), "expected_score": 0}
    with pytest.raises(ValidationError):
        validate_judge_output(extra_payload)


def test_missing_required_structure_is_a_validation_error() -> None:
    payload = _valid_output_payload()
    del payload["rationale"]

    with pytest.raises(ValidationError):
        validate_judge_output(payload)


def test_uncertain_is_a_judgment_not_a_schema_error_fallback() -> None:
    payload = _valid_output_payload()
    payload.update(
        judgment="uncertain",
        primary_failure_mode=None,
        secondary_flags=[],
        problem=None,
        severity=None,
        evidence=[],
        uncertainty="The supplied reference does not establish the policy.",
        review_required=None,
        rationale="Available evidence is insufficient for a reliable judgment.",
    )

    assert validate_judge_output(payload).judgment is Judgment.UNCERTAIN

    del payload["judgment"]
    with pytest.raises(ValidationError):
        validate_judge_output(payload)


def test_input_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JudgeInput.model_validate(
            {
                "case_id": "CASE-19",
                "scenario": "Product",
                "messages": [
                    {"role": "user", "content": "Does this fit?"},
                    {"role": "assistant", "content": "Which model?"},
                ],
                "business_context": None,
                "reference_evidence": None,
                "run_type": "baseline",
            }
        )
