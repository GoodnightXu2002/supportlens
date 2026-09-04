import json
from collections import Counter
from pathlib import Path

from app.import_parser import parse_import_file

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "novamart_v1.json"
SCENARIO_COUNTS = {
    "Refund": 30,
    "Logistics": 25,
    "Product": 20,
    "After-sales": 25,
}
CASE_SET_COUNTS = {"core": 80, "challenge": 20}
SCENARIO_CASE_SET_COUNTS = {
    "Refund": {"core": 24, "challenge": 6},
    "Logistics": {"core": 20, "challenge": 5},
    "Product": {"core": 16, "challenge": 4},
    "After-sales": {"core": 20, "challenge": 5},
}
CASE_ID_RANGES = {
    "Refund": ("NM-REF", 30),
    "Logistics": ("NM-LOG", 25),
    "Product": ("NM-PRO", 20),
    "After-sales": ("NM-AFT", 25),
}


def test_novamart_fixture_contract_and_parser_compatibility() -> None:
    assert FIXTURE_PATH.is_file()
    items = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(items, list)
    assert len(items) == 100

    case_ids = [item["case_id"] for item in items]
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids) == {
        f"{prefix}-{number:03d}"
        for prefix, count in CASE_ID_RANGES.values()
        for number in range(1, count + 1)
    }
    assert Counter(item["scenario"] for item in items) == SCENARIO_COUNTS
    assert Counter(item["metadata"]["case_set"] for item in items) == (
        CASE_SET_COUNTS
    )
    assert {
        scenario: Counter(
            item["metadata"]["case_set"]
            for item in items
            if item["scenario"] == scenario
        )
        for scenario in SCENARIO_COUNTS
    } == SCENARIO_CASE_SET_COUNTS

    for item in items:
        assert item["metadata"]["case_set"] in CASE_SET_COUNTS
        assert isinstance(item["messages"], list) and item["messages"]
        assert all(
            isinstance(message, dict)
            and set(message) >= {"role", "content"}
            and message["role"] in {"user", "assistant"}
            and isinstance(message["content"], str)
            and message["content"].strip()
            for message in item["messages"]
        )
        roles = {message["role"] for message in item["messages"]}
        assert roles == {"user", "assistant"}

    result = parse_import_file(FIXTURE_PATH.read_bytes(), filename=FIXTURE_PATH.name)

    assert result.success is True
    assert result.total_conversation_count == 100
    assert len(result.conversations) == 100
    assert result.errors == []
