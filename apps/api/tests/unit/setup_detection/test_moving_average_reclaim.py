from datetime import date, timedelta

from app.market_structure.schemas import Direction
from app.setup_detection.detectors import moving_average_reclaim
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar


def _weekdays(start: date, count: int):
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:  # Mon-Fri
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _series_with_ema_cross():
    # 40 flat weekday sessions (240 bars) so EMA20/SMA50/SMA200 all have
    # enough history and settle near 100. The second-to-last day dips
    # clearly below the (lagging) EMA, then the final day closes decisively
    # back above it -- a real "was below, now above" reclaim, not an
    # exact-equality edge case (a perfectly flat series' EMA always equals
    # that flat price exactly, which would never trigger "was below").
    weekdays = _weekdays(date(2026, 1, 5), 40)
    candles = []
    for d in weekdays[:-2]:
        candles += flat_session(d.day, price=100.0, month=d.month, year=d.year)

    dip_day = weekdays[-2]
    candles += [
        hour_bar(dip_day.day, h, 98.0, 96.0, close=97.0, month=dip_day.month, year=dip_day.year)
        for h in range(10, 16)
    ]

    last = weekdays[-1]
    candles += [
        hour_bar(last.day, h, 106.0, 104.0, close=105.0, month=last.month, year=last.year)
        for h in range(10, 16)
    ]
    return candles


def test_close_above_ema20_after_being_below_qualifies():
    inputs = build_inputs(_series_with_ema_cross())
    matches = [
        c
        for c in moving_average_reclaim.detect(inputs)
        if c.metadata.get("moving_average") == "ema20" and c.direction == Direction.BULLISH
    ]
    assert matches, "expected an EMA20 bullish reclaim candidate"
    assert matches[0].current_state.value == "qualified"


def test_no_reclaim_when_price_never_crosses():
    weekdays = _weekdays(date(2026, 1, 5), 40)
    candles = []
    for d in weekdays:
        candles += flat_session(d.day, price=100.0, month=d.month, year=d.year)
    inputs = build_inputs(candles)
    assert not moving_average_reclaim.detect(inputs)
