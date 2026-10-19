"""Long-Term Research: deterministic factor computation + state-selection
rules. Every test here operates on pure functions only -- no DB, no
network, no provider classes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.long_term_research.factors import build_factor_bundle
from app.long_term_research.rules import determine_research_state
from app.long_term_research.schemas import (
    FundamentalsSnapshot,
    LongTermEvidenceQuality,
    LongTermResearchState,
)
from tests.unit.long_term_research.helpers import (
    strong_positive_candles,
    strong_positive_fundamentals,
    weak_negative_candles,
    weak_negative_fundamentals,
)

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_strong_positive_evidence_produces_accumulation_candidate():
    factors = build_factor_bundle(strong_positive_fundamentals(AS_OF), strong_positive_candles(AS_OF), AS_OF)
    result = determine_research_state(factors)
    assert result.state == LongTermResearchState.ACCUMULATION_CANDIDATE
    assert result.evidence_quality == LongTermEvidenceQuality.STRONG
    assert result.positive_evidence
    assert result.negative_evidence == []


def test_weak_evidence_cannot_produce_accumulation_candidate():
    factors = build_factor_bundle(weak_negative_fundamentals(AS_OF), weak_negative_candles(AS_OF), AS_OF)
    result = determine_research_state(factors)
    assert result.state != LongTermResearchState.ACCUMULATION_CANDIDATE
    assert result.negative_evidence


def test_contradictory_evidence_is_surfaced():
    """Two factors favorable, two factors unfavorable, one neutral --
    the contradiction must be flagged regardless of which final state
    the net score lands on."""
    fundamentals = FundamentalsSnapshot(
        symbol="TEST",
        fetched_at=AS_OF,
        provider="fixture",
        # Business quality: favorable
        profit_margin=0.20,
        return_on_equity=0.18,
        debt_to_equity=40.0,
        free_cash_flow=100.0,
        # Earnings trend: unfavorable (declining EPS)
        quarterly_eps=[2.0, 1.8, 1.6, 1.4],
        # Growth: unfavorable (declining revenue/EPS YoY)
        quarterly_revenue=[200, 190, 180, 170, 160],
    )
    # quarterly_eps needs 5 entries for growth YoY; extend consistently.
    fundamentals = fundamentals.model_copy(update={"quarterly_eps": [2.2, 2.0, 1.8, 1.6, 1.4]})
    candles = strong_positive_candles(AS_OF)  # long_term_trend: favorable

    factors = build_factor_bundle(fundamentals, candles, AS_OF)
    # valuation will be NOT_ENOUGH_EVIDENCE (no trailing_pe/price_to_sales
    # and insufficient quarters for the own-history comparison) -- fine,
    # we still have 4 available factors: business_quality(+), growth(-),
    # earnings_trend(-), long_term_trend(+) => 2 positive, 2 negative.
    result = determine_research_state(factors)
    assert result.contradictions, (
        f"Expected a contradiction to be flagged; factors were "
        f"bq={factors.business_quality} et={factors.earnings_trend} val={factors.valuation} "
        f"gr={factors.growth} lt={factors.long_term_trend}"
    )


def test_missing_fundamentals_produce_not_enough_evidence_when_appropriate():
    """Only price history available, fundamentals entirely blank --
    business_quality/earnings_trend/growth/valuation all NOT_ENOUGH_
    EVIDENCE, leaving only long_term_trend available (1 of 5) -- below
    the minimum-3 threshold."""
    blank_fundamentals = FundamentalsSnapshot(symbol="TEST", fetched_at=AS_OF, provider="fixture")
    candles = strong_positive_candles(AS_OF)

    factors = build_factor_bundle(blank_fundamentals, candles, AS_OF)
    result = determine_research_state(factors)
    assert result.state == LongTermResearchState.NOT_ENOUGH_EVIDENCE
    assert result.evidence_quality == LongTermEvidenceQuality.NOT_ENOUGH_EVIDENCE
    assert result.missing_evidence


def test_limited_history_is_explicitly_labeled():
    """A recent-IPO-style symbol (e.g. SPCX) with only ~90 days of
    candles must be labeled LIMITED HISTORY (factors.limited_history),
    never silently treated as if years of history existed."""
    recent_candles = strong_positive_candles(AS_OF)[-90:]  # only the most recent 90 days
    factors = build_factor_bundle(strong_positive_fundamentals(AS_OF), recent_candles, AS_OF)
    assert factors.limited_history is True
    assert factors.history_days < 380


def test_ample_history_is_not_labeled_limited():
    factors = build_factor_bundle(strong_positive_fundamentals(AS_OF), strong_positive_candles(AS_OF), AS_OF)
    assert factors.limited_history is False


def test_limited_history_caps_evidence_quality_even_with_full_factor_coverage():
    recent_candles = strong_positive_candles(AS_OF)[-90:]
    factors = build_factor_bundle(strong_positive_fundamentals(AS_OF), recent_candles, AS_OF)
    result = determine_research_state(factors)
    assert result.evidence_quality != LongTermEvidenceQuality.STRONG


def test_daily_scan_rules_are_deterministic_for_identical_data():
    factors = build_factor_bundle(strong_positive_fundamentals(AS_OF), strong_positive_candles(AS_OF), AS_OF)
    first = determine_research_state(factors)
    second = determine_research_state(factors)
    assert first == second


def test_factor_computation_is_deterministic_for_identical_data():
    fundamentals = strong_positive_fundamentals(AS_OF)
    candles = strong_positive_candles(AS_OF)
    first = build_factor_bundle(fundamentals, candles, AS_OF)
    second = build_factor_bundle(fundamentals, candles, AS_OF)
    assert first == second


def test_factor_computation_never_uses_candles_after_as_of():
    """Anti-lookahead: appending future candles (timestamp > as_of) must
    never change the result -- build_factor_bundle defensively filters
    them out."""
    fundamentals = strong_positive_fundamentals(AS_OF)
    candles = strong_positive_candles(AS_OF)
    baseline = build_factor_bundle(fundamentals, candles, AS_OF)

    future_candles = list(candles)
    for i in range(1, 30):
        ts = AS_OF + timedelta(days=i)
        future_candles.append(candles[-1].model_copy(update={"timestamp": ts, "close": 99999.0}))

    with_future = build_factor_bundle(fundamentals, future_candles, AS_OF)
    assert with_future == baseline


def test_reason_and_what_would_change_are_always_populated():
    for fundamentals, candles in (
        (strong_positive_fundamentals(AS_OF), strong_positive_candles(AS_OF)),
        (weak_negative_fundamentals(AS_OF), weak_negative_candles(AS_OF)),
        (FundamentalsSnapshot(symbol="TEST", fetched_at=AS_OF, provider="fixture"), []),
    ):
        factors = build_factor_bundle(fundamentals, candles, AS_OF)
        result = determine_research_state(factors)
        assert result.reason
        assert result.what_would_change_state
