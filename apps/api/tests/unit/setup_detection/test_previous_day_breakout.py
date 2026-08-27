from dataclasses import replace

from app.market_structure.schemas import Direction
from app.setup_detection.config import SetupDetectionConfig
from app.setup_detection.detectors import previous_day_breakout
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar


def _series_with_pdh(breakout_close):
    day17 = flat_session(17, price=100.0)
    day17[3] = hour_bar(17, 13, 105.0, 99.0, close=100.0)  # day high = 105
    day18 = [
        hour_bar(18, h, breakout_close + 1, breakout_close - 1, close=breakout_close) for h in range(10, 16)
    ]
    return day17 + day18


def test_confirmed_close_above_pdh_qualifies():
    inputs = build_inputs(_series_with_pdh(106.0))
    candidates = previous_day_breakout.detect(inputs)
    matches = [c for c in candidates if c.setup_type.value == "previous_day_high_breakout"]
    assert len(matches) == 1
    assert matches[0].direction == Direction.BULLISH
    assert matches[0].current_state.value == "qualified"
    assert matches[0].reference_price == 105.0


def test_exact_level_equality_never_counts_as_breakout():
    inputs = build_inputs(_series_with_pdh(105.0))
    candidates = previous_day_breakout.detect(inputs)
    assert not [c for c in candidates if c.setup_type.value == "previous_day_high_breakout"]


def test_close_below_pdh_produces_no_candidate():
    inputs = build_inputs(_series_with_pdh(103.0))
    candidates = previous_day_breakout.detect(inputs)
    assert not [c for c in candidates if c.setup_type.value == "previous_day_high_breakout"]


def test_tolerance_requires_close_beyond_configured_buffer():
    config = replace(SetupDetectionConfig(), breakout_tolerance_percent=1.0)  # threshold = 106.05
    within_tolerance = build_inputs(_series_with_pdh(106.0), config=config)
    beyond_tolerance = build_inputs(_series_with_pdh(106.10), config=config)

    assert not [
        c
        for c in previous_day_breakout.detect(within_tolerance)
        if c.setup_type.value == "previous_day_high_breakout"
    ]
    assert [
        c
        for c in previous_day_breakout.detect(beyond_tolerance)
        if c.setup_type.value == "previous_day_high_breakout"
    ]


def test_only_the_first_breakout_bar_creates_a_candidate():
    """Duplicate-signal suppression (#26): once PDH breaks, later bars still
    closing above it don't create a second candidate for the same day."""
    day17 = flat_session(17, price=100.0)
    day17[3] = hour_bar(17, 13, 105.0, 99.0, close=100.0)
    day18 = [hour_bar(18, h, 108.0, 104.0, close=106.0) for h in range(10, 16)]
    inputs = build_inputs(day17 + day18)

    candidates = [
        c for c in previous_day_breakout.detect(inputs) if c.setup_type.value == "previous_day_high_breakout"
    ]
    assert len(candidates) == 1


def test_previous_day_low_breakdown_is_bearish():
    day17 = flat_session(17, price=100.0)
    day17[3] = hour_bar(17, 13, 101.0, 95.0, close=100.0)  # day low = 95
    day18 = [hour_bar(18, h, 95.0, 93.0, close=94.0) for h in range(10, 16)]
    inputs = build_inputs(day17 + day18)

    matches = [
        c for c in previous_day_breakout.detect(inputs) if c.setup_type.value == "previous_day_low_breakdown"
    ]
    assert len(matches) == 1
    assert matches[0].direction == Direction.BEARISH
    assert matches[0].reference_price == 95.0
