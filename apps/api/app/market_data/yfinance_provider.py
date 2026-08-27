"""yfinance implementation of MarketDataProvider — a research/development
data source only, not an institutional-grade feed. No API key required.
Selected via `MARKET_DATA_PROVIDER` config, never hard-coded as the only
option (see app/api/deps.py) — kept fully isolated from alpaca_provider.py
so an eligible account holder can switch back to Alpaca, or to another
licensed provider, by implementing MarketDataProvider and changing one
config value. See docs/decisions/0006-yfinance-development-provider.md for
the full rationale and the real Yahoo Finance history-window limits this
was built and tested against.

Known, documented limitations (not silently hidden):
- No real bid/ask. `get_latest_quote` returns the last trade price as both
  bid and ask, with `is_approximate=True` set explicitly.
- Extended-hours bars report volume=0 — Yahoo's free intraday feed simply
  doesn't populate pre/post-market volume. This is real data, not a bug;
  `Candle.volume` allows 0, and downstream consumers see honestly-zero
  extended-hours volume rather than a fabricated number.
- Intraday history is capped by Yahoo, not us: 5m/15m ~60 calendar days,
  1h ~730 days, 1d effectively unlimited. `get_candles` always requests
  the real maximum for the timeframe, then trims to `limit`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import yfinance as yf
from yfinance.exceptions import YFException, YFRateLimitError

from app.market_data.aggregation import aggregate_hourly_to_4h
from app.market_data.exceptions import InvalidSymbolError, ProviderError, RateLimitError
from app.market_data.normalization import normalize_yfinance_bars
from app.market_data.provider import MarketDataProvider
from app.market_data.sessions import classify_timestamp_session, exchange_trading_date
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe

logger = logging.getLogger(__name__)

# Yahoo Finance's own hard limits on how far back each interval can be
# queried — not a choice we made. Empirically verified against real SPY
# data; see the ADR for the exact figures observed.
_YFINANCE_INTERVAL = {
    Timeframe.FIVE_MIN: "5m",
    Timeframe.FIFTEEN_MIN: "15m",
    Timeframe.ONE_HOUR: "1h",
    Timeframe.ONE_DAY: "1d",
}
_YFINANCE_MAX_PERIOD = {
    Timeframe.FIVE_MIN: "60d",
    Timeframe.FIFTEEN_MIN: "60d",
    Timeframe.ONE_HOUR: "730d",
    Timeframe.ONE_DAY: "10y",
}

DEFAULT_MAX_RETRIES = 2


class YFinanceMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        ticker_factory: Callable[[str], Any] = yf.Ticker,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._ticker_factory = ticker_factory
        self._sleep = sleep_fn
        self._now = now_fn
        self._max_retries = max_retries

    # ---- MarketDataProvider interface --------------------------------------

    def get_candles(self, symbol: str, timeframe: Timeframe, limit: int = 200) -> list[Candle]:
        if timeframe == Timeframe.FOUR_HOUR:
            # ~2 regular-session 4H bars per trading day; pad generously so
            # we have enough 1H history to produce `limit` complete 4H bars.
            hourly = self._fetch_bars(symbol, Timeframe.ONE_HOUR, limit * 4 + 50)
            return aggregate_hourly_to_4h(hourly)[-limit:]

        return self._fetch_bars(symbol, timeframe, limit)

    def get_latest_quote(self, symbol: str) -> Quote:
        price = self._fast_info_price(symbol)
        timestamp = self._now()
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            session=classify_timestamp_session(timestamp),
            bid_price=price,
            bid_size=0.0,
            ask_price=price,
            ask_size=0.0,
            is_approximate=True,
        )

    def get_previous_close(self, symbol: str) -> PreviousClose:
        daily = self._fetch_bars(symbol, Timeframe.ONE_DAY, limit=10)
        today = exchange_trading_date(self._now())
        completed = [c for c in daily if exchange_trading_date(c.timestamp) < today]
        if not completed:
            raise ProviderError(f"No completed daily bar available for {symbol}")
        last = completed[-1]
        return PreviousClose(
            symbol=symbol,
            trading_date=exchange_trading_date(last.timestamp),
            close=last.close,
            volume=last.volume,
        )

    # ---- internals ----------------------------------------------------------

    def _fetch_bars(self, symbol: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        interval = _YFINANCE_INTERVAL.get(timeframe)
        if interval is None:
            raise ValueError(f"yfinance provider does not support fetching {timeframe.value} bars directly")
        period = _YFINANCE_MAX_PERIOD[timeframe]

        df = self._history(symbol, period=period, interval=interval)
        rows = ((ts.to_pydatetime(), row) for ts, row in df.iterrows())
        result = normalize_yfinance_bars(rows, symbol, timeframe)

        for rejected in result.rejected:
            logger.warning(
                "Rejected malformed %s bar for %s: %s", timeframe.value, symbol, rejected.reason
            )
        if result.duplicates_dropped:
            logger.warning(
                "Dropped %d duplicate %s bar(s) for %s",
                result.duplicates_dropped,
                timeframe.value,
                symbol,
            )

        return result.candles[-limit:]

    def _history(self, symbol: str, period: str, interval: str):
        attempt = 0
        while True:
            attempt += 1
            try:
                ticker = self._ticker_factory(symbol)
                return ticker.history(period=period, interval=interval, auto_adjust=False, prepost=True)
            except YFRateLimitError as exc:
                if attempt > self._max_retries:
                    raise RateLimitError(f"yfinance rate limited fetching {symbol}") from exc
                self._sleep(_backoff_seconds(attempt))
            except YFException as exc:
                if attempt > self._max_retries:
                    raise ProviderError(f"yfinance error fetching {symbol}: {exc}") from exc
                self._sleep(_backoff_seconds(attempt))
            except Exception as exc:  # network hiccups etc. -- yfinance doesn't expose a narrower type
                if attempt > self._max_retries:
                    raise ProviderError(f"Unexpected error fetching {symbol} from yfinance: {exc}") from exc
                self._sleep(_backoff_seconds(attempt))

    def _fast_info_price(self, symbol: str) -> float:
        attempt = 0
        while True:
            attempt += 1
            try:
                ticker = self._ticker_factory(symbol)
                price = ticker.fast_info["last_price"]
                if price is None:
                    raise InvalidSymbolError(symbol)
                return price
            except InvalidSymbolError:
                raise
            except YFRateLimitError as exc:
                if attempt > self._max_retries:
                    raise RateLimitError(f"yfinance rate limited fetching quote for {symbol}") from exc
                self._sleep(_backoff_seconds(attempt))
            except Exception as exc:
                if attempt > self._max_retries:
                    raise InvalidSymbolError(symbol) from exc
                self._sleep(_backoff_seconds(attempt))


def _backoff_seconds(attempt: int) -> float:
    return min(2 ** (attempt - 1) * 0.5, 4.0)
