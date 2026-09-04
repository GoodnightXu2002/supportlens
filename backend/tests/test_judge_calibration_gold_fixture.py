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
ANNOTATED_CASE_IDS = {
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

    annotated_count = 0
    empty_count = 0
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
        if item["case_id"] not in ANNOTATED_CASE_IDS:
            assert human_gold == EMPTY_HUMAN_GOLD
            empty_count += 1
            continue

        annotated_count += 1
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

    assert annotated_count == 20
    assert empty_count == 0
