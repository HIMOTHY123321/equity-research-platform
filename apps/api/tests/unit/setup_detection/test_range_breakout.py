from datetime import timedelta

from app.market_structure.schemas import Direction
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.detectors import range_breakout
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _active_range():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    return inputs.structure_by_timeframe[inputs.timeframe].active_range


def _append_bar(price):
    last = SPY_1H[-1]
    return Candle(
        symbol=last.symbol,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=last.timestamp + timedelta(hours=1),
        session=MarketSession.REGULAR,
        open=price,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=50_000,
    )


def test_close_above_active_range_high_qualifies():
    active_range = _active_range()
    extra = _append_bar(active_range.high + 2.0)
    as_of = extra.timestamp + timedelta(hours=1)  # the extra bar must itself be *completed*
    inputs = build_inputs(SPY_1H + [extra], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in range_breakout.detect(inputs) if c.direction == Direction.BULLISH]
    assert matches, "expected a bullish range breakout candidate"
    assert matches[0].reference_price == active_range.high


def test_close_inside_range_produces_no_candidate():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    assert not range_breakout.detect(inputs)
