from app.market_data.normalization import (
    normalize_alpaca_bar,
    normalize_alpaca_bars,
    normalize_yfinance_bar,
    normalize_yfinance_bars,
)
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import alpaca_bar, utc


def test_normalize_single_bar_maps_fields_and_session():
    raw = alpaca_bar("2026-08-17T14:30:00Z", 100.0, 101.5, 99.5, 101.0, 5000)
    candle = normalize_alpaca_bar(raw, "AAPL", Timeframe.ONE_HOUR)

    assert candle.symbol == "AAPL"
    assert candle.timeframe == Timeframe.ONE_HOUR
    assert candle.open == 100.0
    assert candle.high == 101.5
    assert candle.low == 99.5
    assert candle.close == 101.0
    assert candle.volume == 5000
    # 14:30 UTC = 10:30 ET in August (EDT, UTC-4) -> regular session
    assert candle.session == MarketSession.REGULAR


def test_normalize_bars_sorts_out_of_order_input():
    bars = [
        alpaca_bar("2026-08-17T15:30:00Z", 1, 2, 0.5, 1.5, 10),
        alpaca_bar("2026-08-17T13:30:00Z", 1, 2, 0.5, 1.5, 10),
        alpaca_bar("2026-08-17T14:30:00Z", 1, 2, 0.5, 1.5, 10),
    ]
    result = normalize_alpaca_bars(bars, "AAPL", Timeframe.ONE_HOUR)

    assert [c.timestamp.hour for c in result.candles] == [13, 14, 15]
    assert result.rejected == []
    assert result.duplicates_dropped == 0


def test_normalize_bars_deduplicates_same_timestamp():
    bars = [
        alpaca_bar("2026-08-17T14:30:00Z", 1, 2, 0.5, 1.5, 10),
        alpaca_bar("2026-08-17T14:30:00Z", 1, 2, 0.5, 1.5, 10),
    ]
    result = normalize_alpaca_bars(bars, "AAPL", Timeframe.ONE_HOUR)

    assert len(result.candles) == 1
    assert result.duplicates_dropped == 1


def test_normalize_bars_collects_malformed_bars_without_dropping_valid_ones():
    bars = [
        alpaca_bar("2026-08-17T14:30:00Z", 100, 101, 99, 100.5, 10),
        {"t": "2026-08-17T15:30:00Z", "o": 100, "h": 90, "l": 99, "c": 100.5, "v": 10},  # bad OHLC
        {"t": "2026-08-17T16:30:00Z", "o": 100, "h": 101, "c": 100.5, "v": 10},  # missing "l"
        {"t": "not-a-timestamp", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10},
        alpaca_bar("2026-08-17T17:30:00Z", 100, 101, 99, 100.5, -5),  # negative volume
    ]
    result = normalize_alpaca_bars(bars, "AAPL", Timeframe.ONE_HOUR)

    assert len(result.candles) == 1
    assert len(result.rejected) == 4
    assert all(r.reason for r in result.rejected)


def test_normalize_empty_input_returns_empty_result():
    result = normalize_alpaca_bars([], "AAPL", Timeframe.ONE_HOUR)

    assert result.candles == []
    assert result.rejected == []
    assert result.duplicates_dropped == 0


# ---- yfinance -----------------------------------------------------------


def test_normalize_yfinance_single_row():
    ts = utc(2026, 8, 17, 14, 30)
    row = {"Open": 100.0, "High": 101.5, "Low": 99.5, "Close": 101.0, "Volume": 5000}

    candle = normalize_yfinance_bar(ts, row, "AAPL", Timeframe.ONE_HOUR)

    assert candle.symbol == "AAPL"
    assert candle.open == 100.0
    assert candle.high == 101.5
    assert candle.low == 99.5
    assert candle.close == 101.0
    assert candle.volume == 5000
    assert candle.session == MarketSession.REGULAR


def test_normalize_yfinance_rejects_naive_timestamp():
    from datetime import datetime

    row = {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000}
    result = normalize_yfinance_bars(
        [(datetime(2026, 8, 17, 14, 30), row)], "AAPL", Timeframe.ONE_HOUR
    )

    assert result.candles == []
    assert len(result.rejected) == 1


def test_normalize_yfinance_bars_sorts_out_of_order_input():
    row = {"Open": 1, "High": 2, "Low": 0.5, "Close": 1.5, "Volume": 10}
    rows = [
        (utc(2026, 8, 17, 15, 30), row),
        (utc(2026, 8, 17, 13, 30), row),
        (utc(2026, 8, 17, 14, 30), row),
    ]
    result = normalize_yfinance_bars(rows, "AAPL", Timeframe.ONE_HOUR)

    assert [c.timestamp.hour for c in result.candles] == [13, 14, 15]


def test_normalize_yfinance_bars_deduplicates_same_timestamp():
    row = {"Open": 1, "High": 2, "Low": 0.5, "Close": 1.5, "Volume": 10}
    ts = utc(2026, 8, 17, 14, 30)
    result = normalize_yfinance_bars([(ts, row), (ts, row)], "AAPL", Timeframe.ONE_HOUR)

    assert len(result.candles) == 1
    assert result.duplicates_dropped == 1


def test_normalize_yfinance_bars_collects_malformed_rows_without_dropping_valid_ones():
    good = {"Open": 100, "High": 101, "Low": 99, "Close": 100.5, "Volume": 10}
    bad_ohlc = {"Open": 100, "High": 90, "Low": 99, "Close": 100.5, "Volume": 10}
    missing_field = {"Open": 100, "High": 101, "Close": 100.5, "Volume": 10}
    negative_volume = {"Open": 100, "High": 101, "Low": 99, "Close": 100.5, "Volume": -5}

    rows = [
        (utc(2026, 8, 17, 14, 30), good),
        (utc(2026, 8, 17, 15, 30), bad_ohlc),
        (utc(2026, 8, 17, 16, 30), missing_field),
        (utc(2026, 8, 17, 17, 30), negative_volume),
    ]
    result = normalize_yfinance_bars(rows, "AAPL", Timeframe.ONE_HOUR)

    assert len(result.candles) == 1
    assert len(result.rejected) == 3
    assert all(r.reason for r in result.rejected)


def test_normalize_yfinance_zero_volume_is_valid_not_rejected():
    row = {"Open": 100, "High": 101, "Low": 99, "Close": 100.5, "Volume": 0}
    # 10:30 UTC = 6:30 ET (EDT) -- within the 04:00-09:30 pre-market window.
    result = normalize_yfinance_bars([(utc(2026, 8, 17, 10, 30), row)], "AAPL", Timeframe.ONE_HOUR)

    assert len(result.candles) == 1
    assert result.candles[0].volume == 0
    assert result.candles[0].session == MarketSession.PRE_MARKET


def test_normalize_yfinance_empty_input_returns_empty_result():
    result = normalize_yfinance_bars([], "AAPL", Timeframe.ONE_HOUR)

    assert result.candles == []
    assert result.rejected == []
    assert result.duplicates_dropped == 0
