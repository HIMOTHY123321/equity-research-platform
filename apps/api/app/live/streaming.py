"""Phase 12.2 (#B/#C/#K/#L): provider-agnostic push-streaming abstraction.

A StreamingMarketDataProvider owns exactly ONE upstream connection servicing
every subscribed symbol/channel -- LiveMarketService's stream supervisor is
the only thing that ever calls it, never once per symbol (see ADR 0018).
Normalized event schemas here carry no provider-specific field names; no
Massive-shaped dict leaks past app.market_data.massive_streaming.

This mirrors app.market_data.provider's discipline: nothing outside this
module (and the one implementation that talks to a real vendor) should know
what "Massive" is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

from app.live.entitlement import MarketDataEntitlement
from app.market_data.capabilities import ProviderCapabilities

# Channel identifiers -- provider-agnostic; each StreamingMarketDataProvider
# implementation maps these to its own wire format (e.g. Massive's T./Q./A.
# channel prefixes).
CHANNEL_TRADES = "trades"
CHANNEL_QUOTES = "quotes"
CHANNEL_AGGREGATES = "aggregates"

ALL_CHANNELS = frozenset({CHANNEL_TRADES, CHANNEL_QUOTES, CHANNEL_AGGREGATES})


@dataclass(frozen=True)
class StreamTrade:
    """A single executed trade (#G) -- this, never a quote midpoint, is the
    authoritative "last price" for a symbol once any trade has been seen."""

    symbol: str
    price: float
    size: float
    exchange: Optional[int]
    conditions: tuple[int, ...]
    source_timestamp: datetime
    sequence: Optional[int] = None


@dataclass(frozen=True)
class StreamNbbo:
    """A National Best Bid and Offer update (#G) -- displayed separately
    from last-trade price, never silently substituted for it."""

    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    source_timestamp: datetime
    sequence: Optional[int] = None


@dataclass(frozen=True)
class StreamAggregate:
    """A completed per-second OHLCV window (#H) -- the source for real
    forming-candle volume, replacing yfinance's volume=0.0 approximation.
    Never itself promoted into a confirmed research bar; only a real
    higher-timeframe boundary crossing (candle_builder.bucket_start)
    triggers CompletedCandleEvent."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True)
class StreamStatus:
    connected: bool
    message: str = ""


StreamEvent = Union[StreamTrade, StreamNbbo, StreamAggregate, StreamStatus]


@dataclass(frozen=True)
class StreamingMetrics:
    """(#N) provider-reported/observed connection metrics, surfaced at
    /api/live/status -- never used on their own to claim "real time"."""

    connected: bool
    connect_count: int = 0
    messages_received: int = 0
    malformed_messages_dropped: int = 0


class StreamingMarketDataProvider(ABC):
    """One persistent upstream connection, many symbol/channel subscriptions
    multiplexed over it (#K/#L) -- never one connection per ticker. Callers
    (LiveMarketService's stream supervisor) own reconnect/backoff/resubscribe;
    an implementation only needs to raise out of `events()` on a genuine
    disconnect and support being `connect()`-ed again afterward."""

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def connect(self) -> None:
        """Open the upstream connection and authenticate. Raises on failure
        -- never silently returns as if connected."""

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def subscribe(self, symbol: str, channels: frozenset) -> None: ...

    @abstractmethod
    async def unsubscribe(self, symbol: str, channels: frozenset) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[StreamEvent]:
        """An async generator over normalized events for every currently
        subscribed symbol/channel. Raises (e.g. on a dropped connection) to
        signal the supervisor a reconnect+resubscribe cycle is needed --
        never returns silently and never yields a fabricated event."""

    def entitlement_hint(self) -> Optional[MarketDataEntitlement]:
        """Phase 19.1 (§5/§6): an OPTIONAL, non-abstract escape hatch for
        providers (like Twelve Data) whose real entitlement can only be
        discovered at runtime from the wire protocol itself -- e.g. a
        subscribe-status acknowledgement that names which symbols were
        actually accepted vs rejected. Returns None by default (no opinion;
        LiveMarketService's stored entitlement is left untouched), which is
        exactly what a provider like Massive -- whose entitlement is a
        static, operator-attested account fact, not something the wire
        protocol reveals -- should keep doing by simply not overriding
        this. A non-None return is only ever evidence-based, never a
        default/optimistic guess."""
        return None
