"""Massive (massive.com) push-streaming implementation of
StreamingMarketDataProvider (Phase 12.2 §B/§K/§L/§V).

Wire protocol (per current official docs, massive.com/docs/websocket/stocks/*):
  - Connect: wss://socket.massive.com/stocks (real-time) or
    wss://delayed.massive.com/stocks (15-min delayed).
  - Auth: send {"action":"auth","params":"<API_KEY>"}, expect a `status`
    message with status == "auth_success".
  - Subscribe: send {"action":"subscribe","params":"T.AAPL,Q.AAPL,A.AAPL"}
    -- ONE connection subscribes to many tickers/channels at once (T=trades,
    Q=NBBO quotes, A=per-second aggregates). Unsubscribe mirrors this with
    action="unsubscribe".
  - Messages arrive as a JSON array of event objects, each with an `ev`
    discriminator: "T" (trade), "Q" (quote), "A" (aggregate), "status".

This module is the ONLY place that knows any of the above -- everything
above app.live.streaming.StreamingMarketDataProvider deals exclusively in
normalized StreamTrade/StreamNbbo/StreamAggregate/StreamStatus objects.
`ws_connect` is injectable so unit tests never open a real socket (see
tests/unit/live/test_massive_streaming.py's fake transport).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone

from app.live.streaming import (
    CHANNEL_AGGREGATES,
    CHANNEL_QUOTES,
    CHANNEL_TRADES,
    StreamAggregate,
    StreamEvent,
    StreamingMarketDataProvider,
    StreamNbbo,
    StreamStatus,
    StreamTrade,
)
from app.market_data.capabilities import MASSIVE_CAPABILITIES, ProviderCapabilities
from app.market_data.exceptions import AuthenticationError

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = {CHANNEL_TRADES: "T", CHANNEL_QUOTES: "Q", CHANNEL_AGGREGATES: "A"}
_AUTH_TIMEOUT_SECONDS = 10.0
# (§V) Untrusted external input is bounded, never trusted at arbitrary size.
_MAX_MESSAGE_BYTES = 1_000_000

DEFAULT_MASSIVE_WS_URL = "wss://socket.massive.com/stocks"


class MassiveStreamingProvider(StreamingMarketDataProvider):
    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_MASSIVE_WS_URL,
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

    def capabilities(self) -> ProviderCapabilities:
        return MASSIVE_CAPABILITIES

    async def connect(self) -> None:
        # The API key never leaves this process in a log line, an exception
        # message, or anywhere the browser can see (§V) -- only sent once,
        # over TLS, as the auth message's own payload.
        self._ws = await self._ws_connect(self._url)
        await self._ws.send(json.dumps({"action": "auth", "params": self._api_key}))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=_AUTH_TIMEOUT_SECONDS)
        messages = _parse_messages(raw)
        if not any(isinstance(m, dict) and m.get("status") == "auth_success" for m in messages):
            raise AuthenticationError("Massive WebSocket authentication failed")

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def subscribe(self, symbol: str, channels: frozenset) -> None:
        self._subscriptions.setdefault(symbol, set()).update(channels)
        params = _channel_params(symbol, channels)
        if params and self._ws is not None:
            await self._ws.send(json.dumps({"action": "subscribe", "params": params}))

    async def unsubscribe(self, symbol: str, channels: frozenset) -> None:
        current = self._subscriptions.get(symbol)
        params = _channel_params(symbol, channels)
        if current is not None:
            current -= channels
            if not current:
                self._subscriptions.pop(symbol, None)
        if params and self._ws is not None:
            await self._ws.send(json.dumps({"action": "unsubscribe", "params": params}))

    async def events(self) -> AsyncIterator[StreamEvent]:
        if self._ws is None:
            raise RuntimeError("MassiveStreamingProvider.events() called before connect()")
        async for raw in self._ws:
            if isinstance(raw, (bytes, bytearray)) and len(raw) > _MAX_MESSAGE_BYTES:
                logger.warning("Dropped oversized Massive message (%d bytes)", len(raw))
                continue
            if isinstance(raw, str) and len(raw.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                logger.warning("Dropped oversized Massive message (%d bytes)", len(raw))
                continue
            for message in _parse_messages(raw):
                event = _normalize_message(message)
                if event is not None:
                    yield event


def _parse_messages(raw) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Dropped malformed Massive message: invalid JSON")
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [m for m in parsed if isinstance(m, dict)]
    logger.warning("Dropped malformed Massive message: unexpected top-level shape")
    return []


def _channel_params(symbol: str, channels: frozenset) -> str:
    return ",".join(
        f"{_CHANNEL_PREFIX[channel]}.{symbol}" for channel in sorted(channels) if channel in _CHANNEL_PREFIX
    )


def _normalize_message(message: dict) -> StreamEvent | None:
    """(§V) Untrusted external input: every required field is validated
    before use; a malformed event is dropped and logged, never allowed to
    crash the stream or propagate a provider-shaped object upward."""
    ev = message.get("ev")
    try:
        if ev == "T":
            return StreamTrade(
                symbol=message["sym"],
                price=float(message["p"]),
                size=float(message["s"]),
                exchange=message.get("x"),
                conditions=tuple(int(c) for c in (message.get("c") or [])),
                source_timestamp=_ms_to_datetime(message["t"]),
                sequence=message.get("q"),
            )
        if ev == "Q":
            return StreamNbbo(
                symbol=message["sym"],
                bid=float(message["bp"]),
                ask=float(message["ap"]),
                bid_size=float(message.get("bs", 0)),
                ask_size=float(message.get("as", 0)),
                source_timestamp=_ms_to_datetime(message["t"]),
                sequence=message.get("q"),
            )
        if ev == "A":
            return StreamAggregate(
                symbol=message["sym"],
                open=float(message["o"]),
                high=float(message["h"]),
                low=float(message["l"]),
                close=float(message["c"]),
                volume=float(message.get("v", 0)),
                window_start=_ms_to_datetime(message["s"]),
                window_end=_ms_to_datetime(message["e"]),
            )
        if ev == "status":
            return StreamStatus(
                connected=message.get("status") == "auth_success",
                message=str(message.get("message", "")),
            )
    except (KeyError, TypeError, ValueError):
        logger.warning("Dropped malformed Massive %r message: missing/invalid fields", ev)
        return None
    # Unrecognized event type (a new channel Massive adds later, LULD/FMV,
    # etc) -- ignored, not forwarded, never crashes the stream.
    return None


def _ms_to_datetime(ms) -> datetime:
    return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc)
