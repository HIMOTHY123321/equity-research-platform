from app.market_structure.schemas import Direction
from app.setup_detection.detectors import previous_week_breakout
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar


def test_confirmed_close_above_pwh_qualifies():
    # Week of Aug 10-14 (Mon-Fri): engineer a known week high on Wed the 12th.
    week1 = flat_session(10, price=100.0) + flat_session(11, price=100.0)
    week1 += [hour_bar(12, 13, 110.0, 99.0, close=100.0)]  # week high = 110
    week1 += flat_session(13, price=100.0) + flat_session(14, price=100.0)
    week2 = [hour_bar(17, h, 112.0, 108.0, close=111.0) for h in range(10, 16)]

    inputs = build_inputs(week1 + week2)
    matches = [
        c
        for c in previous_week_breakout.detect(inputs)
        if c.setup_type.value == "previous_week_high_breakout"
    ]
    assert len(matches) == 1
    assert matches[0].direction == Direction.BULLISH
    assert matches[0].reference_price == 110.0


def test_close_below_pwh_produces_no_candidate():
    week1 = flat_session(10, price=100.0) + flat_session(11, price=100.0)
    week1 += [hour_bar(12, 13, 110.0, 99.0, close=100.0)]
    week1 += flat_session(13, price=100.0) + flat_session(14, price=100.0)
    week2 = [hour_bar(17, h, 108.0, 105.0, close=107.0) for h in range(10, 16)]

    inputs = build_inputs(week1 + week2)
    assert not [
        c
        for c in previous_week_breakout.detect(inputs)
        if c.setup_type.value == "previous_week_high_breakout"
    ]


def test_previous_week_low_breakdown_is_bearish():
    week1 = flat_session(10, price=100.0) + flat_session(11, price=100.0)
    week1 += [hour_bar(12, 13, 101.0, 90.0, close=100.0)]  # week low = 90
    week1 += flat_session(13, price=100.0) + flat_session(14, price=100.0)
    week2 = [hour_bar(17, h, 89.0, 86.0, close=87.0) for h in range(10, 16)]

    inputs = build_inputs(week1 + week2)
    matches = [
        c
        for c in previous_week_breakout.detect(inputs)
        if c.setup_type.value == "previous_week_low_breakdown"
    ]
    assert len(matches) == 1
    assert matches[0].direction == Direction.BEARISH
    assert matches[0].reference_price == 90.0
