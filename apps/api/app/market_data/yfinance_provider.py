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
from typing import Any, Optional

import yfinance as yf
from yfinance.exceptions import YFException, YFRateLimitError

from app.market_data.aggregation import aggregate_hourly_to_4h
from app.market_data.capabilities import YFINANCE_CAPABILITIES, ProviderCapabilities
from app.market_data.exceptions import ProviderError, RateLimitError
from app.market_data.normalization import normalize_yfinance_bars
from app.market_data.provider import MarketDataProvider
from app.market_data.sessions import classify_timestamp_session, exchange_trading_date
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe

logger = logging.getLogger(__name__)

# Yahoo Finance's own hard limits on how far back each interval can be
# queried — not a choice we made. Empirically verified against real SPY
# data; see the ADR for the exact figures observed.
_YFINANCE_INTERVAL = {
    Timeframe.ONE_MIN: "1m",
    Timeframe.FIVE_MIN: "5m",
    Timeframe.FIFTEEN_MIN: "15m",
    Timeframe.ONE_HOUR: "1h",
    Timeframe.ONE_DAY: "1d",
}
_YFINANCE_MAX_PERIOD = {
    # Yahoo's real, documented, empirically-verified limit for 1m bars is 7
    # calendar days -- far shorter than 5m/15m's 60 days. This is a genuine
    # provider limitation, not a choice; requesting more silently returns
    # nothing extra from Yahoo's own API, so we never claim a longer window.
    Timeframe.ONE_MIN: "7d",
    Timeframe.FIVE_MIN: "60d",
    Timeframe.FIFTEEN_MIN: "60d",
    Timeframe.ONE_HOUR: "730d",
    # (MARKET EXPERIENCE COMPLETION PASS #6) "max" is a real yfinance period
    # value -- Yahoo returns every daily bar it has back to a symbol's own
    # listing date, never more. A fixed "10y" previously capped MAX+1d well
    # short of that (e.g. SPY has traded since 1993), silently pretending a
    # shorter history was the true limit when it was only our own request.
    Timeframe.ONE_DAY: "max",
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

    def capabilities(self) -> ProviderCapabilities:
        return YFINANCE_CAPABILITIES

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Candle]:
        if timeframe == Timeframe.FOUR_HOUR:
            # ~2 regular-session 4H bars per trading day; pad generously so
            # we have enough 1H history to produce `limit` complete 4H bars.
            # For a `before` page, the same padding is added on the FAR side
            # of the cursor (older direction) so the aggregation still has
            # enough raw 1H bars to build `limit` complete 4H bars ending
            # right at the cursor, not just near "now".
            hourly = self._fetch_bars(symbol, Timeframe.ONE_HOUR, limit * 4 + 50, before=before)
            return aggregate_hourly_to_4h(hourly)[-limit:]

        return self._fetch_bars(symbol, timeframe, limit, before=before)

    def get_latest_quote(self, symbol: str) -> Quote:
        """Hardening pass: `timestamp` used to be `self._now()` -- the
        moment *we polled*, not any real market event. That fabricated a
        quote that always looked "just now" fresh even when Yahoo's
        underlying data hadn't actually moved in minutes (the "LIVE <1s
        ago" bug, and the reason a genuinely-new forming candle bucket
        never appeared: LiveMarketService's dedup-on-timestamp had nothing
        to dedup against). `price` and `timestamp` now both come from the
        same real, most-recent intraday bar Yahoo has actually published --
        an honest, internally-consistent pair. This trades update
        granularity (at best every 5 minutes, matching Yahoo's own free
        intraday resolution) for truthfulness, which is the point."""
        bar = self._latest_intraday_bar(symbol)
        return Quote(
            symbol=symbol,
            timestamp=bar.timestamp,
            session=classify_timestamp_session(bar.timestamp),
            bid_price=bar.close,
            bid_size=0.0,
            ask_price=bar.close,
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

    def _fetch_bars(
        self, symbol: str, timeframe: Timeframe, limit: int, before: Optional[datetime] = None
    ) -> list[Candle]:
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

        candles = result.candles
        if before is not None:
            # (#1 pagination) Strictly `< before` -- the boundary candle
            # already shown to the caller is never duplicated in the next
            # page. This still fetches the SAME real provider window
            # `_YFINANCE_MAX_PERIOD` already caps (never more than Yahoo
            # actually has), so a page that comes back shorter than
            # `limit` is genuine exhaustion of that interval's real
            # history, not an artifact of this request's own size.
            candles = [c for c in candles if c.timestamp < before]

        return candles[-limit:]

    def _latest_intraday_bar(self, symbol: str) -> Candle:
        """The real, most-recently-published 5-minute bar -- a light
        `period="1d"` fetch (today's session only, ~78 rows at most), never
        the heavy 60-day history `_fetch_bars` requests for chart data.
        Raises ProviderError if Yahoo has published nothing for today yet
        (e.g. immediately after market open, or a fully closed session) --
        callers must not fabricate a bar to fill that gap."""
        df = self._history(symbol, period="1d", interval="5m")
        rows = ((ts.to_pydatetime(), row) for ts, row in df.iterrows())
        result = normalize_yfinance_bars(rows, symbol, Timeframe.FIVE_MIN)
        for rejected in result.rejected:
            logger.warning("Rejected malformed live 5m bar for %s: %s", symbol, rejected.reason)
        if not result.candles:
            raise ProviderError(f"No intraday bar available yet for {symbol}")
        return result.candles[-1]

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

def _backoff_seconds(attempt: int) -> float:
    return min(2 ** (attempt - 1) * 0.5, 4.0)
