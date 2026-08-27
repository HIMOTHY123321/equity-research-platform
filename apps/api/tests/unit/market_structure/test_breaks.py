import pytest

from app.market_structure.breaks import apply_break_state, detect_breaks_of_structure
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


def _candles(hour_close_pairs):
    return [bar(h, max(c, 15) + 1, min(c, 15) - 1, close=c) for h, c in hour_close_pairs]


def test_bullish_close_break():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16), (6, 17)])

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].direction == Direction.BULLISH
    assert events[0].broken_level == pytest.approx(15)
    assert events[0].broken_swing_timestamp == swing_high.pivot_timestamp
    assert events[0].break_timestamp == candles[5].timestamp
    assert events[0].distance_beyond_level == pytest.approx(1.0)


def test_bearish_close_break():
    swing_low = make_swing(SwingType.LOW, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles([(0, 18), (1, 17), (2, 16), (3, 16), (4, 16), (5, 14), (6, 13)])

    events = detect_breaks_of_structure(candles, [swing_low], DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].direction == Direction.BEARISH
    assert events[0].broken_level == pytest.approx(15)
    assert events[0].distance_beyond_level == pytest.approx(1.0)


def test_wick_only_break_does_not_count():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = [
        bar(0, 15, 5, close=12),
        bar(1, 15, 5, close=13),
        bar(2, 15, 5, close=14),
        bar(3, 15, 5, close=14),
        bar(4, 15, 5, close=14),
        bar(5, 20, 5, close=14.5),  # high pokes way above 15, close stays under
    ]

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)
    assert events == []


def test_exact_level_equality_does_not_count():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 15)])

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)
    assert events == []


def test_tolerance_requires_close_beyond_the_configured_buffer():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    config = MarketStructureConfig(bos_tolerance_percent=1.0)  # threshold = 15.15
    within_tolerance = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 15.10)])
    beyond_tolerance = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 15.20)])

    assert detect_breaks_of_structure(within_tolerance, [swing_high], config) == []
    events = detect_breaks_of_structure(beyond_tolerance, [swing_high], config)
    assert len(events) == 1


def test_same_level_does_not_generate_repeated_events():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles(
        [(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16), (6, 17), (7, 18), (8, 19)]
    )

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)
    assert len(events) == 1  # only the first breach, not every subsequent bar


def test_swing_not_yet_confirmed_cannot_be_broken_early():
    # confirmed_at (7:30) is strictly after the hour-5 candle's own
    # completion (6:30), so its close beyond the level must NOT count yet;
    # the hour-6 candle's completion (7:30) is when confirmation lands, so
    # the break is only recognized there.
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=7)
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16), (6, 17)])

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].break_timestamp == candles[6].timestamp


def test_break_allowed_when_confirmation_and_candle_completion_are_simultaneous():
    # confirmed_at exactly equals the breaking candle's own completion
    # instant (both facts become knowable at literally the same moment) --
    # this is NOT lookahead, so the break must be recognized, not withheld.
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=6)
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16)])

    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)

    assert len(events) == 1
    assert events[0].break_timestamp == candles[5].timestamp


def test_extending_candles_forward_never_changes_earlier_events():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles(
        [(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16), (6, 17), (7, 18), (8, 19)]
    )

    events_short = detect_breaks_of_structure(candles[:6], [swing_high], DEFAULT_CONFIG)
    events_long = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)

    assert events_short == events_long


def test_apply_break_state_annotates_matching_swing():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 16)])
    events = detect_breaks_of_structure(candles, [swing_high], DEFAULT_CONFIG)

    annotated = apply_break_state([swing_high], events)

    assert annotated[0].is_broken is True
    assert annotated[0].break_direction == Direction.BULLISH
    assert annotated[0].first_broken_at == events[0].break_timestamp


def test_apply_break_state_leaves_unbroken_swings_untouched():
    swing_high = make_swing(SwingType.HIGH, 15, pivot_hour=2, confirmed_hour=4)
    annotated = apply_break_state([swing_high], [])
    assert annotated[0].is_broken is False
    assert annotated[0].first_broken_at is None


def test_apply_break_state_does_not_cross_contaminate_high_and_low_at_the_same_pivot_timestamp():
    # Real-data regression (found 2026-08-24 on live SPY 1H data): a single
    # candle can legitimately be both a swing high and a swing low pivot at
    # once (a wide-range bar whose neighbors sit inside its range on both
    # sides). A bearish break of the LOW at that timestamp must never be
    # applied to the unrelated HIGH sharing the same pivot_timestamp.
    swing_high = make_swing(SwingType.HIGH, 20, pivot_hour=2, confirmed_hour=4)
    swing_low = make_swing(SwingType.LOW, 10, pivot_hour=2, confirmed_hour=4)
    assert swing_high.pivot_timestamp == swing_low.pivot_timestamp

    # Only the low ever gets broken; the high never does (closes stay under 20).
    candles = _candles([(0, 12), (1, 13), (2, 14), (3, 14), (4, 14), (5, 8)])

    events = detect_breaks_of_structure(candles, [swing_high, swing_low], DEFAULT_CONFIG)
    assert len(events) == 1
    assert events[0].direction == Direction.BEARISH

    annotated = apply_break_state([swing_high, swing_low], events)
    annotated_high = next(s for s in annotated if s.type == SwingType.HIGH)
    annotated_low = next(s for s in annotated if s.type == SwingType.LOW)

    assert annotated_low.is_broken is True
    assert annotated_low.break_direction == Direction.BEARISH
    assert annotated_high.is_broken is False
    assert annotated_high.break_direction is None
