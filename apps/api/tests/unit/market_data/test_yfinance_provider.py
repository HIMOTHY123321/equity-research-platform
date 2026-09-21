import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from app.market_data.exceptions import ProviderError, RateLimitError
from app.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.schemas.market_data import Timeframe
from tests.conftest import utc


def _df(rows):
    """rows: list of (timestamp, open, high, low, close, volume)."""
    index = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


BAR_ROW = (utc(2026, 8, 17, 14, 30), 100, 101, 99, 100.5, 1000)


class FakeTicker:
    def __init__(self, history_df=None, fast_info=None, raise_on_history=None, raise_on_fast_info=None):
        self._history_df = history_df
        self._fast_info = fast_info if fast_info is not None else {"last_price": 100.5}
        self._raise_on_history = raise_on_history
        self._raise_on_fast_info = raise_on_fast_info

    def history(self, **kwargs):
        if self._raise_on_history is not None:
            raise self._raise_on_history
        return self._history_df

    @property
    def fast_info(self):
        if self._raise_on_fast_info is not None:
            raise self._raise_on_fast_info
        return self._fast_info


def _provider(ticker, sleep_fn=None, max_retries=2, now_fn=None):
    kwargs = {
        "ticker_factory": lambda symbol: ticker,
        "sleep_fn": sleep_fn or (lambda _: None),
        "max_retries": max_retries,
    }
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return YFinanceMarketDataProvider(**kwargs)


def test_get_candles_normalizes_response():
    ticker = FakeTicker(history_df=_df([BAR_ROW]))
    provider = _provider(ticker)

    candles = provider.get_candles("SPY", Timeframe.ONE_DAY, limit=10)

    assert len(candles) == 1
    assert candles[0].close == pytest.approx(100.5)
    assert candles[0].symbol == "SPY"


def test_get_candles_trims_to_limit():
    rows = [
        (utc(2026, 8, 17, h, 30), 100 + h, 101 + h, 99 + h, 100.5 + h, 1000) for h in range(10)
    ]
    ticker = FakeTicker(history_df=_df(rows))
    provider = _provider(ticker)

    candles = provider.get_candles("SPY", Timeframe.ONE_HOUR, limit=3)

    assert len(candles) == 3
    assert candles[-1].timestamp == rows[-1][0]


def test_get_candles_4h_aggregates_from_hourly():
    hourly_rows = [
        (utc(2026, 8, 17, h, 30), 100, 101, 99, 100.5, 1000) for h in range(13, 20)
    ]
    ticker = FakeTicker(history_df=_df(hourly_rows))
    provider = _provider(ticker)

    candles = provider.get_candles("SPY", Timeframe.FOUR_HOUR, limit=10)

    assert all(c.timeframe == Timeframe.FOUR_HOUR for c in candles)
    assert len(candles) == 2


def test_empty_response_returns_empty_list_without_fabricating():
    ticker = FakeTicker(history_df=_df([]))
    provider = _provider(ticker)

    candles = provider.get_candles("ZZZZINVALID", Timeframe.ONE_DAY)
    assert candles == []


def test_get_latest_quote_uses_the_real_latest_bars_price_and_timestamp():
    # Hardening pass: get_latest_quote no longer fabricates `timestamp` as
    # "now" -- both price and timestamp come from the same real bar, so a
    # caller can never see a price that doesn't match its claimed time.
    bars = [BAR_ROW, (utc(2026, 8, 17, 14, 35), 100.5, 102, 100, 101.25, 900)]
    ticker = FakeTicker(history_df=_df(bars))
    provider = _provider(ticker)

    quote = provider.get_latest_quote("SPY")

    assert quote.bid_price == pytest.approx(101.25)
    assert quote.ask_price == pytest.approx(101.25)
    assert quote.timestamp == bars[-1][0]
    assert quote.is_approximate is True


def test_get_latest_quote_raises_provider_error_when_nothing_published_yet():
    ticker = FakeTicker(history_df=_df([]))
    provider = _provider(ticker)

    with pytest.raises(ProviderError):
        provider.get_latest_quote("ZZZZINVALID")


def test_get_latest_quote_propagates_provider_error_after_retries_exhausted():
    ticker = FakeTicker(raise_on_history=ConnectionError("network down"))
    provider = _provider(ticker, max_retries=0)

    with pytest.raises(ProviderError):
        provider.get_latest_quote("ZZZZINVALID")


def test_repeated_polls_against_unchanged_yahoo_data_never_fabricate_a_newer_timestamp():
    # Hardening pass regression: two polls against a data source that
    # genuinely hasn't advanced must return the exact same timestamp -- the
    # old self._now()-based implementation would have returned a "newer"
    # timestamp on every single call regardless of whether Yahoo's
    # underlying bar had actually changed.
    ticker = FakeTicker(history_df=_df([BAR_ROW]))
    provider = _provider(ticker)

    first = provider.get_latest_quote("SPY")
    second = provider.get_latest_quote("SPY")

    assert first.timestamp == second.timestamp == BAR_ROW[0]


def test_get_previous_close_skips_todays_incomplete_bar():
    daily_rows = [
        (utc(2026, 8, 13, 4, 0), 98, 99, 97, 98.0, 1000),
        (utc(2026, 8, 14, 4, 0), 99, 100, 98, 99.0, 1000),
        (utc(2026, 8, 17, 4, 0), 105, 106, 104, 105.0, 1000),  # today, still forming
    ]
    ticker = FakeTicker(history_df=_df(daily_rows))
    provider = _provider(ticker, now_fn=lambda: utc(2026, 8, 17, 18, 0))

    previous_close = provider.get_previous_close("SPY")

    assert previous_close.close == pytest.approx(99.0)


def test_rate_limit_retries_then_succeeds():
    calls = []
    sleeps = []

    class FlakyTicker(FakeTicker):
        def history(self, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise YFRateLimitError()
            return _df([BAR_ROW])

    provider = _provider(FlakyTicker(), sleep_fn=sleeps.append)
    candles = provider.get_candles("SPY", Timeframe.ONE_DAY)

    assert len(calls) == 3
    assert len(sleeps) == 2
    assert len(candles) == 1


def test_rate_limit_raises_after_exhausting_retries():
    ticker = FakeTicker(raise_on_history=YFRateLimitError())
    provider = _provider(ticker, max_retries=1)

    with pytest.raises(RateLimitError):
        provider.get_candles("SPY", Timeframe.ONE_DAY)


def test_generic_error_retries_then_raises_provider_error():
    calls = []

    class BrokenTicker(FakeTicker):
        def history(self, **kwargs):
            calls.append(1)
            raise ConnectionError("network down")

    provider = _provider(BrokenTicker(), max_retries=2)

    with pytest.raises(ProviderError):
        provider.get_candles("SPY", Timeframe.ONE_DAY)

    assert len(calls) == 3  # initial attempt + 2 retries


def test_extended_hours_zero_volume_is_preserved_not_fabricated():
    row = (utc(2026, 8, 17, 8, 0), 100, 101, 99, 100.5, 0)  # premarket, real zero volume
    ticker = FakeTicker(history_df=_df([row]))
    provider = _provider(ticker)

    candles = provider.get_candles("SPY", Timeframe.ONE_HOUR)

    assert len(candles) == 1
    assert candles[0].volume == 0
