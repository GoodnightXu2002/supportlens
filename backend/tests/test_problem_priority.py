import pytest

from app.business_impact_mapping import (
    BUSINESS_IMPACT_MAPPING_VERSION,
    BusinessImpact,
    BusinessImpactLookupResult,
    BusinessImpactLookupStatus,
)
from app.judge_contract import JudgeOutput
from app.problem_priority import (
    PROBLEM_PROFILE_VERSION,
    ProblemCaseSignal,
    build_problem_profile,
    rank_problem_profiles,
)
from app.schemas import (
    EvidenceConfidence,
    EvidenceSufficiency,
    FinalEffectiveResultStatus,
    PatternConsistency,
    ProblemFrequencyRead,
    ProblemProfileRead,
    ProblemRead,
    ProblemReviewStatus,
    ReferenceConflictStatus,
    SeverityDistributionRead,
)


def _output(
    severity: str = "medium",
    *,
    evidence: list[dict[str, str | None]] | None = None,
) -> JudgeOutput:
    return JudgeOutput.model_validate(
        {
            "judgment": "failure",
            "primary_failure_mode": "incorrect_information",
            "secondary_flags": [],
            "problem": "Actionable failure",
            "severity": severity,
            "evidence": (
                evidence
                if evidence is not None
                else [
                    {
                        "evidence_type": "response",
                        "content": "The response made the failing claim.",
                        "source_ref": "assistant_response",
                    }
                ]
            ),
            "uncertainty": None,
            "review_required": False,
            "rationale": "The response conflicts with the available facts.",
        }
    )


def _case(
    *,
    is_core: bool = True,
    severity: str = "medium",
    status: FinalEffectiveResultStatus = FinalEffectiveResultStatus.FINAL,
    human_changed: bool = False,
    evidence: list[dict[str, str | None]] | None = None,
) -> ProblemCaseSignal:
    return ProblemCaseSignal(
        is_core=is_core,
        final_status=status,
        final_result=_output(severity, evidence=evidence),
        human_problem_or_severity_changed=human_changed,
    )


def _impact(
    impact: BusinessImpact | None = BusinessImpact.HIGH,
) -> BusinessImpactLookupResult:
    return BusinessImpactLookupResult(
        mapping_key='["Refund","Actionable failure"]',
        mapping_version=BUSINESS_IMPACT_MAPPING_VERSION,
        status=(
            BusinessImpactLookupStatus.MAPPED
            if impact is not None
            else BusinessImpactLookupStatus.UNMAPPED
        ),
        business_impact=impact,
    )


def test_core_challenge_frequency_and_severity_are_strictly_separated() -> None:
    profile = build_problem_profile(
        cases=[
            _case(is_core=True, severity="low"),
            _case(is_core=True, severity="high"),
            _case(is_core=False, severity="critical"),
        ],
        core_denominator=80,
        run_status="completed",
        business_impact_lookup=_impact(),
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
    )

    assert profile.frequency == ProblemFrequencyRead(
        numerator=2,
        denominator=80,
    )
    assert profile.severity_distribution == SeverityDistributionRead(
        low=1,
        medium=0,
        high=1,
        critical=0,
    )
    assert profile.priority_severity.value == "high"
    assert profile.pattern_consistency is PatternConsistency.MODERATE


@pytest.mark.parametrize(
    ("core_count", "expected"),
    [
        (1, PatternConsistency.WEAK),
        (2, PatternConsistency.MODERATE),
        (3, PatternConsistency.STRONG),
        (5, PatternConsistency.STRONG),
    ],
)
def test_pattern_consistency_uses_only_core_count(
    core_count: int,
    expected: PatternConsistency,
) -> None:
    profile = build_problem_profile(
        cases=[_case() for _ in range(core_count)] + [_case(is_core=False)],
        core_denominator=10,
        run_status="completed",
        business_impact_lookup=_impact(),
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
    )

    assert profile.frequency.numerator == core_count
    assert profile.pattern_consistency is expected


@pytest.mark.parametrize("run_status", ["partial_failure", "invalid"])
def test_review_and_evidence_hard_gates_are_explicit(
    run_status: str,
) -> None:
    pending = _case(status=FinalEffectiveResultStatus.PENDING_REVIEW)
    insufficient = _case(evidence=[])
    profile = build_problem_profile(
        cases=[pending, insufficient],
        core_denominator=10,
        run_status=run_status,
        business_impact_lookup=_impact(None),
    )

    assert profile.review_status is ProblemReviewStatus.PENDING
    assert profile.evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT
    assert profile.evidence_confidence is None
    assert profile.ranking_eligible is False
    assert set(profile.ranking_blockers) >= {
        "run_status_not_rankable",
        "review_pending",
        "evidence_insufficient",
        "business_impact_unmapped",
    }


def test_invalid_evidence_source_ref_is_insufficient() -> None:
    profile = build_problem_profile(
        cases=[
            _case(
                evidence=[
                    {
                        "evidence_type": "response",
                        "content": "A non-empty but incorrectly traced claim.",
                        "source_ref": "business_context",
                    }
                ]
            )
        ],
        core_denominator=10,
        run_status="completed",
        business_impact_lookup=_impact(),
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
    )

    assert profile.evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT
    assert profile.ranking_eligible is False
    assert "evidence_insufficient" in profile.ranking_blockers


def test_evidence_confidence_uses_reviewed_change_and_exposes_signal_gap() -> None:
    corrected = build_problem_profile(
        cases=[_case(human_changed=True)],
        core_denominator=10,
        run_status="completed",
        business_impact_lookup=_impact(),
    )
    unsupported = build_problem_profile(
        cases=[_case()],
        core_denominator=10,
        run_status="completed",
        business_impact_lookup=_impact(),
    )
    explicit_clear = build_problem_profile(
        cases=[_case()],
        core_denominator=10,
        run_status="completed",
        business_impact_lookup=_impact(),
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
    )

    assert corrected.evidence_confidence is EvidenceConfidence.MEDIUM
    assert corrected.ranking_eligible is True
    assert unsupported.reference_conflict_status is (
        ReferenceConflictStatus.UNSUPPORTED
    )
    assert unsupported.evidence_confidence is EvidenceConfidence.UNKNOWN
    assert unsupported.ranking_eligible is True
    assert "evidence_confidence_unavailable" not in unsupported.ranking_blockers
    assert explicit_clear.evidence_confidence is EvidenceConfidence.HIGH
    assert explicit_clear.ranking_eligible is True


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_high_or_critical_weak_pattern_is_individual_risk_issue(
    severity: str,
) -> None:
    profile = build_problem_profile(
        cases=[_case(severity=severity)],
        core_denominator=80,
        run_status="completed",
        business_impact_lookup=_impact(),
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
    )

    assert profile.pattern_consistency is PatternConsistency.WEAK
    assert profile.individual_risk_issue is True


def _rankable_profile(
    *,
    severity: str,
    impact: BusinessImpact,
    frequency: int,
    pattern: PatternConsistency,
    confidence: EvidenceConfidence,
) -> ProblemProfileRead:
    return ProblemProfileRead(
        profile_version=PROBLEM_PROFILE_VERSION,
        frequency=ProblemFrequencyRead(numerator=frequency, denominator=100),
        severity_distribution=SeverityDistributionRead(
            low=0,
            medium=0,
            high=0,
            critical=0,
        ),
        priority_severity=severity,
        business_impact=impact,
        business_impact_status=BusinessImpactLookupStatus.MAPPED,
        business_impact_mapping_version=BUSINESS_IMPACT_MAPPING_VERSION,
        review_status=ProblemReviewStatus.CLEARED,
        evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
        evidence_confidence=confidence,
        reference_conflict_status=ReferenceConflictStatus.CLEAR,
        pattern_consistency=pattern,
        individual_risk_issue=False,
        ranking_eligible=True,
        ranking_blockers=[],
        rank=None,
        equal_review_priority=None,
    )


def test_priority_ranking_is_lexicographic_and_preserves_equal_ties() -> None:
    profiles = [
        _rankable_profile(
            severity="high",
            impact=BusinessImpact.LOW,
            frequency=1,
            pattern=PatternConsistency.WEAK,
            confidence=EvidenceConfidence.MEDIUM,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.HIGH,
            frequency=5,
            pattern=PatternConsistency.STRONG,
            confidence=EvidenceConfidence.HIGH,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.HIGH,
            frequency=4,
            pattern=PatternConsistency.STRONG,
            confidence=EvidenceConfidence.HIGH,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.HIGH,
            frequency=4,
            pattern=PatternConsistency.MODERATE,
            confidence=EvidenceConfidence.HIGH,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.HIGH,
            frequency=4,
            pattern=PatternConsistency.MODERATE,
            confidence=EvidenceConfidence.MEDIUM,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.MEDIUM,
            frequency=99,
            pattern=PatternConsistency.STRONG,
            confidence=EvidenceConfidence.HIGH,
        ),
    ]
    profiles.append(profiles[4].model_copy(deep=True))

    assignments = rank_problem_profiles(profiles)

    assert [assignment.rank for assignment in assignments] == [
        1,
        2,
        3,
        4,
        5,
        6,
        5,
    ]
    assert [assignment.equal_review_priority for assignment in assignments] == [
        False,
        False,
        False,
        False,
        True,
        False,
        True,
    ]


def test_unknown_confidence_does_not_block_different_primary_signals() -> None:
    profiles = [
        _rankable_profile(
            severity="high",
            impact=BusinessImpact.LOW,
            frequency=1,
            pattern=PatternConsistency.WEAK,
            confidence=EvidenceConfidence.UNKNOWN,
        ),
        _rankable_profile(
            severity="medium",
            impact=BusinessImpact.HIGH,
            frequency=99,
            pattern=PatternConsistency.STRONG,
            confidence=EvidenceConfidence.HIGH,
        ),
    ]

    assignments = rank_problem_profiles(profiles)

    assert [assignment.rank for assignment in assignments] == [1, 2]
    assert all(
        assignment.equal_review_priority is False
        for assignment in assignments
    )


def test_tied_primary_signals_with_unknown_confidence_share_rank() -> None:
    unknown = _rankable_profile(
        severity="medium",
        impact=BusinessImpact.MEDIUM,
        frequency=1,
        pattern=PatternConsistency.WEAK,
        confidence=EvidenceConfidence.UNKNOWN,
    )
    known = unknown.model_copy(
        update={"evidence_confidence": EvidenceConfidence.HIGH}
    )

    assignments = rank_problem_profiles([unknown, known])

    assert [assignment.rank for assignment in assignments] == [1, 1]
    assert all(
        assignment.equal_review_priority is True
        for assignment in assignments
    )


def test_problem_contract_has_no_priority_score() -> None:
    assert "priority_score" not in ProblemProfileRead.model_fields
    assert "priority_score" not in ProblemRead.model_fields
    assert "score" not in ProblemProfileRead.model_fields
