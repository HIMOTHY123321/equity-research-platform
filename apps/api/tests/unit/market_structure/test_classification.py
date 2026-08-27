import pytest

from app.market_structure.classification import classify_swings, classify_trend
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import SwingClassification, SwingPoint, SwingType, TrendClass, TrendStrength
from tests.conftest import et

CONFIG = MarketStructureConfig(equal_tolerance_percent=0.1, structure_lookback_swings=4)


def swing(type_, price, hour, day=17):  # noqa: A002
    ts = et(2026, 8, day, hour, 30)
    return SwingPoint(
        type=type_,
        price=price,
        pivot_timestamp=ts,
        confirmed_at=et(2026, 8, day, hour + 2, 30),
        left_bars=2,
        right_bars=2,
    )


# ---- HH/HL/LH/LL/EH/EL --------------------------------------------------


def test_higher_high():
    swings = [swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 110, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.HIGHER_HIGH
    assert result[1].previous_comparable_price == pytest.approx(100)


def test_lower_high():
    swings = [swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 90, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.LOWER_HIGH


def test_equal_high_within_tolerance():
    swings = [swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 100.05, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.EQUAL_HIGH


def test_higher_low():
    swings = [swing(SwingType.LOW, 100, 0), swing(SwingType.LOW, 105, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.HIGHER_LOW


def test_lower_low():
    swings = [swing(SwingType.LOW, 100, 0), swing(SwingType.LOW, 95, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.LOWER_LOW


def test_equal_low_within_tolerance():
    swings = [swing(SwingType.LOW, 100, 0), swing(SwingType.LOW, 99.95, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.EQUAL_LOW


def test_tolerance_edge_exactly_at_boundary_is_equal():
    # 0.1% tolerance of 100 = 0.10 exactly
    swings = [swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 100.10, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.EQUAL_HIGH


def test_tolerance_edge_just_beyond_boundary_is_not_equal():
    swings = [swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 100.11, 4)]
    result = classify_swings(swings, CONFIG)
    assert result[1].classification == SwingClassification.HIGHER_HIGH


def test_first_swing_of_a_type_has_no_classification():
    swings = [swing(SwingType.HIGH, 100, 0)]
    result = classify_swings(swings, CONFIG)
    assert result[0].classification is None
    assert result[0].previous_comparable_price is None


def test_highs_and_lows_are_never_cross_compared():
    # Interleave: a low should only ever be compared to the PREVIOUS low,
    # never to an intervening high, and vice versa.
    swings = [
        swing(SwingType.LOW, 100, 0),
        swing(SwingType.HIGH, 500, 2),  # wildly different scale, must not affect the low comparison
        swing(SwingType.LOW, 105, 4),
        swing(SwingType.HIGH, 10, 6),  # wildly different scale, must not affect the high comparison
    ]
    result = classify_swings(swings, CONFIG)
    low2 = next(s for s in result if s.type == SwingType.LOW and s.price == 105)
    high2 = next(s for s in result if s.type == SwingType.HIGH and s.price == 10)

    assert low2.classification == SwingClassification.HIGHER_LOW
    assert low2.previous_comparable_price == pytest.approx(100)
    assert high2.classification == SwingClassification.LOWER_HIGH
    assert high2.previous_comparable_price == pytest.approx(500)


# ---- Trend classification -----------------------------------------------


def test_clear_bullish_structure():
    swings = classify_swings(
        [
            swing(SwingType.LOW, 100, 0),
            swing(SwingType.HIGH, 110, 2),
            swing(SwingType.LOW, 105, 4),
            swing(SwingType.HIGH, 115, 6),
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.BULLISH
    assert result.strength in (TrendStrength.DEVELOPING, TrendStrength.ESTABLISHED)
    assert len(result.evidence) > 0


def test_clear_bearish_structure():
    swings = classify_swings(
        [
            swing(SwingType.HIGH, 110, 0),
            swing(SwingType.LOW, 100, 2),
            swing(SwingType.HIGH, 105, 4),
            swing(SwingType.LOW, 95, 6),
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.BEARISH


def test_established_requires_enough_evidence():
    swings = classify_swings(
        [
            swing(SwingType.LOW, 100, 0),
            swing(SwingType.HIGH, 110, 2),
            swing(SwingType.LOW, 105, 4),
            swing(SwingType.HIGH, 115, 6),
            swing(SwingType.LOW, 108, 8),
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.BULLISH
    assert result.strength == TrendStrength.ESTABLISHED


def test_ranging_on_tied_contradictory_evidence():
    swings = classify_swings(
        [
            swing(SwingType.LOW, 100, 0),
            swing(SwingType.HIGH, 110, 2),
            swing(SwingType.LOW, 90, 4),  # a lower low, tied 1-1 against the one HH
            swing(SwingType.HIGH, 115, 6),
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    # bull_evidence=[HH] (1), bear_evidence=[LL] (1) -- a genuine tie stays ranging.
    assert result.trend == TrendClass.RANGING


def test_majority_bullish_evidence_wins_over_a_single_contradicting_swing():
    # Real-data motivated (see ADR 0004): SPY/QQQ/NVDA all showed exactly
    # this HH/LH/HL/HH shape -- a clear bullish majority (3 pieces of
    # evidence) with one minor pullback (1 LH) -- and the old
    # zero-contradiction rule classified all of them "ranging" despite a
    # textbook bullish EMA20>SMA50>SMA200 stack underneath. Majority now wins.
    swings = classify_swings(
        [
            swing(SwingType.LOW, 100, 0),
            swing(SwingType.HIGH, 110, 2),
            swing(SwingType.HIGH, 108, 4),  # LH: one contradicting pullback
            swing(SwingType.LOW, 105, 6),  # HL
            swing(SwingType.HIGH, 115, 8),  # HH
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.BULLISH


def test_majority_bearish_evidence_wins_over_a_single_contradicting_swing():
    swings = classify_swings(
        [
            swing(SwingType.HIGH, 110, 0),
            swing(SwingType.LOW, 100, 2),
            swing(SwingType.LOW, 102, 4),  # HL: one contradicting bounce
            swing(SwingType.HIGH, 98, 6),  # LH
            swing(SwingType.LOW, 90, 8),  # LL
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.BEARISH


def test_ranging_on_equal_highs_lows_only():
    swings = classify_swings(
        [
            swing(SwingType.HIGH, 100, 0),
            swing(SwingType.LOW, 90, 2),
            swing(SwingType.HIGH, 100.02, 4),
            swing(SwingType.LOW, 90.01, 6),
        ],
        CONFIG,
    )
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.RANGING


def test_insufficient_data_with_no_swings():
    result = classify_trend([], CONFIG)
    assert result.trend == TrendClass.INSUFFICIENT_DATA


def test_insufficient_data_with_only_one_classified_swing():
    swings = classify_swings([swing(SwingType.HIGH, 100, 0), swing(SwingType.HIGH, 110, 2)], CONFIG)
    # only 1 classified swing exists (the second one) -> insufficient
    result = classify_trend(swings, CONFIG)
    assert result.trend == TrendClass.INSUFFICIENT_DATA


def test_trend_only_considers_the_configured_lookback_window():
    # 6 bullish-evidence swings, but lookback=2 should ignore the older ones
    # and a contradictory swing just outside the window should not matter.
    swings = classify_swings(
        [
            swing(SwingType.LOW, 50, 0),  # contradictory ancient low, outside window
            swing(SwingType.HIGH, 200, 2),  # contradictory ancient high, outside window
            swing(SwingType.LOW, 100, 4),
            swing(SwingType.HIGH, 110, 6),
            swing(SwingType.LOW, 105, 8),
            swing(SwingType.HIGH, 115, 10),
        ],
        CONFIG,
    )
    short_lookback = MarketStructureConfig(structure_lookback_swings=2)
    result = classify_trend(swings, short_lookback)
    assert result.trend == TrendClass.BULLISH
