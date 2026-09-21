"""Phase 12.1 (#G/#H): the event-driven recomputation graph. The one and
only trigger for authoritative recomputation is a CompletedCandleEvent --
a forming-candle price move or a raw quote tick never reaches this module,
which is what mechanically prevents premature pivot/BOS/CHOCH/setup
confirmation (#G). Reuses app.ai_analysis.market_snapshot.build_market_
snapshot verbatim -- no parallel statistics engine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.ai_analysis.market_snapshot import MarketSnapshot, build_market_snapshot
from app.live.events import CompletedCandleEvent, LiveEvent
from app.live.service import LiveMarketService
from app.market_data.cache import Cache
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Timeframe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotRefreshedEvent:
    symbol: str
    timeframe: Timeframe
    refreshed_at: datetime


@dataclass
class _RefreshedSnapshot:
    bundle: MarketSnapshot
    refreshed_at: datetime


class RecomputationEngine:
    """Subscribes to one LiveMarketService's event stream and, strictly on
    CompletedCandleEvent, invalidates the stale candle cache entry and
    recomputes the canonical market snapshot -- so the next request (or the
    next WebSocket push) sees the newly-closed bar's authoritative
    structure/S-R/setup state immediately, not after waiting out whatever
    candle-cache TTL happened to be in flight."""

    def __init__(
        self,
        live_service: LiveMarketService,
        market_provider: MarketDataProvider,
        cache: Cache,
        now_fn=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._live_service = live_service
        self._market_provider = market_provider
        self._cache = cache
        self._now = now_fn
        self._snapshots: dict[tuple[str, Timeframe], _RefreshedSnapshot] = {}
        self._listeners: list[asyncio.Queue] = []
        self._queue: Optional["asyncio.Queue[LiveEvent]"] = None
        self._task: Optional[asyncio.Task] = None

    def latest_snapshot(self, symbol: str, timeframe: Timeframe) -> Optional[MarketSnapshot]:
        entry = self._snapshots.get((symbol, timeframe))
        return entry.bundle if entry else None

    def add_listener(self) -> "asyncio.Queue[SnapshotRefreshedEvent]":
        queue: "asyncio.Queue[SnapshotRefreshedEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: "asyncio.Queue[SnapshotRefreshedEvent]") -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def handle_event(self, event: LiveEvent) -> Optional[SnapshotRefreshedEvent]:
        """The directly-testable core: given one live event, recompute if
        (and only if) it is a CompletedCandleEvent. Returns the emitted
        SnapshotRefreshedEvent, or None if the event wasn't actionable."""
        if not isinstance(event, CompletedCandleEvent):
            return None

        symbol = event.symbol
        timeframe = Timeframe(event.candle.timeframe)
        self._cache.delete_prefix(f"candles:{symbol}:{timeframe.value}:")

        refreshed_at = self._now()
        bundle = build_market_snapshot(symbol, timeframe, self._market_provider, refreshed_at)
        self._snapshots[(symbol, timeframe)] = _RefreshedSnapshot(bundle=bundle, refreshed_at=refreshed_at)

        refresh_event = SnapshotRefreshedEvent(symbol=symbol, timeframe=timeframe, refreshed_at=refreshed_at)
        for queue in list(self._listeners):
            queue.put_nowait(refresh_event)
        return refresh_event

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._queue = self._live_service.add_listener()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue is not None:
            self._live_service.remove_listener(self._queue)
            self._queue = None

    async def _run(self) -> None:
        assert self._queue is not None
        try:
            while True:
                event = await self._queue.get()
                try:
                    self.handle_event(event)
                except Exception:
                    logger.exception("Recomputation failed for event %r", event)
        except asyncio.CancelledError:
            return
