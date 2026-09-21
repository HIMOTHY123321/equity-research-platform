"""Massive (massive.com) REST implementation of MarketDataProvider -- the
historical/snapshot half of Phase 12.2's Massive integration. The push
streaming half lives in app.market_data.massive_streaming and is only used
by app.live.service when actually configured; this class alone is enough to
satisfy MARKET_DATA_PROVIDER=massive for every non-live route (chart
history, previous close, /forecasts, etc).

Massive's REST API is schema-compatible with the wider Polygon.io-family
convention (same `ev/sym/o/h/l/c/v/t` aggregate shape as its WebSocket
feeds -- see app.market_data.massive_streaming's module docstring); auth,
retries, pagination follow the same house style as
app.market_data.alpaca_provider so the two implementations stay easy to
compare.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx

from app.config import Settings, get_settings
from app.market_data.aggregation import aggregate_hourly_to_4h
from app.market_data.capabilities import MASSIVE_CAPABILITIES, ProviderCapabilities
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

# Massive has no native 4-hour aggregate; built from 1h bars, same approach
# app.market_data.alpaca_provider already uses.
_MASSIVE_TIMEFRAME = {
    Timeframe.FIVE_MIN: (5, "minute"),
    Timeframe.FIFTEEN_MIN: (15, "minute"),
    Timeframe.ONE_HOUR: (1, "hour"),
    Timeframe.ONE_DAY: (1, "day"),
}

DEFAULT_MAX_RETRIES = 3
MAX_PAGES = 10


class MassiveMarketDataProvider(MarketDataProvider):
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
            base_url=settings.massive_rest_base_url,
            headers={"Authorization": f"Bearer {settings.massive_api_key}"},
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    # ---- MarketDataProvider interface --------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return MASSIVE_CAPABILITIES

    def get_candles(self, symbol: str, timeframe: Timeframe, limit: int = 200) -> list[Candle]:
        if timeframe == Timeframe.FOUR_HOUR:
            hourly_limit = max(limit * 4, 50)
            hourly = self._fetch_bars(symbol, Timeframe.ONE_HOUR, hourly_limit)
            return aggregate_hourly_to_4h(hourly)[-limit:]
        return self._fetch_bars(symbol, timeframe, limit)

    def get_latest_quote(self, symbol: str) -> Quote:
        data = self._request("GET", f"/v3/quotes/{symbol}", params={"limit": 1, "order": "desc"})
        results = data.get("results") or []
        if not results:
            raise InvalidSymbolError(symbol)
        raw = results[0]
        timestamp = _ns_to_datetime(raw["sip_timestamp"])
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            session=classify_timestamp_session(timestamp),
            bid_price=raw["bid_price"],
            bid_size=raw.get("bid_size", 0),
            ask_price=raw["ask_price"],
            ask_size=raw.get("ask_size", 0),
        )

    def get_previous_close(self, symbol: str) -> PreviousClose:
        data = self._request("GET", f"/v2/aggs/ticker/{symbol}/prev")
        results = data.get("results") or []
        if not results:
            raise ProviderError(f"No previous-close aggregate available for {symbol}")
        raw = results[0]
        timestamp = _ms_to_datetime(raw["t"])
        return PreviousClose(
            symbol=symbol,
            trading_date=exchange_trading_date(timestamp),
            close=raw["c"],
            volume=raw.get("v", 0),
        )

    # ---- internals ----------------------------------------------------------

    def _fetch_bars(self, symbol: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        multiplier, span = _MASSIVE_TIMEFRAME.get(timeframe, (None, None))
        if multiplier is None:
            raise ValueError(f"Massive does not support fetching {timeframe.value} bars directly")

        to_date = exchange_trading_date(self._now())
        # A generous lookback window so `limit` bars are actually available
        # even for coarse timeframes/thin trading days -- never fabricated,
        # just a wide enough REST query range.
        from_date = to_date - timedelta(days=max(limit * 3, 30))

        raw_bars: list[dict] = []
        next_url: str | None = None
        for _ in range(MAX_PAGES):
            if next_url:
                data = self._request_url(next_url)
            else:
                data = self._request(
                    "GET",
                    f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{span}/{from_date}/{to_date}",
                    params={"sort": "asc", "limit": min(limit, 50_000)},
                )
            raw_bars.extend(data.get("results") or [])
            next_url = data.get("next_url")
            if not next_url or len(raw_bars) >= limit:
                break

        candles = _normalize_massive_bars(raw_bars, symbol, timeframe)
        return candles[-limit:]

    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        return self._send(lambda: self._client.request(method, path, params=params))

    def _request_url(self, url: str) -> dict:
        return self._send(lambda: self._client.request("GET", url))

    def _send(self, do_request: Callable[[], httpx.Response]) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = do_request()
            except httpx.TransportError as exc:
                if attempt > self._max_retries:
                    raise ProviderError(f"Network error calling Massive: {exc}") from exc
                self._sleep(_backoff_seconds(attempt))
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code in (401, 403):
                raise AuthenticationError(f"Massive rejected credentials ({response.status_code})")
            if response.status_code == 404:
                raise InvalidSymbolError(response.request.url.path)
            if response.status_code == 429:
                if attempt > self._max_retries:
                    raise RateLimitError(
                        "Massive rate limit exceeded", retry_after=_parse_retry_after(response)
                    )
                self._sleep(_parse_retry_after(response) or _backoff_seconds(attempt))
                continue
            if response.status_code >= 500:
                if attempt > self._max_retries:
                    raise ProviderError(f"Massive server error ({response.status_code})")
                self._sleep(_backoff_seconds(attempt))
                continue
            raise ProviderError(f"Unexpected Massive response ({response.status_code}): {response.text}")


def _normalize_massive_bars(raw_bars: list[dict], symbol: str, timeframe: Timeframe) -> list[Candle]:
    candles_by_timestamp: dict[datetime, Candle] = {}
    for raw in raw_bars:
        try:
            timestamp = _ms_to_datetime(raw["t"])
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                session=MarketSession.REGULAR
                if timeframe in (Timeframe.ONE_DAY, Timeframe.ONE_WEEK)
                else classify_timestamp_session(timestamp),
                open=raw["o"],
                high=raw["h"],
                low=raw["l"],
                close=raw["c"],
                volume=raw.get("v", 0),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("Rejected malformed Massive %s bar for %s", timeframe.value, symbol)
            continue
        candles_by_timestamp[candle.timestamp] = candle
    return sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)


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


def _ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _ns_to_datetime(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
