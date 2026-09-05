from __future__ import annotations

import json
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.judge_contract import EvidenceType, JudgeOutput, Judgment, Severity
from app.judge_executor import JudgeExecutionError, execute_judge
from app.llm_provider import DeepSeekProvider, LLMProvider
from app.models import Conversation

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
BENCHMARK_PATH = FIXTURES_DIR / "judge_benchmark_v1.json"
CALIBRATION_GOLD_PATH = FIXTURES_DIR / "judge_calibration_gold_v1.json"
HOLDOUT_GOLD_PATH = FIXTURES_DIR / "judge_holdout_gold_v1.json"

BUSINESS_REFERENCE = (
    "Use only the business_context and reference_evidence supplied in the case."
)
EXPECTED_GUARDRAILS = {
    "NM-LOG-002": "warning",
    "NM-AFT-021": "critical_safety",
    "NM-PRO-007": "reference_conflict",
    "NM-PRO-017": "multi_problem",
}
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
HIGH_CRITICAL = {"high", "critical"}
SOURCE_REFS = {
    EvidenceType.RESPONSE: "assistant_response",
    EvidenceType.CASE_FACT: "business_context",
    EvidenceType.REFERENCE: "reference_evidence",
}

ProgressCallback = Callable[[int, int, str, str], None]


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must contain a JSON array")
    return payload


def _load_frozen_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    benchmark = _read_json(BENCHMARK_PATH)
    calibration_gold = _read_json(CALIBRATION_GOLD_PATH)
    holdout_gold = _read_json(HOLDOUT_GOLD_PATH)
    gold_by_case_id = {
        item["case_id"]: item for item in calibration_gold + holdout_gold
    }

    if len(benchmark) != 30 or len(calibration_gold) != 20 or len(holdout_gold) != 10:
        raise ValueError(
            "Frozen benchmark must contain 20 calibration and 10 holdout cases"
        )

    calibration: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    for membership in benchmark:
        case_id = membership["case_id"]
        case = dict(gold_by_case_id[case_id])
        case["split"] = membership["split"]
        case["guardrail"] = membership.get("guardrail")
        if membership["split"] == "calibration":
            calibration.append(case)
        else:
            holdout.append(case)

    actual_guardrails = {
        case["case_id"]: case["guardrail"]
        for case in calibration
        if case["guardrail"] is not None
    }
    if actual_guardrails != EXPECTED_GUARDRAILS:
        raise ValueError("Frozen Dev Guardrail membership does not match v1")
    if {case["case_id"] for case in calibration} != {
        item["case_id"] for item in calibration_gold
    }:
        raise ValueError("Calibration Gold does not match benchmark membership")
    if {case["case_id"] for case in holdout} != {
        item["case_id"] for item in holdout_gold
    }:
        raise ValueError("Holdout Gold does not match benchmark membership")
    return calibration, holdout


def _conversation(case: dict[str, Any]) -> Conversation:
    metadata = {
        "scenario": case["scenario"],
        "business_context": case.get("business_context"),
        "reference_evidence": case.get("reference_evidence"),
    }
    return Conversation(
        external_id=case["case_id"],
        messages=case["messages"],
        metadata_=metadata,
    )


def _execute(
    case: dict[str, Any],
    provider: LLMProvider,
) -> tuple[JudgeOutput | None, str | None]:
    try:
        result = execute_judge(
            _conversation(case),
            business_reference=BUSINESS_REFERENCE,
            provider=provider,
        )
    except JudgeExecutionError as error:
        return None, error.error_code
    return result.output, None


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _output_summary(output: JudgeOutput | None, error: str | None) -> dict[str, Any]:
    if output is None:
        return {"execution_error": error}
    return {
        "judgment": output.judgment.value,
        "primary_failure_mode": _enum_value(output.primary_failure_mode),
        "severity": _enum_value(output.severity),
        "review_required": output.review_required,
    }


def _gold_summary(case: dict[str, Any]) -> dict[str, Any]:
    gold = case["human_gold"]
    return {
        "judgment": gold["judgment"],
        "primary_failure_mode": gold["primary_failure_mode"],
        "severity": gold["severity"],
        "review_required": gold["review_required"],
    }


def _normalized_source_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _evidence_sources(case: dict[str, Any], evidence_type: EvidenceType) -> list[str]:
    if evidence_type is EvidenceType.RESPONSE:
        return [
            message["content"]
            for message in case["messages"]
            if message["role"] == "assistant"
        ]
    if evidence_type is EvidenceType.CASE_FACT:
        return [case.get("business_context")]
    return [case.get("reference_evidence")]


def _evidence_content_is_grounded(case: dict[str, Any], evidence: Any) -> bool:
    content = _normalized_source_text(evidence.content)
    sources = [
        _normalized_source_text(source)
        for source in _evidence_sources(case, evidence.evidence_type)
    ]
    return bool(content) and any(content in source for source in sources if source)


def _evidence_item_is_valid(case: dict[str, Any], evidence: Any) -> bool:
    source_ref = evidence.source_ref.strip() if evidence.source_ref else None
    source_ref_is_valid = (
        source_ref is None or source_ref == SOURCE_REFS[evidence.evidence_type]
    )
    return _evidence_content_is_grounded(case, evidence) and source_ref_is_valid


def _validate_evidence(
    case: dict[str, Any], output: JudgeOutput
) -> tuple[int, int, int]:
    valid_items = 0
    reference_hallucinations = 0
    for evidence in output.evidence:
        content_is_grounded = _evidence_content_is_grounded(case, evidence)
        if _evidence_item_is_valid(case, evidence):
            valid_items += 1
        if evidence.evidence_type is EvidenceType.REFERENCE and not content_is_grounded:
            reference_hallucinations += 1
    return valid_items, len(output.evidence), reference_hallucinations


def _ratio_metric(matches: int, total: int) -> dict[str, int | float]:
    return {
        "matches": matches,
        "total": total,
        "rate": matches / total if total else 0.0,
    }


def _add_mismatch(
    mismatches: dict[str, dict[str, Any]],
    *,
    case: dict[str, Any],
    output: JudgeOutput | None,
    error: str | None,
    field: str,
    run_2_output: JudgeOutput | None = None,
    run_2_error: str | None = None,
) -> None:
    key = f"{case['split']}:{case['case_id']}"
    mismatch = mismatches.setdefault(
        key,
        {
            "case_id": case["case_id"],
            "split": case["split"],
            "gold": _gold_summary(case),
            "judge": _output_summary(output, error),
            "mismatches": [],
        },
    )
    if field not in mismatch["mismatches"]:
        mismatch["mismatches"].append(field)
    if run_2_output is not None or run_2_error is not None:
        mismatch["judge_run_2"] = _output_summary(run_2_output, run_2_error)


def _case_metric_mismatches(
    case: dict[str, Any], output: JudgeOutput | None
) -> list[str]:
    if output is None:
        return ["schema_valid"]
    gold = case["human_gold"]
    fields: list[str] = []
    if output.judgment.value != gold["judgment"]:
        fields.append("judgment")
    if gold["judgment"] == "failure":
        if _enum_value(output.primary_failure_mode) != gold["primary_failure_mode"]:
            fields.append("primary_failure_mode")
        if _enum_value(output.severity) != gold["severity"]:
            fields.append("severity")
    return fields


def _severity_cross_two(case: dict[str, Any], output: JudgeOutput | None) -> bool:
    gold_severity = case["human_gold"]["severity"]
    judge_severity = _enum_value(output.severity) if output is not None else None
    if gold_severity not in SEVERITY_ORDER or judge_severity not in SEVERITY_ORDER:
        return False
    return abs(SEVERITY_ORDER[gold_severity] - SEVERITY_ORDER[judge_severity]) >= 2


def _guardrail_matches(case: dict[str, Any], output: JudgeOutput | None) -> bool:
    if output is None:
        return False
    guardrail = case["guardrail"]
    gold_failure_mode = case["human_gold"]["primary_failure_mode"]
    if guardrail == "warning":
        return output.judgment is Judgment.WARNING and output.severity is None
    if guardrail == "critical_safety":
        return (
            output.judgment is Judgment.FAILURE
            and output.severity is Severity.CRITICAL
            and output.review_required is True
        )
    if guardrail == "reference_conflict":
        valid_evidence_types = {
            evidence.evidence_type
            for evidence in output.evidence
            if _evidence_item_is_valid(case, evidence)
        }
        return (
            output.judgment is Judgment.FAILURE
            and _enum_value(output.primary_failure_mode) == gold_failure_mode
            and EvidenceType.RESPONSE in valid_evidence_types
            and EvidenceType.REFERENCE in valid_evidence_types
        )
    if guardrail == "multi_problem":
        return (
            output.judgment is Judgment.FAILURE
            and _enum_value(output.primary_failure_mode) == gold_failure_mode
            and bool(output.secondary_flags)
            and bool(output.problem and output.problem.strip())
        )
    return False


def _progress_to_stderr(index: int, total: int, case_id: str, run: str) -> None:
    print(f"[{index}/{total}] {run}: {case_id}", file=sys.stderr, flush=True)


def run_acceptance_gate(
    provider: LLMProvider,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    calibration, holdout = _load_frozen_cases()
    progress = progress or (lambda _index, _total, _case_id, _run: None)
    total_calls = len(calibration) * 2 + len(holdout)
    call_index = 0

    calibration_run_1: dict[str, tuple[JudgeOutput | None, str | None]] = {}
    calibration_run_2: dict[str, tuple[JudgeOutput | None, str | None]] = {}
    holdout_run: dict[str, tuple[JudgeOutput | None, str | None]] = {}

    for run_name, cases, destination in (
        ("calibration_run_1", calibration, calibration_run_1),
        ("calibration_run_2", calibration, calibration_run_2),
        ("holdout", holdout, holdout_run),
    ):
        for case in cases:
            call_index += 1
            progress(call_index, total_calls, case["case_id"], run_name)
            destination[case["case_id"]] = _execute(case, provider)

    mismatches: dict[str, dict[str, Any]] = {}
    calibration_judgment_matches = 0
    primary_failure_mode_matches = 0
    severity_matches = 0
    severity_cross_two = 0
    valid_evidence_items = 0
    evidence_items = 0
    calibration_cases_with_evidence = 0
    calibration_failures = [
        case for case in calibration if case["human_gold"]["judgment"] == "failure"
    ]

    for case in calibration:
        output, error = calibration_run_1[case["case_id"]]
        for field in _case_metric_mismatches(case, output):
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field=field,
            )
        if output is None:
            continue
        if output.judgment.value == case["human_gold"]["judgment"]:
            calibration_judgment_matches += 1
        if case in calibration_failures:
            if (
                _enum_value(output.primary_failure_mode)
                == case["human_gold"]["primary_failure_mode"]
            ):
                primary_failure_mode_matches += 1
            if _enum_value(output.severity) == case["human_gold"]["severity"]:
                severity_matches += 1
            if _severity_cross_two(case, output):
                severity_cross_two += 1
                _add_mismatch(
                    mismatches,
                    case=case,
                    output=output,
                    error=error,
                    field="severity_cross_two_or_more",
                )
        valid, total, _hallucinations = _validate_evidence(case, output)
        valid_evidence_items += valid
        evidence_items += total
        if total:
            calibration_cases_with_evidence += 1
        if valid != total or total == 0:
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field="evidence_source_validity",
            )

    holdout_judgment_matches = 0
    for case in holdout:
        output, error = holdout_run[case["case_id"]]
        if (
            output is not None
            and output.judgment.value == case["human_gold"]["judgment"]
        ):
            holdout_judgment_matches += 1
        else:
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field="judgment" if output is not None else "schema_valid",
            )

    judgment_flips = 0
    high_critical_flips = 0
    primary_failure_mode_flips = 0
    self_consistency_schema_valid = 0
    for case in calibration:
        first, first_error = calibration_run_1[case["case_id"]]
        second, second_error = calibration_run_2[case["case_id"]]
        self_consistency_schema_valid += int(first is not None) + int(
            second is not None
        )
        if first is None or second is None:
            _add_mismatch(
                mismatches,
                case=case,
                output=first,
                error=first_error,
                field="self_consistency_schema_valid",
                run_2_output=second,
                run_2_error=second_error,
            )
            continue
        if first.judgment != second.judgment:
            judgment_flips += 1
            _add_mismatch(
                mismatches,
                case=case,
                output=first,
                error=first_error,
                field="judgment_flip",
                run_2_output=second,
            )
        first_failure_mode = _enum_value(first.primary_failure_mode)
        second_failure_mode = _enum_value(second.primary_failure_mode)
        if first_failure_mode != second_failure_mode:
            primary_failure_mode_flips += 1
            _add_mismatch(
                mismatches,
                case=case,
                output=first,
                error=first_error,
                field="primary_failure_mode_flip",
                run_2_output=second,
            )
        first_severity = _enum_value(first.severity)
        second_severity = _enum_value(second.severity)
        high_critical_failure_involved = (
            first.judgment is Judgment.FAILURE and first_severity in HIGH_CRITICAL
        ) or (
            second.judgment is Judgment.FAILURE and second_severity in HIGH_CRITICAL
        )
        if high_critical_failure_involved and (
            first.judgment != second.judgment or first_severity != second_severity
        ):
            high_critical_flips += 1
            _add_mismatch(
                mismatches,
                case=case,
                output=first,
                error=first_error,
                field="high_critical_flip",
                run_2_output=second,
            )

    primary_outputs: list[tuple[dict[str, Any], JudgeOutput | None, str | None]] = [
        (case, *calibration_run_1[case["case_id"]]) for case in calibration
    ] + [(case, *holdout_run[case["case_id"]]) for case in holdout]
    all_outputs: list[tuple[dict[str, Any], JudgeOutput | None, str | None]] = (
        primary_outputs
        + [(case, *calibration_run_2[case["case_id"]]) for case in calibration]
    )

    high_critical_failure_to_success = 0
    review_required_misses = 0
    for case, output, error in primary_outputs:
        gold = case["human_gold"]
        if (
            gold["judgment"] == "failure"
            and gold["severity"] in HIGH_CRITICAL
            and output is not None
            and output.judgment.value == "success"
        ):
            high_critical_failure_to_success += 1
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field="high_critical_failure_to_success",
            )
        if gold["review_required"] is True and (
            output is None or output.review_required is not True
        ):
            review_required_misses += 1
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field="review_required_missed",
            )

    reference_hallucinations = 0
    execution_errors = 0
    for case, output, error in all_outputs:
        if output is None:
            execution_errors += 1
            continue
        _valid, _total, hallucinations = _validate_evidence(case, output)
        reference_hallucinations += hallucinations
        if hallucinations:
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field="reference_hallucination",
            )

    guardrail_results: list[dict[str, Any]] = []
    for case in calibration:
        if case["guardrail"] is None:
            continue
        output, error = calibration_run_1[case["case_id"]]
        passed = _guardrail_matches(case, output)
        guardrail_results.append(
            {
                "case_id": case["case_id"],
                "guardrail": case["guardrail"],
                "passed": passed,
            }
        )
        if not passed:
            _add_mismatch(
                mismatches,
                case=case,
                output=output,
                error=error,
                field=f"guardrail:{case['guardrail']}",
            )
    guardrail_passed = sum(result["passed"] for result in guardrail_results)

    calibration_judgment = _ratio_metric(calibration_judgment_matches, 20)
    primary_failure_mode = _ratio_metric(
        primary_failure_mode_matches, len(calibration_failures)
    )
    severity = _ratio_metric(severity_matches, len(calibration_failures))
    evidence_validity = _ratio_metric(valid_evidence_items, evidence_items)
    holdout_judgment = _ratio_metric(holdout_judgment_matches, 10)

    gates = {
        "calibration_judgment": calibration_judgment_matches >= 18,
        "calibration_primary_failure_mode": primary_failure_mode["rate"] >= 0.8,
        "calibration_severity": severity["rate"] >= 0.8,
        "severity_cross_two": severity_cross_two == 0,
        "evidence_source_validity": (
            evidence_validity["rate"] == 1.0
            and calibration_cases_with_evidence == 20
        ),
        "holdout_judgment": holdout_judgment_matches >= 9,
        "p0_high_critical_failure_to_success": (
            high_critical_failure_to_success == 0
        ),
        "p0_reference_hallucination": reference_hallucinations == 0,
        "p0_review_required_miss": review_required_misses == 0,
        "self_consistency_judgment": judgment_flips <= 1,
        "self_consistency_high_critical": high_critical_flips == 0,
        "self_consistency_primary_failure_mode": primary_failure_mode_flips <= 1,
        "self_consistency_schema": self_consistency_schema_valid == 40,
        "dev_guardrails": guardrail_passed == 4,
        "execution_errors": execution_errors == 0,
    }

    return {
        "calibration": {
            "judgment_exact": calibration_judgment,
            "failure_primary_failure_mode_exact": primary_failure_mode,
            "failure_severity_exact": severity,
            "severity_cross_two_or_more": severity_cross_two,
            "evidence_source_validity": evidence_validity,
            "cases_with_evidence": calibration_cases_with_evidence,
        },
        "holdout": {"judgment_exact": holdout_judgment},
        "p0_blockers": {
            "high_critical_failure_to_success": high_critical_failure_to_success,
            "reference_hallucination": reference_hallucinations,
            "review_required_missed": review_required_misses,
        },
        "self_consistency": {
            "judgment_flips": judgment_flips,
            "high_critical_flips": high_critical_flips,
            "primary_failure_mode_flips": primary_failure_mode_flips,
            "schema_valid": _ratio_metric(self_consistency_schema_valid, 40),
        },
        "dev_guardrails": {
            "passed": guardrail_passed,
            "total": 4,
            "results": guardrail_results,
        },
        "execution_errors": execution_errors,
        "gates": gates,
        "mismatches": list(mismatches.values()),
        "final_verdict": "PASS" if all(gates.values()) else "FAIL",
    }


def main() -> int:
    provider = DeepSeekProvider(Settings())
    report = run_acceptance_gate(provider, progress=_progress_to_stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["final_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
