import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
HOLDOUT_GOLD_PATH = FIXTURES_DIR / "judge_holdout_gold_v1.json"
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
VALID_JUDGMENTS = {"success", "warning", "failure", "uncertain"}
VALID_FAILURE_MODES = {
    "incorrect_information",
    "incomplete_unresolved",
    "intent_relevance_failure",
    "improper_refusal",
    "policy_procedure_violation",
    "other",
}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_EVIDENCE_TYPES = {"response", "case_fact", "reference"}


def test_holdout_gold_annotation_template_contract() -> None:
    assert HOLDOUT_GOLD_PATH.is_file()

    template = json.loads(HOLDOUT_GOLD_PATH.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    novamart = json.loads(NOVAMART_PATH.read_text(encoding="utf-8"))

    holdout_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "holdout"
    }
    calibration_case_ids = {
        item["case_id"] for item in benchmark if item["split"] == "calibration"
    }
    source_by_case_id = {item["case_id"]: item for item in novamart}

    assert isinstance(template, list)
    assert len(template) == 10
    assert {item["case_id"] for item in template} == holdout_case_ids
    assert not ({item["case_id"] for item in template} & calibration_case_ids)

    completed_count = 0
    for item in template:
        source = source_by_case_id[item["case_id"]]
        expected_source = {
            field: source[field] for field in SOURCE_FIELDS if field in source
        }
        actual_source = {
            key: value for key, value in item.items() if key != "human_gold"
        }

        assert actual_source == expected_source

        human_gold = item["human_gold"]
        assert set(human_gold) == set(EMPTY_HUMAN_GOLD)
        assert human_gold["evaluability"] is True
        assert human_gold["judgment"] in VALID_JUDGMENTS
        assert isinstance(human_gold["review_required"], bool)
        assert isinstance(human_gold["annotation_rationale"], str)
        assert human_gold["annotation_rationale"].strip()

        if human_gold["judgment"] == "failure":
            assert human_gold["primary_failure_mode"] in VALID_FAILURE_MODES
            assert isinstance(human_gold["problem"], str)
            assert human_gold["problem"].strip()
            assert human_gold["severity"] in VALID_SEVERITIES
        elif human_gold["judgment"] == "warning":
            assert human_gold["primary_failure_mode"] is None
            assert isinstance(human_gold["problem"], str)
            assert human_gold["problem"].strip()
            assert human_gold["severity"] is None
        else:
            assert human_gold["primary_failure_mode"] is None
            assert human_gold["problem"] is None
            assert human_gold["severity"] is None

        assert isinstance(human_gold["evidence"], list)
        assert human_gold["evidence"]
        for evidence in human_gold["evidence"]:
            assert set(evidence) == {"evidence_type", "content", "source_ref"}
            assert evidence["evidence_type"] in VALID_EVIDENCE_TYPES
            assert isinstance(evidence["content"], str)
            assert evidence["content"].strip()
            assert isinstance(evidence["source_ref"], str)
            assert evidence["source_ref"].strip()

        completed_count += 1

    assert completed_count == 10
