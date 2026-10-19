"""Deterministic long-term research-state selection -- a pure function of
TODAY's LongTermFactorBundle only. No hidden state, no dependency on
yesterday's state, no randomness: identical factor inputs always produce
the identical LongTermRuleResult (app.long_term_research.service's
determinism guarantee), and each day's `reason` genuinely reflects only
that day's evidence.

Day-to-day TRANSITIONS (for push-worthiness) are detected separately by
app.long_term_research.service, by comparing two already-computed
LongTermResearchResult.research_state values from consecutive snapshots
-- this module has no concept of "previous state" at all, by design.

Scoring is a simple, fully transparent, five-factor count -- NOT a 0-100
AI score (per spec): each of business_quality/earnings_trend/valuation/
growth/long_term_trend contributes -1 (unfavorable), 0 (neutral or
NOT_ENOUGH_EVIDENCE), or +1 (favorable) to `net_score`. The thresholds
below are fixed constants, documented inline, never learned or tuned
against realized outcomes (that evaluation happens separately and later,
per spec, to avoid leakage).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.long_term_research.schemas import (
    BusinessQualityState,
    EarningsTrendState,
    GrowthState,
    LongTermEvidenceQuality,
    LongTermFactorBundle,
    LongTermResearchState,
    LongTermTrendState,
    ValuationState,
)

MIN_AVAILABLE_FACTORS_FOR_A_VERDICT = 3

_FAVORABLE = {
    BusinessQualityState.STRONG,
    EarningsTrendState.IMPROVING,
    ValuationState.CHEAP,
    GrowthState.STRONG,
    LongTermTrendState.CONSTRUCTIVE,
}
_UNFAVORABLE = {
    BusinessQualityState.WEAK,
    EarningsTrendState.WEAKENING,
    ValuationState.EXPENSIVE,
    GrowthState.WEAK,
    LongTermTrendState.WEAKENING,
}
_NOT_ENOUGH_EVIDENCE_VALUES = {
    BusinessQualityState.NOT_ENOUGH_EVIDENCE,
    EarningsTrendState.NOT_ENOUGH_EVIDENCE,
    ValuationState.NOT_ENOUGH_EVIDENCE,
    GrowthState.NOT_ENOUGH_EVIDENCE,
    LongTermTrendState.NOT_ENOUGH_EVIDENCE,
}


@dataclass(frozen=True)
class LongTermRuleResult:
    state: LongTermResearchState
    evidence_quality: LongTermEvidenceQuality
    positive_evidence: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    reason: str = ""
    what_would_change_state: str = ""


def _factor_score(value) -> int:
    if value in _FAVORABLE:
        return 1
    if value in _UNFAVORABLE:
        return -1
    return 0


def determine_research_state(factors: LongTermFactorBundle) -> LongTermRuleResult:
    named_factors = (
        (factors.business_quality, factors.business_quality_evidence),
        (factors.earnings_trend, factors.earnings_trend_evidence),
        (factors.valuation, factors.valuation_evidence),
        (factors.growth, factors.growth_evidence),
        (factors.long_term_trend, factors.long_term_trend_evidence),
    )

    positive_evidence: list[str] = []
    negative_evidence: list[str] = []
    missing_evidence: list[str] = []
    available_count = 0
    positive_count = 0
    negative_count = 0
    net_score = 0

    for value, evidence in named_factors:
        missing_evidence.extend(evidence.missing)
        if value in _NOT_ENOUGH_EVIDENCE_VALUES:
            continue
        available_count += 1
        positive_evidence.extend(evidence.positive)
        negative_evidence.extend(evidence.negative)
        score = _factor_score(value)
        net_score += score
        if score > 0:
            positive_count += 1
        elif score < 0:
            negative_count += 1

    contradictions: list[str] = []
    if positive_count >= 2 and negative_count >= 2:
        contradictions.append(
            "Evidence is split: multiple factors point positive while multiple others point negative "
            "-- this is not a clean signal in either direction."
        )

    if available_count < MIN_AVAILABLE_FACTORS_FOR_A_VERDICT:
        return LongTermRuleResult(
            state=LongTermResearchState.NOT_ENOUGH_EVIDENCE,
            evidence_quality=LongTermEvidenceQuality.NOT_ENOUGH_EVIDENCE,
            positive_evidence=positive_evidence,
            negative_evidence=negative_evidence,
            contradictions=contradictions,
            missing_evidence=missing_evidence,
            reason=(
                f"Only {available_count} of 5 long-term factors could be evaluated (minimum "
                f"{MIN_AVAILABLE_FACTORS_FOR_A_VERDICT} required) -- the available data cannot support "
                "a long-term research conclusion yet."
            ),
            what_would_change_state="More complete fundamental and/or price-history data becoming available.",
        )

    trend_weakening_with_fundamentals_deteriorating = (
        factors.long_term_trend == LongTermTrendState.WEAKENING
        and (
            factors.business_quality == BusinessQualityState.WEAK
            or factors.earnings_trend == EarningsTrendState.WEAKENING
        )
    )

    if trend_weakening_with_fundamentals_deteriorating and net_score <= -2:
        state = LongTermResearchState.THESIS_INVALIDATED
        reason = (
            "Long-term price structure is weakening at the same time business fundamentals are "
            "deteriorating -- multiple independent factors agree the original long-term case no "
            "longer holds."
        )
        what_would_change = (
            "A recovery in earnings trend or business quality, or price reclaiming its long-term "
            "trend structure."
        )
    elif net_score <= -2:
        state = LongTermResearchState.REVIEW_POSITION
        reason = (
            "Multiple long-term factors are unfavorable -- this position's long-term case "
            "warrants a fresh look."
        )
        what_would_change = "Improvement in the specific factors flagged negative below."
    elif (
        net_score >= 3
        and factors.valuation != ValuationState.EXPENSIVE
        and factors.long_term_trend == LongTermTrendState.CONSTRUCTIVE
    ):
        state = LongTermResearchState.ACCUMULATION_CANDIDATE
        reason = (
            "A majority of long-term factors are favorable, valuation is not stretched, and the "
            "long-term trend is constructive."
        )
        what_would_change = "Valuation becoming expensive, or the long-term trend turning weak."
    elif net_score >= 2:
        state = LongTermResearchState.LONG_TERM_THESIS_STRENGTHENING
        reason = (
            "Long-term evidence is improving but not yet unanimous enough to call this an "
            "accumulation candidate."
        )
        what_would_change = (
            "One or two more factors turning favorable, particularly valuation or long-term trend."
        )
    elif net_score == 1:
        state = LongTermResearchState.WATCH_FOR_BETTER_ENTRY
        reason = "Evidence is mildly favorable but not strong enough yet to justify accumulation."
        what_would_change = "Additional favorable factors, or price reaching a more attractive level."
    elif net_score == 0:
        state = LongTermResearchState.HOLDING_THESIS_INTACT
        reason = "Evidence is balanced -- no strong case to add or to exit."
        what_would_change = "A clear shift of two or more factors in either direction."
    elif net_score == -1:
        state = LongTermResearchState.LONG_TERM_THESIS_WEAKENING
        reason = (
            "More long-term factors are unfavorable than favorable, though not yet severe "
            "enough for a full review."
        )
        what_would_change = (
            "Further deterioration would trigger REVIEW POSITION; improvement would restore "
            "HOLDING THESIS INTACT."
        )
    else:  # pragma: no cover -- net_score is bounded to [-5, 5] by construction; no other branch reachable
        state = LongTermResearchState.WATCH_FOR_BETTER_ENTRY
        reason = "Evidence does not yet support an accumulation case."
        what_would_change = "Improvement in the unfavorable factors below."

    if factors.limited_history:
        evidence_quality = (
            LongTermEvidenceQuality.WEAK if available_count <= 3 else LongTermEvidenceQuality.MODERATE
        )
    elif contradictions:
        evidence_quality = LongTermEvidenceQuality.MODERATE
    elif available_count == 5:
        evidence_quality = LongTermEvidenceQuality.STRONG
    elif available_count == 4:
        evidence_quality = LongTermEvidenceQuality.MODERATE
    else:
        evidence_quality = LongTermEvidenceQuality.WEAK

    return LongTermRuleResult(
        state=state,
        evidence_quality=evidence_quality,
        positive_evidence=positive_evidence,
        negative_evidence=negative_evidence,
        contradictions=contradictions,
        missing_evidence=missing_evidence,
        reason=reason,
        what_would_change_state=what_would_change,
    )
