import json

from app.judge_contract import (
    EvidenceType,
    FailureMode,
    JudgeInput,
    Judgment,
    Severity,
)
from app.judge_prompt import JudgePromptAssets, assemble_judge_request
from app.judge_rules import (
    EVIDENCE_RULES,
    EVIDENCE_TYPE_DEFINITIONS,
    FAILURE_MODE_RULES,
    FAILURE_MODES,
    JUDGMENT_DEFINITIONS,
    JUDGMENT_RULES,
    JUDGMENT_SEVERITY_RULES,
    PRIORITY_BOUNDARY,
    PROBLEM_DEFINITION,
    PROBLEM_EXCLUSIONS,
    PROBLEM_RULES,
    SEVERITY_BOUNDARY_RULES,
    SEVERITY_DEFINITIONS,
    SEVERITY_DOES_NOT_MEASURE,
    SEVERITY_EVALUATION_BASIS,
    SEVERITY_LEVELS,
    SEVERITY_PRINCIPLE,
    SEVERITY_RULES_STATUS,
    get_judge_rules_readiness,
    judge_rules_ready_for_execution,
    require_judge_rules_ready_for_execution,
)


def _judge_input() -> JudgeInput:
    return JudgeInput(
        case_id="CASE-RULES-1",
        scenario="Refund",
        messages=[
            {"role": "user", "content": "Can I get a refund?"},
            {
                "role": "assistant",
                "content": "Please share the order status.",
            },
        ],
    )


def test_judgment_definitions_cover_exactly_four_frozen_states() -> None:
    assert set(JUDGMENT_DEFINITIONS) == set(Judgment)
    assert len(JUDGMENT_DEFINITIONS) == 4
    assert any(
        "does not automatically mean uncertain" in rule
        for rule in JUDGMENT_RULES
    )
    assert any("judgment may be success" in rule for rule in JUDGMENT_RULES)


def test_failure_modes_are_complete_without_extensions() -> None:
    assert FAILURE_MODES == tuple(FailureMode)
    assert len(FAILURE_MODES) == 6
    assert any("at most one primary" in rule.lower() for rule in FAILURE_MODE_RULES)
    for excluded in ("review_required", "evidence_insufficient", "uncertain"):
        assert any(excluded in rule for rule in FAILURE_MODE_RULES)


def test_evidence_rules_cover_exact_types_and_traceability() -> None:
    assert set(EVIDENCE_TYPE_DEFINITIONS) == set(EvidenceType)
    assert len(EVIDENCE_TYPE_DEFINITIONS) == 3
    assert any("must not create" in rule for rule in EVIDENCE_RULES)
    assert any("traceable" in rule for rule in EVIDENCE_RULES)


def test_problem_and_root_cause_boundary_is_explicit() -> None:
    assert "business scenario + actionable failure behavior" in PROBLEM_DEFINITION
    assert PROBLEM_EXCLUSIONS == ("failure_mode", "root_cause")
    assert any("root cause" in rule for rule in PROBLEM_RULES)
    assert any("optimization hypothesis" in rule.lower() for rule in PROBLEM_RULES)


def test_severity_asset_contains_exactly_four_frozen_definitions() -> None:
    assert SEVERITY_LEVELS == tuple(Severity)
    assert len(SEVERITY_LEVELS) == 4
    assert SEVERITY_PRINCIPLE == "Severity is case-level impact."
    assert "potential business or user impact" in SEVERITY_EVALUATION_BASIS
    assert set(SEVERITY_DEFINITIONS) == set(Severity)
    assert all(
        definition.definition
        for definition in SEVERITY_DEFINITIONS.values()
    )
    assert "problem-level decision" in PRIORITY_BOUNDARY
    assert SEVERITY_RULES_STATUS == "ready"


def test_readiness_reports_all_runtime_assets_ready() -> None:
    readiness = get_judge_rules_readiness()

    assert readiness.judgment_rules_available is True
    assert readiness.failure_mode_rules_available is True
    assert readiness.evidence_rules_available is True
    assert readiness.severity_definitions_available is True
    assert readiness.ready_for_execution is True
    assert judge_rules_ready_for_execution() is True
    assert require_judge_rules_ready_for_execution() is None


def test_severity_safety_uncertainty_and_frequency_boundaries_are_frozen() -> None:
    high_rules = SEVERITY_DEFINITIONS[Severity.HIGH].boundary_rules
    assert any(
        "Safety does not automatically mean critical" in rule
        for rule in high_rules
    )
    assert any(
        "Insufficient evidence or reference" in rule
        and "must not" in rule
        and "high or critical" in rule
        for rule in SEVERITY_BOUNDARY_RULES
    )
    assert any(
        "Failure frequency does not enter single-case severity" in rule
        for rule in SEVERITY_BOUNDARY_RULES
    )
    assert "Failure frequency" in SEVERITY_DOES_NOT_MEASURE


def test_judgment_severity_rules_match_frozen_semantics() -> None:
    assert JUDGMENT_SEVERITY_RULES == {
        Judgment.SUCCESS: None,
        Judgment.WARNING: None,
        Judgment.FAILURE: tuple(Severity),
        Judgment.UNCERTAIN: None,
    }


def test_prompt_injects_runtime_rules_without_forbidden_context() -> None:
    request = assemble_judge_request(
        _judge_input(),
        assets=JudgePromptAssets(
            business_reference="Returns require the current order status."
        ),
    )
    serialized_request = request.model_dump_json().lower()
    payload = json.loads(request.messages[1].content)

    runtime_rules = payload["judge_runtime_rules"]
    assert runtime_rules["severity_rules_status"] == "ready"
    assert set(runtime_rules["severity_definitions"]) == {
        severity.value for severity in Severity
    }
    assert runtime_rules["judgment_severity_rules"] == {
        "success": None,
        "warning": None,
        "failure": [severity.value for severity in Severity],
        "uncertain": None,
    }
    assert runtime_rules["severity_boundary_rules"]
    assert runtime_rules["ready_for_execution"] is True
    assert "definition_text_pending" not in serialized_request
    for forbidden in (
        "gold",
        "baseline",
        "candidate",
        "target",
        "optimization hypothesis",
        "optimization change",
        "change",
        "priority",
        "dashboard outcome",
    ):
        assert forbidden not in serialized_request
