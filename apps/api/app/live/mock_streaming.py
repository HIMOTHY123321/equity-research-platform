"""Phase 12.2 (#X): a deterministic, fully-scriptable StreamingMarketDataProvider
for tests. No test in this codebase depends on real Massive credentials or
network access -- this is the one and only streaming provider the test suite
ever talks to.

Usage: push StreamEvent instances (or an Exception, to simulate a dropped
connection) onto the internal queue with `push_event`/`push_disconnect`
before or while a LiveMarketService is consuming `events()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.live.streaming import StreamEvent, StreamingMarketDataProvider
from app.market_data.capabilities import ProviderCapabilities

MOCK_STREAMING_CAPABILITIES = ProviderCapabilities(
    real_time_quotes=True,
    streaming_quotes=True,
    streaming_trades=True,
    streaming_bars=True,
    streaming_news=False,
    historical_intraday=True,
    quote_delay_seconds=0.0,
    news_delay_seconds=None,
    min_poll_interval_seconds=1.0,
)


class MockStreamingProvider(StreamingMarketDataProvider):
    def __init__(self, capabilities: ProviderCapabilities = MOCK_STREAMING_CAPABILITIES) -> None:
        self._capabilities = capabilities
        self._queue: "asyncio.Queue[object]" = asyncio.Queue()
        self.connect_count = 0
        self.connected = False
        self.subscriptions: dict[str, set[str]] = {}
        self.raise_on_next_connect: Exception | None = None

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def connect(self) -> None:
        if self.raise_on_next_connect is not None:
            exc = self.raise_on_next_connect
            self.raise_on_next_connect = None
            raise exc
        self.connect_count += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe(self, symbol: str, channels: frozenset) -> None:
        self.subscriptions.setdefault(symbol, set()).update(channels)

    async def unsubscribe(self, symbol: str, channels: frozenset) -> None:
        current = self.subscriptions.get(symbol)
        if current is None:
            return
        current -= channels
        if not current:
            self.subscriptions.pop(symbol, None)

    async def events(self) -> AsyncIterator[StreamEvent]:
        while True:
            item = await self._queue.get()
            if isinstance(item, BaseException):
                self.connected = False
                raise item
            yield item

    # ---- test-only script controls ------------------------------------

    def push_event(self, event: StreamEvent) -> None:
        self._queue.put_nowait(event)

    def push_disconnect(self, exc: Exception | None = None) -> None:
        self._queue.put_nowait(exc or ConnectionError("simulated Massive stream drop"))
