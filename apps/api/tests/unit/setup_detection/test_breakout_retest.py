from datetime import timedelta

from app.market_structure.schemas import Direction
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.detectors import breakout_retest
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _bar(after, close, high=None, low=None, volume=50_000):
    return Candle(
        symbol=after.symbol,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=after.timestamp + timedelta(hours=1),
        session=MarketSession.REGULAR,
        open=close,
        high=high if high is not None else close + 0.3,
        low=low if low is not None else close - 0.3,
        close=close,
        volume=volume,
    )


def test_breakout_then_holding_retest_qualifies_at_the_retest_bar():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high
    assert pdh is not None

    breakout = _bar(SPY_1H[-1], close=pdh + 2.0)
    drift = _bar(breakout, close=pdh + 3.0)
    retest = _bar(drift, close=pdh + 0.5, low=pdh - 0.2)  # dips to the level, closes back above
    as_of = retest.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [breakout, drift, retest], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in breakout_retest.detect(inputs) if c.reference_source == "previous_day_high"]
    assert matches
    match = matches[0]
    assert match.direction == Direction.BULLISH
    assert match.current_state.value == "qualified"
    assert match.candidate_candle_timestamp == breakout.timestamp  # created at the breakout, not the retest
    assert match.triggered_at == retest.timestamp


def test_retest_that_fails_to_hold_is_rejected():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high

    breakout = _bar(SPY_1H[-1], close=pdh + 2.0)
    drift = _bar(breakout, close=pdh + 3.0)
    failed_retest = _bar(drift, close=pdh - 1.0, low=pdh - 1.5)  # closes back through the level
    as_of = failed_retest.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [breakout, drift, failed_retest], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in breakout_retest.detect(inputs) if c.reference_source == "previous_day_high"]
    assert matches
    assert matches[0].current_state.value == "rejected"


def test_breakout_without_any_retest_yet_is_not_reported_by_this_detector():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high

    breakout = _bar(SPY_1H[-1], close=pdh + 2.0)
    as_of = breakout.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [breakout], daily_candles=SPY_1D, as_of=as_of)

    assert not [c for c in breakout_retest.detect(inputs) if c.reference_source == "previous_day_high"]
