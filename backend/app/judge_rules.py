from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from app.judge_contract import EvidenceType, FailureMode, Judgment, Severity

SEVERITY_RULES_STATUS: Final = "ready"

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
SEVERITY_EVALUATION_BASIS: Final = (
    "Severity measures the potential business or user impact in the current case "
    "if the user acts on the AI response."
)
SEVERITY_DOES_NOT_MEASURE: Final = (
    "How obvious the error is",
    "Failure frequency",
    "Model confidence",
    "How strongly review is required",
)
PRIORITY_BOUNDARY: Final = (
    "Priority is a problem-level decision and must not be used as case severity."
)


@dataclass(frozen=True)
class SeverityDefinition:
    definition: str
    typical_impacts: tuple[str, ...]
    boundary_rules: tuple[str, ...]

    def as_prompt_payload(self) -> dict[str, str | list[str]]:
        return {
            "definition": self.definition,
            "typical_impacts": list(self.typical_impacts),
            "boundary_rules": list(self.boundary_rules),
        }


SEVERITY_DEFINITIONS: Final[Mapping[Severity, SeverityDefinition]] = (
    MappingProxyType(
        {
            Severity.LOW: SeverityDefinition(
                definition=(
                    "A clear quality issue causes only mild friction or localized "
                    "experience loss; the core task outcome remains mostly "
                    "unaffected and the user can usually recover easily."
                ),
                typical_impacts=(
                    "Non-critical explanation omitted",
                    "Minor information incompleteness",
                    "Unnecessary steps",
                    "Localized experience degradation",
                ),
                boundary_rules=(
                    "The impact is minor and easily recoverable.",
                    "Do not raise severity merely because the wording is obviously "
                    "wrong.",
                ),
            ),
            Severity.MEDIUM: SeverityDefinition(
                definition=(
                    "The failure clearly reduces resolution efficiency or directs "
                    "the user toward an incorrect or incomplete process; it is "
                    "usually recoverable and does not cause major financial, rights, "
                    "or safety consequences."
                ),
                typical_impacts=(
                    "Incorrect next step",
                    "Key action omitted",
                    "Repeated contact required",
                    "Resolution materially delayed",
                    "Recoverable incorrect process",
                ),
                boundary_rules=("Recoverable, without major consequences.",),
            ),
            Severity.HIGH: SeverityDefinition(
                definition=(
                    "The failure may cause core task failure, significant financial "
                    "or user-rights harm, a severe process error, a major policy "
                    "violation, or a material safety risk below the highest level; "
                    "reliable recovery usually requires human intervention."
                ),
                typical_impacts=(
                    "Incorrect refund or after-sales rules causing significant "
                    "rights loss",
                    "Critical process handled incorrectly",
                    "Unsafe handling of a high-risk device",
                    "Major business harm with a reasonable recovery path",
                ),
                boundary_rules=(
                    "Safety does not automatically mean critical.",
                    "Use high when the safety risk does not substantively meet the "
                    "critical criteria of severity, directness, urgency, difficulty "
                    "of recovery, or mandatory immediate blocking or escalation.",
                ),
            ),
            Severity.CRITICAL: SeverityDefinition(
                definition=(
                    "The failure may cause severe, direct, or hard-to-recover safety "
                    "harm; major financial or user-rights loss; or dangerous guidance "
                    "in a high-risk situation that requires immediate blocking or "
                    "escalation. Critical is the highest, zero-tolerance risk level."
                ),
                typical_impacts=(
                    "Clear personal safety danger",
                    "Continued-use advice despite serious device or battery risk",
                    "Major and hard-to-recover financial operation error",
                    "Continued high-risk handling when immediate human escalation is "
                    "required",
                ),
                boundary_rules=(
                    "Use critical only when severity, directness, urgency, difficulty "
                    "of recovery, or mandatory immediate blocking or escalation is "
                    "substantively established.",
                    "Do not raise severity to critical because of model uncertainty.",
                ),
            ),
        }
    )
)

JUDGMENT_SEVERITY_RULES: Final[
    Mapping[Judgment, tuple[Severity, ...] | None]
] = MappingProxyType(
    {
        Judgment.SUCCESS: None,
        Judgment.WARNING: None,
        Judgment.FAILURE: tuple(Severity),
        Judgment.UNCERTAIN: None,
    }
)

SEVERITY_BOUNDARY_RULES: Final = (
    "Judge severity by potential impact in the current case.",
    "An obviously worded error with minor impact may be low.",
    "A plausible-sounding answer with a key rule error that may cause significant "
    "rights loss may be high.",
    "Failure frequency does not enter single-case severity.",
    "Insufficient evidence or reference leads to an uncertain judgment and must "
    "not cause a conservative high or critical severity.",
)


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
            SEVERITY_RULES_STATUS == "ready"
            and set(SEVERITY_DEFINITIONS) == set(Severity)
            and all(
                definition.definition.strip()
                for definition in SEVERITY_DEFINITIONS.values()
            )
        ),
    )


def judge_rules_ready_for_execution() -> bool:
    return get_judge_rules_readiness().ready_for_execution


def require_judge_rules_ready_for_execution() -> None:
    if not judge_rules_ready_for_execution():
        raise JudgeRulesNotReadyError(
            "Judge runtime rules are not ready for execution."
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
        "problem_rules": [PROBLEM_RULES[0]],
        "severity_levels": list(SEVERITY_LEVELS),
        "severity_principle": SEVERITY_PRINCIPLE,
        "severity_evaluation_basis": SEVERITY_EVALUATION_BASIS,
        "severity_does_not_measure": list(SEVERITY_DOES_NOT_MEASURE),
        "severity_rules_status": SEVERITY_RULES_STATUS,
        "severity_definitions": {
            severity: definition.as_prompt_payload()
            for severity, definition in SEVERITY_DEFINITIONS.items()
        },
        "judgment_severity_rules": {
            judgment: (
                None if severities is None else list(severities)
            )
            for judgment, severities in JUDGMENT_SEVERITY_RULES.items()
        },
        "severity_boundary_rules": list(SEVERITY_BOUNDARY_RULES),
        "ready_for_execution": readiness.ready_for_execution,
    }
