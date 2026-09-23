"""Alpaca implementation of MarketDataProvider.

Auth, retries, pagination, and rate-limit handling live here; everything
above this module only ever talks to the MarketDataProvider interface. An
httpx.Client can be injected (e.g. with a MockTransport) so this class is
fully testable without live credentials or network access.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from app.config import Settings, get_settings
from app.market_data.aggregation import aggregate_hourly_to_4h
from app.market_data.capabilities import ALPACA_CAPABILITIES, ProviderCapabilities
from app.market_data.exceptions import (
    AuthenticationError,
    InvalidSymbolError,
    ProviderError,
    RateLimitError,
)
from app.market_data.normalization import normalize_alpaca_bars
from app.market_data.provider import MarketDataProvider
from app.market_data.sessions import classify_timestamp_session, exchange_trading_date
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe

logger = logging.getLogger(__name__)

# Alpaca has no native 4-hour timeframe; we build it from 1h bars ourselves.
_ALPACA_TIMEFRAME = {
    Timeframe.FIVE_MIN: "5Min",
    Timeframe.FIFTEEN_MIN: "15Min",
    Timeframe.ONE_HOUR: "1Hour",
    Timeframe.ONE_DAY: "1Day",
}

DEFAULT_MAX_RETRIES = 3
MAX_PAGES = 10


class AlpacaMarketDataProvider(MarketDataProvider):
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
            base_url=settings.alpaca_data_base_url,
            headers={
                "APCA-API-KEY-ID": settings.alpaca_api_key_id,
                "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
            },
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    # ---- MarketDataProvider interface --------------------------------------

    def capabilities(self) -> ProviderCapabilities:
        return ALPACA_CAPABILITIES

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Candle]:
        if timeframe == Timeframe.FOUR_HOUR:
            # ~2 regular-session 4H bars per trading day; pad generously so we
            # have enough 1H history to produce `limit` complete 4H bars.
            hourly_limit = max(limit * 4, 50)
            hourly = self._fetch_bars(symbol, Timeframe.ONE_HOUR, hourly_limit, before=before)
            return aggregate_hourly_to_4h(hourly)[-limit:]

        return self._fetch_bars(symbol, timeframe, limit, before=before)

    def get_latest_quote(self, symbol: str) -> Quote:
        data = self._request("GET", f"/v2/stocks/{symbol}/quotes/latest")
        quote = data.get("quote")
        if not quote:
            raise InvalidSymbolError(symbol)
        timestamp = _parse_timestamp(quote["t"])
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            session=classify_timestamp_session(timestamp),
            bid_price=quote["bp"],
            bid_size=quote["bs"],
            ask_price=quote["ap"],
            ask_size=quote["as"],
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
        alpaca_timeframe = _ALPACA_TIMEFRAME.get(timeframe)
        if alpaca_timeframe is None:
            raise ValueError(f"Alpaca does not support fetching {timeframe.value} bars directly")

        raw_bars: list[dict] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict = {
                "timeframe": alpaca_timeframe,
                "limit": min(limit, 10_000),
                "adjustment": "raw",
                "feed": "iex",
            }
            if before is not None:
                # Alpaca's own real "end" cursor -- an actual older-page
                # request, not a post-fetch filter over the recent window.
                params["end"] = before.isoformat().replace("+00:00", "Z")
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", f"/v2/stocks/{symbol}/bars", params=params)
            raw_bars.extend(data.get("bars") or [])
            page_token = data.get("next_page_token")
            if not page_token or len(raw_bars) >= limit:
                break

        result = normalize_alpaca_bars(raw_bars, symbol, timeframe)
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
            # Alpaca's own `end` param is documented as inclusive -- this
            # strict client-side filter is what actually guarantees the
            # boundary candle is never duplicated, same contract as
            # yfinance_provider/massive_provider.
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(method, path, params=params)
            except httpx.TransportError as exc:
                if attempt > self._max_retries:
                    raise ProviderError(f"Network error calling Alpaca: {exc}") from exc
                self._sleep(_backoff_seconds(attempt))
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code in (401, 403):
                raise AuthenticationError(f"Alpaca rejected credentials ({response.status_code})")

            if response.status_code == 404:
                raise InvalidSymbolError(path)

            if response.status_code == 429:
                if attempt > self._max_retries:
                    raise RateLimitError(
                        "Alpaca rate limit exceeded", retry_after=_parse_retry_after(response)
                    )
                self._sleep(_parse_retry_after(response) or _backoff_seconds(attempt))
                continue

            if response.status_code >= 500:
                if attempt > self._max_retries:
                    raise ProviderError(f"Alpaca server error ({response.status_code})")
                self._sleep(_backoff_seconds(attempt))
                continue

            raise ProviderError(f"Unexpected Alpaca response ({response.status_code}): {response.text}")


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


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
