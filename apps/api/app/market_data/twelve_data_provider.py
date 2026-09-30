"""Twelve Data (twelvedata.com) REST implementation of MarketDataProvider
(Phase 19.1) -- the historical/quote half of the integration; the push
streaming half lives in app.market_data.twelve_data_streaming and is only
used by app.live.service when actually configured.

Auth: `Authorization: apikey <key>` header, per Twelve Data's documented
alternative to the `?apikey=` query parameter -- preferred here because a
query-string credential is far more likely to end up in a proxy/access log
than a header ever is. The key is never logged, never included in an
exception message, and never sent to the browser.

Rate-limit reality (Basic/free plan, as of Twelve Data's own published
limits): a small number of REST credits per minute and per day. This
provider does not attempt to outsmart that budget beyond honest,
provider-capabilities-driven throttling (see TWELVE_DATA_CAPABILITIES'
min_poll_interval_seconds) and the existing generic response cache every
MarketDataProvider already gets for free via
app.market_data.cached_provider.CachedMarketDataProvider -- so 25 users
requesting NVDA within the same TTL window still make one real Twelve Data
request, the same guarantee every other provider already has, not something
reimplemented per-provider.

Known, documented limitations (not silently hidden):
- No real bid/ask anywhere in Twelve Data's REST surface -- `get_latest_quote`
  returns the last close price as both bid and ask, `is_approximate=True`,
  the exact same honest degradation app.market_data.yfinance_provider
  already uses for the identical reason.
- No native 4-hour interval; built from 1h bars via aggregate_hourly_to_4h,
  the same approach every other multi-provider implementation in this
  codebase uses.
- `get_previous_close` reads the same daily time-series `/time_series`
  endpoint every other provider's previous-close logic already reads
  (filtered to the last COMPLETED trading day), never Twelve Data's own
  `/quote` "previous_close" field, whose exact boundary semantics around
  extended hours are not documented precisely enough to trust blindly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import Settings, get_settings
from app.market_data.aggregation import aggregate_hourly_to_4h
from app.market_data.capabilities import TWELVE_DATA_CAPABILITIES, ProviderCapabilities
from app.market_data.exceptions import (
    AuthenticationError,
    InvalidSymbolError,
    ProviderError,
    RateLimitError,
)
from app.market_data.provider import MarketDataProvider
from app.market_data.sessions import classify_timestamp_session, exchange_trading_date
from app.schemas.market_data import Candle, MarketSession, PreviousClose, Quote, Timeframe

logger = logging.getLogger(__name__)

_TWELVE_DATA_INTERVAL = {
    Timeframe.ONE_MIN: "1min",
    Timeframe.FIVE_MIN: "5min",
    Timeframe.FIFTEEN_MIN: "15min",
    Timeframe.ONE_HOUR: "1h",
    Timeframe.ONE_DAY: "1day",
}

# Twelve Data's own documented ceiling on a single /time_series response.
_MAX_OUTPUTSIZE = 5000
DEFAULT_MAX_RETRIES = 2


class TwelveDataMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        client: httpx.Client | None = None,
        settings: Settings | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        settings = settings or get_settings()
        self._sleep = sleep_fn
        self._now = now_fn
        self._max_retries = max_retries
        self._client = client or httpx.Client(
            base_url=settings.twelve_data_rest_base_url,
            headers={"Authorization": f"apikey {settings.twelve_data_api_key}"},
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    # ---- MarketDataProvider interface --------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return TWELVE_DATA_CAPABILITIES

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Candle]:
        if timeframe == Timeframe.FOUR_HOUR:
            hourly_limit = max(limit * 4, 50)
            hourly = self._fetch_bars(symbol, Timeframe.ONE_HOUR, hourly_limit, before=before)
            return aggregate_hourly_to_4h(hourly)[-limit:]
        return self._fetch_bars(symbol, timeframe, limit, before=before)

    def get_latest_quote(self, symbol: str) -> Quote:
        data = self._request("GET", "/quote", params={"symbol": symbol})
        if not data.get("close"):
            raise InvalidSymbolError(symbol)
        timestamp = _epoch_to_datetime(data.get("timestamp"))
        close = float(data["close"])
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            session=classify_timestamp_session(timestamp),
            bid_price=close,
            bid_size=0.0,
            ask_price=close,
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
        interval = _TWELVE_DATA_INTERVAL.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Twelve Data provider does not support fetching {timeframe.value} bars directly"
            )

        params = {
            "symbol": symbol,
            "interval": interval,
            # A little padding beyond `limit` so an exact-limit page still
            # has room for the client-side `before` filter below to drop
            # the boundary candle without starving the page.
            "outputsize": min(limit + 50, _MAX_OUTPUTSIZE),
            "order": "ASC",
            "timezone": "UTC",
        }
        data = self._request("GET", "/time_series", params=params)
        candles = _normalize_twelve_data_bars(data.get("values") or [], symbol, timeframe)

        if before is not None:
            # Strictly `< before` -- the boundary candle already shown to
            # the caller is never duplicated in the next page, same
            # contract as every other provider's pagination.
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

    def _request(self, method: str, path: str, params: dict) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(method, path, params=params)
            except httpx.TransportError as exc:
                if attempt > self._max_retries:
                    raise ProviderError(f"Network error calling Twelve Data: {exc}") from exc
                self._sleep(_backoff_seconds(attempt))
                continue

            if response.status_code in (401, 403):
                raise AuthenticationError(f"Twelve Data rejected credentials ({response.status_code})")
            if response.status_code == 404:
                raise InvalidSymbolError(params.get("symbol", "?"))
            if response.status_code == 429:
                if attempt > self._max_retries:
                    raise RateLimitError(
                        "Twelve Data rate limit exceeded", retry_after=_parse_retry_after(response)
                    )
                self._sleep(_parse_retry_after(response) or _backoff_seconds(attempt))
                continue
            if response.status_code >= 500:
                if attempt > self._max_retries:
                    raise ProviderError(f"Twelve Data server error ({response.status_code})")
                self._sleep(_backoff_seconds(attempt))
                continue
            if response.status_code != 200:
                raise ProviderError(
                    f"Unexpected Twelve Data response ({response.status_code}): {response.text}"
                )

            body = response.json()
            # (§V) Twelve Data has historically returned HTTP 200 with an
            # embedded error body for some failure modes -- checked here so
            # a caller never silently treats an error payload as real data.
            if isinstance(body, dict) and body.get("status") == "error":
                code = body.get("code")
                message = str(body.get("message", "Twelve Data error"))
                if code in (401, 403):
                    raise AuthenticationError(f"Twelve Data rejected credentials: {message}")
                if code == 429:
                    if attempt > self._max_retries:
                        raise RateLimitError(f"Twelve Data rate limit exceeded: {message}")
                    self._sleep(_backoff_seconds(attempt))
                    continue
                if code in (400, 404):
                    raise InvalidSymbolError(params.get("symbol", "?"))
                raise ProviderError(f"Twelve Data error ({code}): {message}")
            return body


def _normalize_twelve_data_bars(raw_values: list[dict], symbol: str, timeframe: Timeframe) -> list[Candle]:
    candles_by_timestamp: dict[datetime, Candle] = {}
    for raw in raw_values:
        try:
            timestamp = _parse_utc_naive(raw["datetime"])
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                session=MarketSession.REGULAR
                if timeframe == Timeframe.ONE_DAY
                else classify_timestamp_session(timestamp),
                open=float(raw["open"]),
                high=float(raw["high"]),
                low=float(raw["low"]),
                close=float(raw["close"]),
                # Twelve Data omits volume for some instruments (indices,
                # forex) -- 0.0 is real, honestly-absent data, not a bug,
                # the same convention yfinance_provider's extended-hours
                # bars already use.
                volume=float(raw.get("volume") or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("Rejected malformed Twelve Data %s bar for %s", timeframe.value, symbol)
            continue
        candles_by_timestamp[candle.timestamp] = candle
    return sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)


def _parse_utc_naive(raw: str) -> datetime:
    """`timezone=UTC` was requested, so Twelve Data's `datetime` string is
    already UTC wall-clock time with no offset suffix -- attach tzinfo
    rather than trust any implicit local-time assumption."""
    fmt = "%Y-%m-%d %H:%M:%S" if " " in raw else "%Y-%m-%d"
    return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)


def _epoch_to_datetime(value) -> datetime:
    if value is None:
        raise ProviderError("Twelve Data quote response is missing a timestamp")
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _backoff_seconds(attempt: int) -> float:
    return min(2 ** (attempt - 1) * 0.5, 8.0)


def _parse_retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None
