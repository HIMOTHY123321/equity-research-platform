import pytest

from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import SwingType
from app.market_structure.swings import detect_swings
from tests.unit.market_structure.conftest import bars

DEFAULT_CONFIG = MarketStructureConfig(left_bars=2, right_bars=2)


def test_obvious_swing_high():
    candles = bars([(0, 10, 5), (1, 11, 6), (2, 15, 10), (3, 11, 6), (4, 10, 5)])
    result = detect_swings(candles, DEFAULT_CONFIG)

    highs = [s for s in result.confirmed if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].price == pytest.approx(15)
    assert highs[0].pivot_timestamp == candles[2].timestamp


def test_obvious_swing_low():
    candles = bars([(0, 20, 15), (1, 19, 14), (2, 18, 5), (3, 19, 14), (4, 20, 15)])
    result = detect_swings(candles, DEFAULT_CONFIG)

    lows = [s for s in result.confirmed if s.type == SwingType.LOW]
    assert len(lows) == 1
    assert lows[0].price == pytest.approx(5)
    assert lows[0].pivot_timestamp == candles[2].timestamp


def test_multiple_swings_detected_independently():
    candles = bars(
        [
            (0, 10, 5),
            (1, 11, 6),
            (2, 15, 10),
            (3, 11, 6),
            (4, 10, 5),
            (5, 9, 4),
            (6, 9, 4),
            (7, 10, 5),
            (8, 11, 6),
            (9, 18, 13),
            (10, 11, 6),
            (11, 10, 5),
        ]
    )
    result = detect_swings(candles, DEFAULT_CONFIG)

    highs = [s for s in result.confirmed if s.type == SwingType.HIGH]
    assert {round(h.price) for h in highs} == {15, 18}
    assert len(highs) == 2


def test_no_swings_in_monotonic_series():
    candles = bars([(h, 10 + h, 5 + h) for h in range(8)])
    result = detect_swings(candles, DEFAULT_CONFIG)
    assert result.confirmed == []


def test_insufficient_candles_for_any_confirmation():
    candles = bars([(0, 10, 5), (1, 15, 10), (2, 11, 6), (3, 10, 5)])
    result = detect_swings(candles, DEFAULT_CONFIG)
    assert result.confirmed == []


def test_equal_high_tie_earliest_bar_wins():
    candles = bars([(0, 10, 5), (1, 11, 6), (2, 15, 10), (3, 15, 10), (4, 11, 6), (5, 10, 5)])
    result = detect_swings(candles, DEFAULT_CONFIG)

    highs = [s for s in result.confirmed if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].pivot_timestamp == candles[2].timestamp  # index 2 (earlier), not 3


def test_equal_low_tie_earliest_bar_wins():
    candles = bars([(0, 20, 15), (1, 19, 14), (2, 18, 5), (3, 18, 5), (4, 19, 14), (5, 20, 15)])
    result = detect_swings(candles, DEFAULT_CONFIG)

    lows = [s for s in result.confirmed if s.type == SwingType.LOW]
    assert len(lows) == 1
    assert lows[0].pivot_timestamp == candles[2].timestamp


def test_left_right_bars_are_configurable():
    candles = bars([(0, 10, 5), (1, 15, 10), (2, 11, 6), (3, 10, 5)])
    config = MarketStructureConfig(left_bars=1, right_bars=1)
    result = detect_swings(candles, config)

    highs = [s for s in result.confirmed if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].pivot_timestamp == candles[1].timestamp
    assert highs[0].left_bars == 1
    assert highs[0].right_bars == 1


def test_asymmetric_left_right_configuration():
    candles = bars([(0, 9, 4), (1, 10, 5), (2, 15, 10), (3, 11, 6)])
    config = MarketStructureConfig(left_bars=2, right_bars=1)
    result = detect_swings(candles, config)

    highs = [s for s in result.confirmed if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].pivot_timestamp == candles[2].timestamp


def test_candidate_pivot_not_yet_confirmed():
    # Only 1 right-side bar available; left_bars=2, right_bars=2 required.
    candles = bars([(0, 10, 5), (1, 11, 6), (2, 15, 10), (3, 11, 6)])
    result = detect_swings(candles, DEFAULT_CONFIG)

    assert result.confirmed == []
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.type == SwingType.HIGH
    assert candidate.pivot_timestamp == candles[2].timestamp
    assert candidate.right_bars_available == 1
    assert candidate.right_bars_required == 2


def test_pivot_becomes_confirmed_only_after_required_right_bars():
    partial = bars([(0, 10, 5), (1, 11, 6), (2, 15, 10), (3, 11, 6)])
    before = detect_swings(partial, DEFAULT_CONFIG)
    assert before.confirmed == []

    complete = partial + bars([(4, 10, 5)])
    after = detect_swings(complete, DEFAULT_CONFIG)

    assert len(after.confirmed) == 1
    swing = after.confirmed[0]
    assert swing.pivot_timestamp == complete[2].timestamp
    assert swing.confirmed_at == candle_complete_at(complete[4])
    assert swing.confirmed_at > swing.pivot_timestamp
