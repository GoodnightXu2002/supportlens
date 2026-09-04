import json
from collections import Counter
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
BENCHMARK_PATH = FIXTURES_DIR / "judge_benchmark_v1.json"
NOVAMART_PATH = FIXTURES_DIR / "novamart_v1.json"

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


def test_judge_benchmark_membership_contract() -> None:
    assert BENCHMARK_PATH.is_file()

    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    novamart = json.loads(NOVAMART_PATH.read_text(encoding="utf-8"))

    assert isinstance(benchmark, list)
    assert len(benchmark) == 30

    for membership in benchmark:
        assert isinstance(membership, dict)
        assert set(membership) == {"case_id", "split"}
        assert isinstance(membership["case_id"], str)
        assert membership["case_id"]
        assert membership["split"] in {"calibration", "holdout"}

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
    assert holdout_case_ids == EXPECTED_HOLDOUT_CASE_IDS
