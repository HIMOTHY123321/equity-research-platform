from datetime import timedelta

from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.detectors import failed_breakout
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


def test_wick_only_breach_is_rejected_immediately():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high

    wick = _bar(SPY_1H[-1], close=pdh - 0.5, high=pdh + 1.0)  # wicks above, closes back below
    as_of = wick.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [wick], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in failed_breakout.detect(inputs) if c.reference_source == "previous_day_high"]
    assert matches
    assert matches[0].setup_type.value == "wick_failed_breakout"
    assert matches[0].current_state.value == "rejected"
    assert matches[0].candidate_candle_timestamp == wick.timestamp


def test_confirmed_breakout_that_reverses_within_window_is_invalidated():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high

    breakout = _bar(SPY_1H[-1], close=pdh + 2.0)
    reversal = _bar(breakout, close=pdh - 1.0)
    as_of = reversal.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [breakout, reversal], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in failed_breakout.detect(inputs) if c.reference_source == "previous_day_high"]
    assert matches
    assert matches[0].setup_type.value == "confirmed_breakout_failure"
    assert matches[0].current_state.value == "invalidated"
    assert matches[0].candidate_candle_timestamp == breakout.timestamp
    assert matches[0].invalidated_at == reversal.timestamp


def test_confirmed_breakout_that_holds_produces_no_failure_candidate():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    pdh = inputs0.feature_snapshot.previous_day.high

    breakout = _bar(SPY_1H[-1], close=pdh + 2.0)
    holding = _bar(breakout, close=pdh + 2.5)
    as_of = holding.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [breakout, holding], daily_candles=SPY_1D, as_of=as_of)

    assert not [c for c in failed_breakout.detect(inputs) if c.reference_source == "previous_day_high"]
