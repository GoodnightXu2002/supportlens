import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.judge_acceptance import (
    _guardrail_matches,
    _load_frozen_cases,
    _validate_evidence,
    run_acceptance_gate,
)
from app.judge_contract import (
    FailureMode,
    JudgeOutput,
    Judgment,
    Severity,
    validate_judge_output,
)
from app.llm_provider import LLMRequest, LLMResponse

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _gold_by_case_id() -> dict[str, dict[str, Any]]:
    calibration = json.loads(
        (FIXTURES_DIR / "judge_calibration_gold_v1.json").read_text(
            encoding="utf-8"
        )
    )
    holdout = json.loads(
        (FIXTURES_DIR / "judge_holdout_gold_v1.json").read_text(encoding="utf-8")
    )
    return {case["case_id"]: case for case in calibration + holdout}


def _source_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _valid_evidence(case_input: dict[str, Any]) -> list[dict[str, Any]]:
    assistant_response = next(
        message["content"]
        for message in case_input["messages"]
        if message["role"] == "assistant"
    )
    evidence = [
        {
            "evidence_type": "response",
            "content": assistant_response,
            "source_ref": "assistant_response",
        }
    ]
    if case_input.get("business_context") is not None:
        evidence.append(
            {
                "evidence_type": "case_fact",
                "content": _source_text(case_input["business_context"]),
                "source_ref": "business_context",
            }
        )
    if case_input.get("reference_evidence") is not None:
        evidence.append(
            {
                "evidence_type": "reference",
                "content": _source_text(case_input["reference_evidence"]),
                "source_ref": "reference_evidence",
            }
        )
    return evidence


def _gold_payload(case_input: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    return {
        "judgment": gold["judgment"],
        "primary_failure_mode": gold["primary_failure_mode"],
        "secondary_flags": (
            ["incomplete_unresolved"]
            if case_input["case_id"] == "NM-PRO-017"
            else []
        ),
        "problem": gold["problem"],
        "severity": gold["severity"],
        "evidence": _valid_evidence(case_input),
        "uncertainty": None,
        "review_required": gold["review_required"],
        "rationale": gold["annotation_rationale"],
    }


class GoldProvider:
    provider_name = "fake"

    def __init__(
        self,
        overrides: dict[str, dict[str, Any]] | None = None,
        run_overrides: dict[tuple[str, int], dict[str, Any]] | None = None,
    ) -> None:
        self.gold = _gold_by_case_id()
        self.overrides = overrides or {}
        self.run_overrides = run_overrides or {}
        self.case_calls: defaultdict[str, int] = defaultdict(int)
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        request_payload = json.loads(request.messages[1].content)
        case_input = request_payload["case"]
        case_id = case_input["case_id"]
        self.case_calls[case_id] += 1
        payload = _gold_payload(case_input, self.gold[case_id]["human_gold"])
        payload.update(self.overrides.get(case_id, {}))
        payload.update(self.run_overrides.get((case_id, self.case_calls[case_id]), {}))
        return LLMResponse(
            provider=self.provider_name,
            model="fake-judge",
            structured_payload=payload,
            raw_json_text=json.dumps(payload, ensure_ascii=False),
        )


def _frozen_case(case_id: str) -> dict[str, Any]:
    calibration, holdout = _load_frozen_cases()
    return next(case for case in calibration + holdout if case["case_id"] == case_id)


def _gold_output(case_id: str) -> JudgeOutput:
    case = _frozen_case(case_id)
    case_input = {
        key: case.get(key)
        for key in (
            "case_id",
            "scenario",
            "messages",
            "business_context",
            "reference_evidence",
        )
    }
    return validate_judge_output(_gold_payload(case_input, case["human_gold"]))


def _output_with_evidence(evidence: list[dict[str, Any]]) -> JudgeOutput:
    return validate_judge_output(
        {
            "judgment": "success",
            "primary_failure_mode": None,
            "secondary_flags": [],
            "problem": None,
            "severity": None,
            "evidence": evidence,
            "uncertainty": None,
            "review_required": False,
            "rationale": "Valid test rationale.",
        }
    )


def test_acceptance_gate_passes_exact_stable_grounded_outputs() -> None:
    provider = GoldProvider()

    report = run_acceptance_gate(provider)

    assert provider.calls == 50
    assert report["final_verdict"] == "PASS"
    assert report["calibration"]["judgment_exact"]["matches"] == 20
    assert (
        report["calibration"]["failure_primary_failure_mode_exact"]["rate"]
        == 1.0
    )
    assert report["calibration"]["failure_severity_exact"]["rate"] == 1.0
    assert report["holdout"]["judgment_exact"]["matches"] == 10
    assert report["dev_guardrails"]["passed"] == 4
    assert not report["mismatches"]


def test_primary_failure_mode_is_exact_but_problem_text_is_not() -> None:
    provider = GoldProvider(
        overrides={
            "NM-AFT-015": {"problem": "Different free-form problem wording."},
            "NM-AFT-021": {"primary_failure_mode": "incorrect_information"},
        }
    )

    report = run_acceptance_gate(provider)

    metric = report["calibration"]["failure_primary_failure_mode_exact"]
    assert metric == {"matches": 7, "total": 8, "rate": 0.875}
    mismatches = {item["case_id"]: item for item in report["mismatches"]}
    assert "NM-AFT-015" not in mismatches
    assert "primary_failure_mode" in mismatches["NM-AFT-021"]["mismatches"]


def test_evidence_allows_only_unicode_and_whitespace_normalized_fragments() -> None:
    case = {
        "messages": [{"role": "assistant", "content": "ＡＢＣ  order\naccepted."}],
        "business_context": "Order   42 is paid.",
        "reference_evidence": "Refunds require approval.",
    }
    output = _output_with_evidence(
        [
            {
                "evidence_type": "response",
                "content": "ABC order accepted.",
                "source_ref": None,
            },
            {
                "evidence_type": "case_fact",
                "content": "Order 42 is paid.",
                "source_ref": "business_context",
            },
            {
                "evidence_type": "reference",
                "content": "Refunds require approval.",
                "source_ref": "reference_evidence",
            },
        ]
    )

    assert _validate_evidence(case, output) == (3, 3, 0)

    invalid = _output_with_evidence(
        [
            {
                "evidence_type": "response",
                "content": "abc order accepted",
                "source_ref": "assistant_response",
            },
            {
                "evidence_type": "case_fact",
                "content": "Order 42 is paid.",
                "source_ref": "reference_evidence",
            },
        ]
    )
    assert _validate_evidence(case, invalid) == (0, 2, 0)

    wrong_source_refs = _output_with_evidence(
        [
            {
                "evidence_type": "response",
                "content": "ABC order accepted.",
                "source_ref": "business_context",
            },
            {
                "evidence_type": "case_fact",
                "content": "Order 42 is paid.",
                "source_ref": "assistant_response",
            },
            {
                "evidence_type": "reference",
                "content": "Refunds require approval.",
                "source_ref": "business_context",
            },
        ]
    )
    assert _validate_evidence(case, wrong_source_refs) == (0, 3, 0)


def test_reference_hallucination_requires_reference_and_locatable_content() -> None:
    missing_reference_case = {
        "messages": [{"role": "assistant", "content": "Response."}],
        "business_context": None,
        "reference_evidence": None,
    }
    hallucinated = _output_with_evidence(
        [
            {
                "evidence_type": "reference",
                "content": "A reference that was not supplied.",
                "source_ref": None,
            }
        ]
    )
    assert _validate_evidence(missing_reference_case, hallucinated) == (0, 1, 1)

    supplied_reference_case = {
        **missing_reference_case,
        "reference_evidence": "Returns require the original receipt.",
    }
    unlocatable = _output_with_evidence(
        [
            {
                "evidence_type": "reference",
                "content": "Returns never need a receipt.",
                "source_ref": "reference_evidence",
            }
        ]
    )
    assert _validate_evidence(supplied_reference_case, unlocatable) == (0, 1, 1)

    locatable = _output_with_evidence(
        [
            {
                "evidence_type": "reference",
                "content": "require the original receipt",
                "source_ref": None,
            }
        ]
    )
    assert _validate_evidence(supplied_reference_case, locatable) == (1, 1, 0)


def test_self_consistency_uses_outputs_not_gold_for_high_critical_scope() -> None:
    provider = GoldProvider(
        run_overrides={
            ("NM-AFT-021", 1): {"severity": "medium"},
            ("NM-AFT-021", 2): {"severity": "low"},
            ("NM-AFT-015", 1): {"severity": "high"},
            ("NM-AFT-015", 2): {
                "severity": "medium",
                "primary_failure_mode": "policy_procedure_violation",
            },
            ("NM-AFT-001", 2): {
                "judgment": "warning",
                "primary_failure_mode": None,
                "problem": None,
                "severity": None,
            },
        }
    )

    report = run_acceptance_gate(provider)

    assert report["self_consistency"]["judgment_flips"] == 1
    assert report["self_consistency"]["high_critical_flips"] == 1
    assert report["self_consistency"]["primary_failure_mode_flips"] == 1


def test_warning_guardrail_boundaries() -> None:
    case = _frozen_case("NM-LOG-002")
    output = _gold_output(case["case_id"])

    assert _guardrail_matches(case, output)
    assert not _guardrail_matches(
        case, output.model_copy(update={"judgment": Judgment.SUCCESS})
    )
    assert not _guardrail_matches(
        case, output.model_copy(update={"severity": Severity.LOW})
    )


def test_critical_safety_guardrail_boundaries() -> None:
    case = _frozen_case("NM-AFT-021")
    output = _gold_output(case["case_id"])

    assert _guardrail_matches(case, output)
    assert not _guardrail_matches(
        case, output.model_copy(update={"severity": Severity.HIGH})
    )
    assert not _guardrail_matches(
        case, output.model_copy(update={"review_required": False})
    )
    assert not _guardrail_matches(
        case,
        output.model_copy(update={"judgment": Judgment.WARNING, "severity": None}),
    )


def test_reference_conflict_guardrail_boundaries() -> None:
    case = _frozen_case("NM-PRO-007")
    output = _gold_output(case["case_id"])
    response_only = [
        evidence
        for evidence in output.evidence
        if evidence.evidence_type.value == "response"
    ]
    reference_only = [
        evidence
        for evidence in output.evidence
        if evidence.evidence_type.value == "reference"
    ]

    assert _guardrail_matches(case, output)
    assert not _guardrail_matches(
        case,
        output.model_copy(
            update={"primary_failure_mode": FailureMode.INCOMPLETE_UNRESOLVED}
        ),
    )
    assert not _guardrail_matches(
        case, output.model_copy(update={"evidence": response_only})
    )
    assert not _guardrail_matches(
        case, output.model_copy(update={"evidence": reference_only})
    )
    assert not _guardrail_matches(
        case,
        output.model_copy(update={"judgment": Judgment.SUCCESS, "severity": None}),
    )


def test_multi_problem_guardrail_boundaries() -> None:
    case = _frozen_case("NM-PRO-017")
    output = _gold_output(case["case_id"])

    assert _guardrail_matches(case, output)
    assert not _guardrail_matches(
        case,
        output.model_copy(
            update={"primary_failure_mode": FailureMode.INCOMPLETE_UNRESOLVED}
        ),
    )
    assert not _guardrail_matches(
        case, output.model_copy(update={"secondary_flags": []})
    )
    assert not _guardrail_matches(case, output.model_copy(update={"problem": "   "}))
    assert not _guardrail_matches(
        case,
        output.model_copy(update={"judgment": Judgment.SUCCESS, "severity": None}),
    )


def test_acceptance_gate_detects_p0_and_guardrail_failures() -> None:
    provider = GoldProvider(
        overrides={
            "NM-AFT-021": {
                "judgment": "success",
                "primary_failure_mode": None,
                "problem": None,
                "severity": None,
                "review_required": False,
            },
            "NM-PRO-007": {
                "evidence": [
                    {
                        "evidence_type": "reference",
                        "content": "This reference was never supplied.",
                        "source_ref": "reference_evidence",
                    }
                ]
            },
        }
    )

    report = run_acceptance_gate(provider)

    assert report["final_verdict"] == "FAIL"
    assert report["p0_blockers"]["high_critical_failure_to_success"] == 1
    assert report["p0_blockers"]["reference_hallucination"] == 2
    assert report["p0_blockers"]["review_required_missed"] == 1
    assert report["dev_guardrails"]["passed"] == 2
    mismatch_ids = {item["case_id"] for item in report["mismatches"]}
    assert {"NM-AFT-021", "NM-PRO-007"} <= mismatch_ids
