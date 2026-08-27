from datetime import timedelta

from app.market_structure.schemas import Direction
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.detectors import support_reclaim
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _append_bar(after, close, high=None, low=None, volume=50_000):
    return Candle(
        symbol=after.symbol,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=after.timestamp + timedelta(hours=1),
        session=MarketSession.REGULAR,
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
    )


def test_reclaim_requires_a_genuine_prior_close_below_and_a_close_back_above():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    zone = inputs0.levels_snapshot.nearest_support
    assert zone is not None
    level = zone.representative_price

    below = _append_bar(SPY_1H[-1], close=level - 2.0)
    reclaim = _append_bar(below, close=level + 2.0)
    as_of = reclaim.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [below, reclaim], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in support_reclaim.detect(inputs) if c.direction == Direction.BULLISH]
    assert matches
    assert matches[0].candidate_candle_timestamp == reclaim.timestamp
    assert matches[0].reference_price == level


def test_appending_a_steady_bar_above_the_level_creates_no_new_reclaim_for_it():
    """A bar that never traded below the level can't itself be "the"
    reclaim bar -- checked against this specific appended candle rather
    than the whole snapshot, since real historical data can legitimately
    contain its own genuine (unrelated) reclaims elsewhere in the window."""
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    zone = inputs0.levels_snapshot.nearest_support
    level = zone.representative_price

    steady = _append_bar(SPY_1H[-1], close=level + 3.0)
    as_of = steady.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [steady], daily_candles=SPY_1D, as_of=as_of)

    assert steady.timestamp not in {c.candidate_candle_timestamp for c in support_reclaim.detect(inputs)}
