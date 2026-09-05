import json
from collections import Counter
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
BENCHMARK_PATH = FIXTURES_DIR / "judge_benchmark_v1.json"
NOVAMART_PATH = FIXTURES_DIR / "novamart_v1.json"

EXPECTED_CALIBRATION_CASE_IDS = {
    "NM-AFT-001",
    "NM-AFT-005",
    "NM-AFT-015",
    "NM-AFT-021",
    "NM-AFT-024",
    "NM-LOG-001",
    "NM-LOG-002",
    "NM-LOG-018",
    "NM-LOG-022",
    "NM-LOG-023",
    "NM-PRO-003",
    "NM-PRO-007",
    "NM-PRO-010",
    "NM-PRO-017",
    "NM-PRO-019",
    "NM-REF-004",
    "NM-REF-010",
    "NM-REF-015",
    "NM-REF-019",
    "NM-REF-027",
}
EXPECTED_HOLDOUT_CASE_IDS = {
    "NM-AFT-018",
    "NM-AFT-022",
    "NM-AFT-025",
    "NM-LOG-005",
    "NM-LOG-021",
    "NM-LOG-025",
    "NM-PRO-005",
    "NM-PRO-018",
    "NM-REF-025",
    "NM-REF-030",
}
EXPECTED_GUARDRAILS = {
    "NM-LOG-002": "warning",
    "NM-AFT-021": "critical_safety",
    "NM-PRO-007": "reference_conflict",
    "NM-PRO-017": "multi_problem",
}
ALLOWED_GUARDRAILS = set(EXPECTED_GUARDRAILS.values())


def test_judge_benchmark_membership_contract() -> None:
    assert BENCHMARK_PATH.is_file()

    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    novamart = json.loads(NOVAMART_PATH.read_text(encoding="utf-8"))

    assert isinstance(benchmark, list)
    assert len(benchmark) == 30

    for membership in benchmark:
        assert isinstance(membership, dict)
        assert set(membership) in (
            {"case_id", "split"},
            {"case_id", "split", "guardrail"},
        )
        assert isinstance(membership["case_id"], str)
        assert membership["case_id"]
        assert membership["split"] in {"calibration", "holdout"}
        if "guardrail" in membership:
            assert membership["guardrail"] in ALLOWED_GUARDRAILS
            assert membership["split"] == "calibration"

    split_counts = Counter(item["split"] for item in benchmark)
    assert split_counts == {"calibration": 20, "holdout": 10}

    case_ids = [item["case_id"] for item in benchmark]
    assert len(case_ids) == len(set(case_ids))

    novamart_case_ids = {item["case_id"] for item in novamart}
    assert set(case_ids) <= novamart_case_ids

    calibration_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "calibration"
    }
    holdout_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "holdout"
    }
    assert calibration_case_ids.isdisjoint(holdout_case_ids)
    assert calibration_case_ids == EXPECTED_CALIBRATION_CASE_IDS
    assert holdout_case_ids == EXPECTED_HOLDOUT_CASE_IDS

    actual_guardrails = {
        item["case_id"]: item["guardrail"]
        for item in benchmark
        if "guardrail" in item
    }
    guardrail_counts = Counter(actual_guardrails.values())
    assert actual_guardrails == EXPECTED_GUARDRAILS
    assert guardrail_counts == {guardrail: 1 for guardrail in ALLOWED_GUARDRAILS}
