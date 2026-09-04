import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
CALIBRATION_GOLD_PATH = FIXTURES_DIR / "judge_calibration_gold_v1.json"
BENCHMARK_PATH = FIXTURES_DIR / "judge_benchmark_v1.json"
NOVAMART_PATH = FIXTURES_DIR / "novamart_v1.json"

SOURCE_FIELDS = (
    "case_id",
    "scenario",
    "messages",
    "business_context",
    "reference_evidence",
)
EMPTY_HUMAN_GOLD = {
    "evaluability": None,
    "judgment": None,
    "primary_failure_mode": None,
    "problem": None,
    "evidence": [],
    "severity": None,
    "review_required": None,
    "annotation_rationale": None,
}


def test_calibration_gold_annotation_template_contract() -> None:
    assert CALIBRATION_GOLD_PATH.is_file()

    template = json.loads(CALIBRATION_GOLD_PATH.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    novamart = json.loads(NOVAMART_PATH.read_text(encoding="utf-8"))

    calibration_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "calibration"
    }
    holdout_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "holdout"
    }
    source_by_case_id = {item["case_id"]: item for item in novamart}

    assert isinstance(template, list)
    assert len(template) == 20
    assert {item["case_id"] for item in template} == calibration_case_ids
    assert not ({item["case_id"] for item in template} & holdout_case_ids)

    for item in template:
        source = source_by_case_id[item["case_id"]]
        expected_source = {
            field: source[field] for field in SOURCE_FIELDS if field in source
        }
        actual_source = {
            key: value for key, value in item.items() if key != "human_gold"
        }

        assert actual_source == expected_source
        assert item["human_gold"] == EMPTY_HUMAN_GOLD
