"""Twelve Data (twelvedata.com) push-streaming implementation of
StreamingMarketDataProvider (Phase 19.1).

Wire protocol (per Twelve Data's documented `/v1/quotes/price` WebSocket):
  - Connect: wss://ws.twelvedata.com/v1/quotes/price?apikey=<API_KEY> -- auth
    is via the URL itself (Twelve Data offers no header-based WS auth), so
    the full connect URL is built and used ONLY inside `connect()` and is
    never logged, never included in an exception message, and never
    otherwise leaves this process.
  - Subscribe: {"action":"subscribe","params":{"symbols":"AAPL,NVDA"}} --
    ONE connection subscribes to many tickers. Unsubscribe mirrors this.
  - Events arrive as single JSON objects (not an array, unlike Massive),
    each carrying an `event` discriminator: "price" (a live tick),
    "subscribe-status" (which requested symbols were actually accepted vs
    rejected -- see below), "heartbeat", or an error shape.

CRITICAL (Phase 19.1 §5): a successful WebSocket connection alone proves
NOTHING about which symbols are genuinely streamable on a Basic/free plan.
This module tracks `subscribed_symbols`/`rejected_symbols` from the
`subscribe-status` acknowledgement Twelve Data itself sends back, and
exposes that as `entitlement_hint()` -- LiveMarketService reads this to
upgrade/downgrade its stored MarketDataEntitlement from evidence, never
from a configured flag. `real_time_available()` can only become True once
this module has genuine proof a symbol's subscription succeeded AND fresh
"price" events are actually arriving for it.

The `/v1/quotes/price` feed carries price only -- no bid/ask, no
pre-aggregated OHLCV bar. Every "price" tick maps to a StreamTrade with
`size=0.0` (never a fabricated size); LiveMarketService's existing
ingest_trade path already leaves bid/ask/spread at the last-known value (or
the trade price itself on the very first tick, spread=0.0) rather than
inventing an NBBO -- the same honest degradation any trade-only stream
already gets, not something special-cased here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Optional

from app.live.entitlement import EntitlementStatus, MarketDataEntitlement
from app.live.streaming import (
    CHANNEL_TRADES,
    StreamEvent,
    StreamingMarketDataProvider,
    StreamStatus,
    StreamTrade,
)
from app.market_data.capabilities import TWELVE_DATA_CAPABILITIES, ProviderCapabilities
from app.market_data.exceptions import AuthenticationError, RateLimitError

logger = logging.getLogger(__name__)

# (§V) Untrusted external input is bounded, never trusted at arbitrary size.
_MAX_MESSAGE_BYTES = 1_000_000

DEFAULT_TWELVE_DATA_WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"


class TwelveDataStreamingProvider(StreamingMarketDataProvider):
    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_TWELVE_DATA_WS_URL,
        ws_connect: Callable | None = None,
    ) -> None:
        self._api_key = api_key
        self._url = url
        if ws_connect is None:
            import websockets

            ws_connect = websockets.connect
        self._ws_connect = ws_connect
        self._ws = None
        self._subscriptions: dict[str, set[str]] = {}
        # Phase 19.1 (§5): populated ONLY from genuine subscribe-status
        # acknowledgements -- never assumed, never operator-set.
        self.subscribed_symbols: set[str] = set()
        self.rejected_symbols: set[str] = set()
        self._rate_limited = False
        self._auth_failed = False
        self.last_event_at: Optional[datetime] = None

    def capabilities(self) -> ProviderCapabilities:
        return TWELVE_DATA_CAPABILITIES

    async def connect(self) -> None:
        # The API key is only ever embedded in this one URL, built and used
        # here and nowhere else -- never logged, never in an exception
        # message (any error from the underlying library is caught and
        # re-raised as a clean, key-free message below).
        connect_url = f"{self._url}?apikey={self._api_key}"
        try:
            self._ws = await self._ws_connect(connect_url)
        except Exception as exc:
            # A WS handshake rejection (401/403-shaped close) is the
            # closest thing Twelve Data has to an explicit auth failure;
            # treated the same way Massive's explicit auth_success check
            # is -- never silently "connected".
            self._auth_failed = True
            raise AuthenticationError("Twelve Data WebSocket authentication failed") from exc
        self._auth_failed = False

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def subscribe(self, symbol: str, channels: frozenset) -> None:
        if CHANNEL_TRADES not in channels:
            return
        self._subscriptions.setdefault(symbol, set()).add(CHANNEL_TRADES)
        if self._ws is not None:
            await self._ws.send(json.dumps({"action": "subscribe", "params": {"symbols": symbol}}))

    async def unsubscribe(self, symbol: str, channels: frozenset) -> None:
        self._subscriptions.pop(symbol, None)
        self.subscribed_symbols.discard(symbol)
        self.rejected_symbols.discard(symbol)
        if self._ws is not None:
            await self._ws.send(json.dumps({"action": "unsubscribe", "params": {"symbols": symbol}}))

    async def events(self) -> AsyncIterator[StreamEvent]:
        if self._ws is None:
            raise RuntimeError("TwelveDataStreamingProvider.events() called before connect()")
        async for raw in self._ws:
            if isinstance(raw, (bytes, bytearray)) and len(raw) > _MAX_MESSAGE_BYTES:
                logger.warning("Dropped oversized Twelve Data message (%d bytes)", len(raw))
                continue
            if isinstance(raw, str) and len(raw.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                logger.warning("Dropped oversized Twelve Data message (%d bytes)", len(raw))
                continue
            try:
                message = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Dropped malformed Twelve Data message: invalid JSON")
                continue
            if not isinstance(message, dict):
                logger.warning("Dropped malformed Twelve Data message: unexpected top-level shape")
                continue

            event = self._handle_message(message)
            if event is not None:
                yield event

    def _handle_message(self, message: dict) -> StreamEvent | None:
        """(§V) Untrusted external input: every required field is validated
        before use; a malformed event is dropped and logged, never allowed
        to crash the stream. Also the ONLY place `subscribed_symbols`/
        `rejected_symbols`/`_rate_limited` are ever mutated -- see
        entitlement_hint()."""
        event_type = message.get("event")

        if event_type == "heartbeat":
            return None

        if event_type == "subscribe-status":
            for entry in message.get("success") or []:
                symbol = entry.get("symbol") if isinstance(entry, dict) else None
                if symbol:
                    self.subscribed_symbols.add(symbol)
                    self.rejected_symbols.discard(symbol)
            for entry in message.get("fails") or []:
                symbol = entry.get("symbol") if isinstance(entry, dict) else None
                if symbol:
                    self.rejected_symbols.add(symbol)
                    self.subscribed_symbols.discard(symbol)
            return StreamStatus(connected=True, message="subscribe-status")

        if event_type == "price":
            try:
                symbol = message["symbol"]
                price = float(message["price"])
                source_timestamp = _epoch_to_datetime(message["timestamp"])
            except (KeyError, TypeError, ValueError):
                logger.warning("Dropped malformed Twelve Data price message: missing/invalid fields")
                return None
            self.last_event_at = source_timestamp
            # A price tick for a symbol is itself genuine, positive proof
            # that symbol's subscription is live -- upgrades it even if a
            # subscribe-status message was somehow missed.
            self.subscribed_symbols.add(symbol)
            self.rejected_symbols.discard(symbol)
            return StreamTrade(
                symbol=symbol,
                price=price,
                size=0.0,
                exchange=None,
                conditions=(),
                source_timestamp=source_timestamp,
                sequence=None,
            )

        status = message.get("status")
        code = message.get("code")
        if status == "error" or event_type == "error":
            message_text = str(message.get("message", "Twelve Data error"))
            if code in (401, 403):
                self._auth_failed = True
                raise AuthenticationError(f"Twelve Data WebSocket rejected credentials: {message_text}")
            if code == 429:
                self._rate_limited = True
                raise RateLimitError(f"Twelve Data WebSocket rate limit exceeded: {message_text}")
            logger.warning("Twelve Data WebSocket reported an error: %s", message_text)
            return None

        # Unrecognized event type (a future addition to Twelve Data's wire
        # protocol) -- ignored, never forwarded, never crashes the stream.
        return None

    def entitlement_hint(self) -> Optional[MarketDataEntitlement]:
        """Phase 19.1 (§5/§6): the only source of truth for whether Twelve
        Data streaming is genuinely usable -- built entirely from evidence
        already observed on the wire (subscribe-status acks, price ticks,
        rate-limit/auth errors), never from configuration."""
        if self._rate_limited:
            return MarketDataEntitlement(
                provider="twelve_data",
                status=EntitlementStatus.RATE_LIMITED,
                reason="Twelve Data WebSocket reported a rate-limit/quota error.",
            )
        if self._auth_failed:
            return MarketDataEntitlement(
                provider="twelve_data",
                status=EntitlementStatus.MISCONFIGURED,
                reason="Twelve Data WebSocket authentication failed -- check TWELVE_DATA_API_KEY.",
            )
        if self.subscribed_symbols:
            return MarketDataEntitlement(
                provider="twelve_data",
                status=EntitlementStatus.TRIAL_ONLY,
                reason=(
                    "Genuine WebSocket subscription confirmed for: "
                    f"{', '.join(sorted(self.subscribed_symbols))} "
                    "(Basic/free plan trial access -- other symbols may not be included)."
                ),
            )
        if self.rejected_symbols:
            return MarketDataEntitlement(
                provider="twelve_data",
                status=EntitlementStatus.NOT_ENTITLED,
                reason=(
                    "Twelve Data rejected WebSocket subscription for: "
                    f"{', '.join(sorted(self.rejected_symbols))}."
                ),
            )
        return None


def _epoch_to_datetime(value) -> datetime:
    return datetime.fromtimestamp(float(value), tz=timezone.utc)
