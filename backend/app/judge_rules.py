from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from app.judge_contract import EvidenceType, FailureMode, Judgment, Severity

SEVERITY_RULES_STATUS: Final = "definition_text_pending"

JUDGMENT_DEFINITIONS: Final[Mapping[Judgment, str]] = MappingProxyType(
    {
        Judgment.SUCCESS: (
            "The response quality satisfies the current rubric and reference "
            "requirements."
        ),
        Judgment.WARNING: (
            "The response is generally usable but has an important gap that does "
            "not reach the failure threshold."
        ),
        Judgment.FAILURE: (
            "The response contains a clear and determinable quality failure."
        ),
        Judgment.UNCERTAIN: (
            "The available evidence or reference is insufficient to judge response "
            "quality reliably."
        ),
    }
)

JUDGMENT_RULES: Final = (
    "Missing business facts does not automatically mean uncertain.",
    "When the reference requires clarification for insufficient information and "
    "the assistant correctly asks for it, the judgment may be success.",
)

FAILURE_MODES: Final = tuple(FailureMode)
FAILURE_MODE_RULES: Final = (
    "There may be at most one primary failure mode.",
    "Secondary flags are only for genuinely independent additional violations.",
    "review_required is not a failure mode.",
    "evidence_insufficient is not a failure mode.",
    "uncertain is not a failure mode.",
)

EVIDENCE_TYPE_DEFINITIONS: Final[Mapping[EvidenceType, str]] = MappingProxyType(
    {
        EvidenceType.RESPONSE: "Response Evidence",
        EvidenceType.CASE_FACT: "Case Fact Evidence",
        EvidenceType.REFERENCE: "Reference Evidence",
    }
)
EVIDENCE_RULES: Final = (
    "The judge must not create case facts or reference evidence that are absent "
    "from the input.",
    "Each core claim must be traceable to evidence in the actual input.",
)

PROBLEM_DEFINITION: Final = "Problem = business scenario + actionable failure behavior."
PROBLEM_EXCLUSIONS: Final = ("failure_mode", "root_cause")
PROBLEM_RULES: Final = (
    "A problem is not a failure mode or a root cause.",
    "An optimization hypothesis or root cause must not be asserted as an "
    "established fact."
)

SEVERITY_LEVELS: Final = tuple(Severity)
SEVERITY_PRINCIPLE: Final = "Severity is case-level impact."
PRIORITY_BOUNDARY: Final = (
    "Priority is a problem-level decision and must not be used as case severity."
)
SEVERITY_DEFINITIONS: Final[Mapping[Severity, str]] = MappingProxyType({})


@dataclass(frozen=True)
class JudgeRulesReadiness:
    judgment_rules_available: bool
    failure_mode_rules_available: bool
    evidence_rules_available: bool
    severity_definitions_available: bool

    @property
    def ready_for_execution(self) -> bool:
        return all(
            (
                self.judgment_rules_available,
                self.failure_mode_rules_available,
                self.evidence_rules_available,
                self.severity_definitions_available,
            )
        )


class JudgeRulesNotReadyError(RuntimeError):
    pass


def get_judge_rules_readiness() -> JudgeRulesReadiness:
    return JudgeRulesReadiness(
        judgment_rules_available=set(JUDGMENT_DEFINITIONS) == set(Judgment),
        failure_mode_rules_available=set(FAILURE_MODES) == set(FailureMode),
        evidence_rules_available=(
            set(EVIDENCE_TYPE_DEFINITIONS) == set(EvidenceType)
        ),
        severity_definitions_available=(
            SEVERITY_RULES_STATUS != "definition_text_pending"
            and set(SEVERITY_DEFINITIONS) == set(Severity)
        ),
    )


def judge_rules_ready_for_execution() -> bool:
    return get_judge_rules_readiness().ready_for_execution


def require_judge_rules_ready_for_execution() -> None:
    if not judge_rules_ready_for_execution():
        raise JudgeRulesNotReadyError(
            "Judge runtime rules are not ready for execution: severity definition "
            "text is pending."
        )


def judge_runtime_rules_prompt_payload() -> dict[str, Any]:
    readiness = get_judge_rules_readiness()
    return {
        "judgment_definitions": dict(JUDGMENT_DEFINITIONS),
        "judgment_rules": list(JUDGMENT_RULES),
        "failure_modes": list(FAILURE_MODES),
        "failure_mode_rules": list(FAILURE_MODE_RULES),
        "evidence_type_definitions": dict(EVIDENCE_TYPE_DEFINITIONS),
        "evidence_rules": list(EVIDENCE_RULES),
        "problem_definition": PROBLEM_DEFINITION,
        "problem_exclusions": list(PROBLEM_EXCLUSIONS),
        "problem_rules": list(PROBLEM_RULES),
        "severity_levels": list(SEVERITY_LEVELS),
        "severity_principle": SEVERITY_PRINCIPLE,
        "severity_rules_status": SEVERITY_RULES_STATUS,
        "severity_definitions": dict(SEVERITY_DEFINITIONS),
        "ready_for_execution": readiness.ready_for_execution,
    }
