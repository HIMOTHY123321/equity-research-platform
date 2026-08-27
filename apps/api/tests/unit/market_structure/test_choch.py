import pytest

from app.market_structure.choch import detect_changes_of_character
from app.market_structure.classification import classify_swings
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import Direction, SwingPoint, SwingType
from tests.conftest import et
from tests.unit.market_structure.conftest import bar

DEFAULT_CONFIG = MarketStructureConfig()


def make_swing(type_, price, pivot_hour, confirmed_hour, day=17):
    return SwingPoint(
        type=type_,
        price=price,
        pivot_timestamp=et(2026, 8, day, pivot_hour, 30),
        confirmed_at=et(2026, 8, day, confirmed_hour, 30),
        left_bars=2,
        right_bars=2,
    )


def _neutral_candles(hours, close_by_hour=None):
    close_by_hour = close_by_hour or {}
    return [bar(h, 999, 1, close=close_by_hour.get(h, 110)) for h in hours]


def _bullish_structure_swings():
    # LOW 100 (none) -> HIGH 110 (none) -> LOW 105 (HL) -> HIGH 115 (HH)
    return classify_swings(
        [
            make_swing(SwingType.LOW, 100, 0, 2),
            make_swing(SwingType.HIGH, 110, 2, 4),
            make_swing(SwingType.LOW, 105, 4, 6),
            make_swing(SwingType.HIGH, 115, 6, 8),
        ],
        DEFAULT_CONFIG,
    )


def _bearish_structure_swings():
    # HIGH 110 (none) -> LOW 100 (none) -> HIGH 105 (LH) -> LOW 95 (LL)
    return classify_swings(
        [
            make_swing(SwingType.HIGH, 110, 0, 2),
            make_swing(SwingType.LOW, 100, 2, 4),
            make_swing(SwingType.HIGH, 105, 4, 6),
            make_swing(SwingType.LOW, 95, 6, 8),
        ],
        DEFAULT_CONFIG,
    )


def test_bullish_to_bearish_choch():
    swings = _bullish_structure_swings()
    candles = _neutral_candles(range(11), {9: 104})  # closes below the HL at 105

    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].direction == Direction.BEARISH
    assert events[0].prior_structure == Direction.BULLISH
    assert events[0].broken_level == pytest.approx(105)
    assert events[0].reference_swing_timestamp == et(2026, 8, 17, 4, 30)
    assert events[0].break_timestamp == et(2026, 8, 17, 9, 30)


def test_bearish_to_bullish_choch():
    swings = _bearish_structure_swings()
    candles = _neutral_candles(range(11), {9: 106})  # closes above the LH at 105

    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].direction == Direction.BULLISH
    assert events[0].prior_structure == Direction.BEARISH
    assert events[0].broken_level == pytest.approx(105)


def test_wick_only_does_not_trigger_choch():
    swings = _bullish_structure_swings()
    candles = [bar(h, 999, 1, close=110) for h in range(9)] + [
        bar(9, 999, 50, close=110)  # low wicks well below 105, close stays at 110
    ]

    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)
    assert events == []


def test_insufficient_prior_structure_emits_no_choch():
    # Only one swing ever confirms -> trend never leaves insufficient_data.
    swings = classify_swings([make_swing(SwingType.LOW, 100, 0, 2)], DEFAULT_CONFIG)
    candles = _neutral_candles(range(6), {5: 50})

    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)
    assert events == []


def test_repeated_closes_below_the_broken_level_do_not_duplicate():
    swings = _bullish_structure_swings()
    candles = _neutral_candles(range(13), {9: 104, 10: 103, 11: 102, 12: 101})

    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)
    assert len(events) == 1


def test_no_choch_without_a_qualifying_hl_or_lh():
    # Bullish trend requires HH+HL, but if only HH evidence exists (no HL
    # ever classified), there is no active_hl to break.
    swings = classify_swings(
        [
            make_swing(SwingType.HIGH, 100, 0, 2),
            make_swing(SwingType.HIGH, 110, 2, 4),
            make_swing(SwingType.HIGH, 120, 4, 6),
        ],
        DEFAULT_CONFIG,
    )
    candles = _neutral_candles(range(8), {7: 1})
    events = detect_changes_of_character(candles, swings, DEFAULT_CONFIG)
    assert events == []
