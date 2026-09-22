from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.market_data import Candle, Timeframe


def _candle(**overrides) -> dict:
    base = dict(
        symbol="AAPL",
        timeframe=Timeframe.ONE_DAY,
        timestamp=datetime(2026, 8, 21, tzinfo=timezone.utc),
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=1_000_000,
    )
    base.update(overrides)
    return base


def test_valid_candle_constructs():
    candle = Candle(**_candle())
    assert candle.symbol == "AAPL"
    assert candle.timeframe == Timeframe.ONE_DAY


def test_high_below_close_is_rejected():
    with pytest.raises(ValidationError):
        Candle(**_candle(high=101.0, close=103.0))


def test_low_above_open_is_rejected():
    with pytest.raises(ValidationError):
        Candle(**_candle(low=101.0, open=100.0))


def test_negative_volume_is_rejected():
    with pytest.raises(ValidationError):
        Candle(**_candle(volume=-5))


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_nan_price_is_rejected(field):
    """(MARKET EXPERIENCE COMPLETION PASS #0) Root cause of the
    EvidencePacket JSON 500: `nan < x` and `nan > x` are BOTH False in
    Python, so `ohlc_is_internally_consistent`'s comparisons never caught a
    NaN price -- it silently became a "valid" Candle and propagated into
    ATR/features/analog outcomes, which stdlib json.dumps then refuses to
    serialize. Every OHLC field must reject non-finite values at this one
    universal construction point, regardless of which provider/code path
    built the Candle."""
    with pytest.raises(ValidationError):
        Candle(**_candle(**{field: float("nan")}))


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_infinite_price_is_rejected(field):
    with pytest.raises(ValidationError):
        Candle(**_candle(**{field: float("inf")}))


def test_nan_volume_is_rejected():
    with pytest.raises(ValidationError):
        Candle(**_candle(volume=float("nan")))


def test_candle_is_immutable():
    candle = Candle(**_candle())
    with pytest.raises(ValidationError):
        candle.close = 999.0
