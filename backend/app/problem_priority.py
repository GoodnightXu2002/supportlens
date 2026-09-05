from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from app.business_impact_mapping import (
    BusinessImpact,
    BusinessImpactLookupResult,
    BusinessImpactLookupStatus,
)
from app.judge_contract import EvidenceType, JudgeOutput, Severity
from app.schemas import (
    EvidenceConfidence,
    EvidenceSufficiency,
    FinalEffectiveResultStatus,
    PatternConsistency,
    ProblemFrequencyRead,
    ProblemProfileRead,
    ProblemReviewStatus,
    ReferenceConflictStatus,
    SeverityDistributionRead,
)

PROBLEM_PROFILE_VERSION = "BASELINE-PROBLEM-PROFILE-V1"

_SEVERITY_ORDER = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
_BUSINESS_IMPACT_ORDER = {
    BusinessImpact.LOW: 1,
    BusinessImpact.MEDIUM: 2,
    BusinessImpact.HIGH: 3,
}
_PATTERN_ORDER = {
    PatternConsistency.WEAK: 1,
    PatternConsistency.MODERATE: 2,
    PatternConsistency.STRONG: 3,
}
_EVIDENCE_CONFIDENCE_ORDER = {
    EvidenceConfidence.MEDIUM: 1,
    EvidenceConfidence.HIGH: 2,
}
_EXPECTED_SOURCE_REF = {
    EvidenceType.RESPONSE: "assistant_response",
    EvidenceType.CASE_FACT: "business_context",
    EvidenceType.REFERENCE: "reference_evidence",
}


@dataclass(frozen=True)
class ProblemCaseSignal:
    is_core: bool
    final_status: FinalEffectiveResultStatus
    final_result: JudgeOutput | None
    human_problem_or_severity_changed: bool
    traceable: bool = True


@dataclass(frozen=True)
class PriorityRankAssignment:
    rank: int | None
    equal_review_priority: bool | None


def build_problem_profile(
    *,
    cases: list[ProblemCaseSignal],
    core_denominator: int,
    run_status: str,
    business_impact_lookup: BusinessImpactLookupResult,
    reference_conflict_status: ReferenceConflictStatus = (
        ReferenceConflictStatus.UNSUPPORTED
    ),
) -> ProblemProfileRead:
    core_cases = [case for case in cases if case.is_core]
    severities = [
        case.final_result.severity
        for case in core_cases
        if case.final_result is not None
        and case.final_result.severity is not None
    ]
    severity_counts = Counter(severities)
    priority_severity = (
        max(severities, key=_SEVERITY_ORDER.get) if severities else None
    )
    review_status = (
        ProblemReviewStatus.PENDING
        if any(
            case.final_status is FinalEffectiveResultStatus.PENDING_REVIEW
            for case in cases
        )
        else ProblemReviewStatus.CLEARED
    )
    evidence_sufficiency = (
        EvidenceSufficiency.SUFFICIENT
        if _has_sufficient_evidence(cases)
        else EvidenceSufficiency.INSUFFICIENT
    )
    human_changed = any(
        case.human_problem_or_severity_changed for case in cases
    )
    evidence_confidence = _evidence_confidence(
        evidence_sufficiency=evidence_sufficiency,
        review_status=review_status,
        human_changed=human_changed,
        reference_conflict_status=reference_conflict_status,
    )
    pattern_consistency = _pattern_consistency(len(core_cases))
    individual_risk_issue = (
        pattern_consistency is PatternConsistency.WEAK
        and priority_severity in {Severity.HIGH, Severity.CRITICAL}
    )

    blockers: list[str] = []
    if run_status in {"partial_failure", "invalid"}:
        blockers.append("run_status_not_rankable")
    if review_status is ProblemReviewStatus.PENDING:
        blockers.append("review_pending")
    if evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT:
        blockers.append("evidence_insufficient")
    if business_impact_lookup.status is BusinessImpactLookupStatus.UNMAPPED:
        blockers.append("business_impact_unmapped")
    if core_denominator == 0:
        blockers.append("core_denominator_zero")
    if priority_severity is None:
        blockers.append("priority_severity_unavailable")
    if pattern_consistency is None:
        blockers.append("pattern_consistency_unavailable")

    return ProblemProfileRead(
        profile_version=PROBLEM_PROFILE_VERSION,
        frequency=ProblemFrequencyRead(
            numerator=len(core_cases),
            denominator=core_denominator,
        ),
        severity_distribution=SeverityDistributionRead(
            low=severity_counts[Severity.LOW],
            medium=severity_counts[Severity.MEDIUM],
            high=severity_counts[Severity.HIGH],
            critical=severity_counts[Severity.CRITICAL],
        ),
        priority_severity=(
            priority_severity.value if priority_severity is not None else None
        ),
        business_impact=business_impact_lookup.business_impact,
        business_impact_status=business_impact_lookup.status,
        business_impact_mapping_version=(
            business_impact_lookup.mapping_version
        ),
        review_status=review_status,
        evidence_sufficiency=evidence_sufficiency,
        evidence_confidence=evidence_confidence,
        reference_conflict_status=reference_conflict_status,
        pattern_consistency=pattern_consistency,
        individual_risk_issue=individual_risk_issue,
        ranking_eligible=not blockers,
        ranking_blockers=blockers,
        rank=None,
        equal_review_priority=None,
    )


def rank_problem_profiles(
    profiles: list[ProblemProfileRead],
) -> list[PriorityRankAssignment]:
    primary_keys_by_index = {
        index: _primary_ranking_key(profile)
        for index, profile in enumerate(profiles)
        if profile.ranking_eligible
    }
    indices_by_primary_key: dict[
        tuple[int, int, Fraction, int],
        list[int],
    ] = {}
    for index, key in primary_keys_by_index.items():
        indices_by_primary_key.setdefault(key, []).append(index)

    assignments_by_index: dict[int, PriorityRankAssignment] = {}
    next_rank = 1
    for primary_key in sorted(indices_by_primary_key, reverse=True):
        indices = indices_by_primary_key[primary_key]
        confidences = [profiles[index].evidence_confidence for index in indices]
        if all(confidence in _EVIDENCE_CONFIDENCE_ORDER for confidence in confidences):
            indices_by_confidence: dict[EvidenceConfidence, list[int]] = {}
            for index in indices:
                confidence = profiles[index].evidence_confidence
                assert confidence is not None
                indices_by_confidence.setdefault(confidence, []).append(index)
            for confidence in sorted(
                indices_by_confidence,
                key=_EVIDENCE_CONFIDENCE_ORDER.get,
                reverse=True,
            ):
                tied_indices = indices_by_confidence[confidence]
                assignment = PriorityRankAssignment(
                    rank=next_rank,
                    equal_review_priority=len(tied_indices) > 1,
                )
                assignments_by_index.update(
                    (index, assignment) for index in tied_indices
                )
                next_rank += 1
        else:
            assignment = PriorityRankAssignment(
                rank=next_rank,
                equal_review_priority=len(indices) > 1,
            )
            assignments_by_index.update((index, assignment) for index in indices)
            next_rank += 1

    return [
        assignments_by_index.get(
            index,
            PriorityRankAssignment(rank=None, equal_review_priority=None),
        )
        for index in range(len(profiles))
    ]


def _has_sufficient_evidence(cases: list[ProblemCaseSignal]) -> bool:
    if not cases:
        return False
    for case in cases:
        if not case.traceable or case.final_result is None:
            return False
        evidence = case.final_result.evidence
        if not evidence:
            return False
        if any(
            not item.content.strip()
            or item.source_ref != _EXPECTED_SOURCE_REF[item.evidence_type]
            for item in evidence
        ):
            return False
    return True


def _evidence_confidence(
    *,
    evidence_sufficiency: EvidenceSufficiency,
    review_status: ProblemReviewStatus,
    human_changed: bool,
    reference_conflict_status: ReferenceConflictStatus,
) -> EvidenceConfidence | None:
    if (
        evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT
        or review_status is ProblemReviewStatus.PENDING
    ):
        return None
    if human_changed:
        return EvidenceConfidence.MEDIUM
    if reference_conflict_status is ReferenceConflictStatus.CLEAR:
        return EvidenceConfidence.HIGH
    if reference_conflict_status is ReferenceConflictStatus.UNSUPPORTED:
        return EvidenceConfidence.UNKNOWN
    return None


def _pattern_consistency(core_count: int) -> PatternConsistency | None:
    if core_count >= 3:
        return PatternConsistency.STRONG
    if core_count == 2:
        return PatternConsistency.MODERATE
    if core_count == 1:
        return PatternConsistency.WEAK
    return None


def _primary_ranking_key(
    profile: ProblemProfileRead,
) -> tuple[int, int, Fraction, int]:
    assert profile.priority_severity is not None
    assert profile.business_impact is not None
    assert profile.frequency.denominator > 0
    assert profile.pattern_consistency is not None
    return (
        _SEVERITY_ORDER[Severity(profile.priority_severity)],
        _BUSINESS_IMPACT_ORDER[profile.business_impact],
        Fraction(
            profile.frequency.numerator,
            profile.frequency.denominator,
        ),
        _PATTERN_ORDER[profile.pattern_consistency],
    )
