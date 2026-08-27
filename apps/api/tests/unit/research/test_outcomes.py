"""Hand-calculated outcome fixtures (#48). Every expected value below was
computed by hand from the fixture candles, not derived from the code under
test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.market_structure.schemas import Direction
from app.research.outcomes import compute_excursion, compute_horizon_outcomes, forward_candles
from app.schemas.market_data import Candle, MarketSession, Timeframe


def _c(hour, o, h, l, cl, v=1000):  # noqa: E741
    return Candle(
        symbol="T",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour),
        session=MarketSession.REGULAR,
        open=o,
        high=h,
        low=l,
        close=cl,
        volume=v,
    )


# Bar 0 = detection candle, close = 100 (base price). Bars 1-3 are "future".
_BULLISH_CANDLES = [
    _c(0, 99, 101, 98, 100),
    _c(1, 100, 106, 99, 101),
    _c(2, 101, 103, 95, 96),
    _c(3, 96, 98, 94, 97),
]


def test_bullish_forward_return_horizon_1():
    future = forward_candles(_BULLISH_CANDLES, _BULLISH_CANDLES[0].timestamp)
    horizons = compute_horizon_outcomes(future, 100.0, Direction.BULLISH, (1,))
    assert horizons[0].available
    assert horizons[0].future_close == pytest.approx(101.0)
    assert horizons[0].absolute_change == pytest.approx(1.0)
    assert horizons[0].raw_return_percent == pytest.approx(1.0)
    assert horizons[0].directional_return_percent == pytest.approx(1.0)


def test_bullish_forward_return_horizon_3_is_negative():
    future = forward_candles(_BULLISH_CANDLES, _BULLISH_CANDLES[0].timestamp)
    horizons = compute_horizon_outcomes(future, 100.0, Direction.BULLISH, (3,))
    assert horizons[0].available
    assert horizons[0].future_close == pytest.approx(97.0)
    assert horizons[0].directional_return_percent == pytest.approx(-3.0)


def test_bearish_directional_adjustment_flips_sign():
    candles = [_c(0, 100, 101, 98, 100), _c(1, 100, 101, 94, 95)]
    future = forward_candles(candles, candles[0].timestamp)
    horizons = compute_horizon_outcomes(future, 100.0, Direction.BEARISH, (1,))
    # Price fell 5% -- raw_return is -5%, but that's FAVORABLE for a bearish
    # setup, so directional_return must be +5%.
    assert horizons[0].raw_return_percent == pytest.approx(-5.0)
    assert horizons[0].directional_return_percent == pytest.approx(5.0)


def test_mfe_bullish_uses_high_and_is_directionally_positive():
    future = forward_candles(_BULLISH_CANDLES, _BULLISH_CANDLES[0].timestamp)
    mfe = compute_excursion(future, 100.0, Direction.BULLISH, atr=2.0, favorable=True)
    assert mfe.absolute == pytest.approx(6.0)  # bar1 high = 106
    assert mfe.percent == pytest.approx(6.0)
    assert mfe.atr == pytest.approx(3.0)
    assert mfe.bars_until == 1


def test_mae_bullish_uses_low_and_is_directionally_negative():
    future = forward_candles(_BULLISH_CANDLES, _BULLISH_CANDLES[0].timestamp)
    mae = compute_excursion(future, 100.0, Direction.BULLISH, atr=2.0, favorable=False)
    assert mae.absolute == pytest.approx(-6.0)  # bar3 low = 94
    assert mae.atr == pytest.approx(-3.0)
    assert mae.bars_until == 3


def test_mfe_bearish_uses_low_mae_uses_high():
    candles = [
        _c(0, 100, 101, 98, 100),
        _c(1, 100, 101, 94, 95),
        _c(2, 95, 105, 94, 104),
        _c(3, 104, 106, 103, 105),
    ]
    future = forward_candles(candles, candles[0].timestamp)
    mfe = compute_excursion(future, 100.0, Direction.BEARISH, atr=2.0, favorable=True)
    mae = compute_excursion(future, 100.0, Direction.BEARISH, atr=2.0, favorable=False)
    assert mfe.absolute == pytest.approx(6.0)  # lowest low = 94 -> 100-94=+6
    assert mfe.bars_until == 1
    assert mae.absolute == pytest.approx(-6.0)  # highest high = 106 -> 100-106=-6
    assert mae.bars_until == 3


def test_horizon_unavailable_when_insufficient_future_bars():
    future = forward_candles(_BULLISH_CANDLES, _BULLISH_CANDLES[0].timestamp)  # only 3 future bars
    horizons = compute_horizon_outcomes(future, 100.0, Direction.BULLISH, (1, 3, 5, 10, 20))
    available = {h.horizon_bars: h.available for h in horizons}
    assert available == {1: True, 3: True, 5: False, 10: False, 20: False}
    for h in horizons:
        if not h.available:
            assert h.future_close is None
            assert h.directional_return_percent is None


def test_no_future_candles_gives_fully_unavailable_excursions():
    mfe = compute_excursion([], 100.0, Direction.BULLISH, atr=2.0, favorable=True)
    assert mfe.absolute is None
    assert mfe.bars_until is None
