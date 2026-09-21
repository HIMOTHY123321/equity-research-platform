"""Phase 12.1 (#A/#B/#N/#R): LiveMarketService -- the one centralized
subscription/cache layer. One poll loop per subscribed symbol, shared by
every subscriber (viewed ticker, watchlist, active forecasts, background
benchmark) so N interested consumers of SPY never become N independent
pollers (#O). Streaming-shaped on purpose (subscribe/unsubscribe,
event fan-out via add_listener) even though the only provider implemented
today (yfinance) is polled underneath -- a future streaming provider plugs
in here without changing this class's public contract (see ADR 0017).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.live.candle_builder import bucket_start, fold_price_into_candle
from app.live.config import (
    DEFAULT_LIVE_CONFIG,
    LiveConfig,
    SubscriptionPriority,
    classify_freshness,
    resolve_poll_interval,
)
from app.live.events import (
    CompletedCandleEvent,
    ConnectionStatusEvent,
    FormingCandleEvent,
    LiveEvent,
    QuoteEvent,
)
from app.live.market_hours import current_live_session
from app.live.schemas import (
    CandleState,
    ConnectionState,
    ConnectionStatus,
    FreshnessInfo,
    LiveCandle,
    LiveQuote,
)
from app.market_data.capabilities import ProviderCapabilities
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Quote, Timeframe

logger = logging.getLogger(__name__)

_PRIORITY_ORDER = (
    SubscriptionPriority.VIEWED,
    SubscriptionPriority.ACTIVE_FORECAST,
    SubscriptionPriority.WATCHLIST,
    SubscriptionPriority.BACKGROUND_BENCHMARK,
)


def _highest_priority(counts: dict[SubscriptionPriority, int]) -> SubscriptionPriority:
    for priority in _PRIORITY_ORDER:
        if counts.get(priority, 0) > 0:
            return priority
    return SubscriptionPriority.BACKGROUND_BENCHMARK


@dataclass
class _SymbolState:
    subscriber_counts: dict[SubscriptionPriority, int] = field(default_factory=lambda: defaultdict(int))
    timeframes: set = field(default_factory=set)
    last_quote_timestamp: Optional[datetime] = None
    last_live_quote: Optional[LiveQuote] = None
    previous_close: Optional[float] = None
    forming_candles: dict = field(default_factory=dict)


class LiveMarketService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_name: str,
        config: LiveConfig = DEFAULT_LIVE_CONFIG,
        now_fn=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._provider_name = provider_name
        self._config = config
        self._now = now_fn
        self._symbols: dict[str, _SymbolState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._listeners: list[asyncio.Queue] = []
        self._connection_state = ConnectionState.DISCONNECTED
        self._reconnect_attempts = 0
        self._last_message_at: Optional[datetime] = None

    # ------------------------------------------------------------- capability

    def provider_capabilities(self) -> ProviderCapabilities:
        return self._provider.capabilities()

    # ----------------------------------------------------------- subscription

    async def subscribe(
        self,
        symbol: str,
        priority: SubscriptionPriority = SubscriptionPriority.VIEWED,
        timeframes: tuple[Timeframe, ...] = (Timeframe.ONE_HOUR,),
    ) -> None:
        state = self._symbols.get(symbol)
        is_new = state is None
        if is_new:
            state = _SymbolState()
            self._symbols[symbol] = state
        state.subscriber_counts[priority] += 1
        state.timeframes.update(timeframes)

        if is_new:
            try:
                previous_close = await asyncio.to_thread(self._provider.get_previous_close, symbol)
                state.previous_close = previous_close.close
            except Exception:
                # Honest degradation (#D): percent_change simply stays
                # unavailable rather than guessing a previous close.
                state.previous_close = None

        existing_task = self._tasks.get(symbol)
        if existing_task is None or existing_task.done():
            self._tasks[symbol] = asyncio.create_task(self._poll_loop(symbol))

    async def unsubscribe(
        self, symbol: str, priority: SubscriptionPriority = SubscriptionPriority.VIEWED
    ) -> None:
        state = self._symbols.get(symbol)
        if state is None:
            return
        if state.subscriber_counts.get(priority, 0) > 0:
            state.subscriber_counts[priority] -= 1
        if sum(state.subscriber_counts.values()) <= 0:
            task = self._tasks.pop(symbol, None)
            if task is not None:
                task.cancel()
            del self._symbols[symbol]

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._symbols.clear()

    # ------------------------------------------------------------------ reads

    def latest_quote(self, symbol: str) -> Optional[LiveQuote]:
        state = self._symbols.get(symbol)
        return state.last_live_quote if state else None

    def latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[LiveCandle]:
        state = self._symbols.get(symbol)
        if state is None:
            return None
        return state.forming_candles.get(timeframe)

    def freshness(self, symbol: str) -> Optional[FreshnessInfo]:
        quote = self.latest_quote(symbol)
        return quote.freshness if quote else None

    def connection_status(self) -> ConnectionStatus:
        return ConnectionStatus(
            state=self._connection_state,
            last_message_at=self._last_message_at,
            reconnect_attempts=self._reconnect_attempts,
            subscribed_symbols=sorted(self._symbols.keys()),
        )

    # ------------------------------------------------------------- event bus

    def add_listener(self) -> "asyncio.Queue[LiveEvent]":
        queue: "asyncio.Queue[LiveEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: "asyncio.Queue[LiveEvent]") -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def _publish(self, event: LiveEvent) -> None:
        for queue in list(self._listeners):
            queue.put_nowait(event)

    # ------------------------------------------------------------- ingestion

    def ingest_quote(self, symbol: str, quote: Quote, received_at: datetime) -> None:
        """The directly-testable core (#R): only a strictly-newer source
        timestamp is ever accepted -- an equal or older one (duplicate,
        delayed/out-of-order delivery) is silently dropped, never allowed
        to overwrite newer state."""
        state = self._symbols.setdefault(symbol, _SymbolState())
        if state.last_quote_timestamp is not None and quote.timestamp <= state.last_quote_timestamp:
            return
        state.last_quote_timestamp = quote.timestamp

        session = current_live_session(quote.timestamp)
        age_seconds = max((received_at - quote.timestamp).total_seconds(), 0.0)
        freshness = FreshnessInfo(
            source_timestamp=quote.timestamp,
            received_at=received_at,
            age_seconds=age_seconds,
            provider=self._provider_name,
            market_session=session,
            freshness_state=classify_freshness(
                age_seconds, connected=True, session=session, config=self._config
            ),
        )

        price = quote.bid_price if quote.is_approximate else (quote.bid_price + quote.ask_price) / 2
        spread = max(quote.ask_price - quote.bid_price, 0.0)
        percent_change = (
            (price - state.previous_close) / state.previous_close * 100 if state.previous_close else None
        )

        live_quote = LiveQuote(
            symbol=symbol,
            price=price,
            bid=quote.bid_price,
            ask=quote.ask_price,
            spread=spread,
            is_approximate=quote.is_approximate,
            previous_close=state.previous_close,
            percent_change=percent_change,
            freshness=freshness,
        )
        state.last_live_quote = live_quote
        self._publish(QuoteEvent(symbol=symbol, quote=live_quote))

        for timeframe in state.timeframes:
            self._fold_forming_candle(state, symbol, timeframe, quote.timestamp, price, freshness)

    def _fold_forming_candle(
        self, state: _SymbolState, symbol: str, timeframe: Timeframe, at: datetime, price: float, freshness
    ) -> None:
        bucket_open = bucket_start(at, timeframe)
        existing = state.forming_candles.get(timeframe)
        if existing is not None and existing.timestamp != bucket_open:
            # (#G) Boundary crossed -- the old forming bar is now
            # authoritatively COMPLETED. This is the *only* trigger
            # app.live.recompute ever acts on; a forming-candle price move
            # never reaches it.
            completed = existing.model_copy(update={"state": CandleState.COMPLETED, "freshness": freshness})
            self._publish(CompletedCandleEvent(symbol=symbol, candle=completed))
            existing = None

        updated = fold_price_into_candle(
            existing,
            symbol=symbol,
            timeframe=timeframe,
            bucket_open=bucket_open,
            price=price,
            volume=0.0,  # (#D) yfinance's quote surface has no real-time trade volume to fold in honestly.
            freshness=freshness,
        )
        state.forming_candles[timeframe] = updated
        self._publish(FormingCandleEvent(symbol=symbol, candle=updated))

    # --------------------------------------------------------------- polling

    async def _poll_loop(self, symbol: str) -> None:
        try:
            while True:
                state = self._symbols.get(symbol)
                if state is None:
                    return
                priority = _highest_priority(state.subscriber_counts)
                caps = self._provider.capabilities()
                interval = resolve_poll_interval(caps.min_poll_interval_seconds, priority, self._config)

                if self._connection_state == ConnectionState.DISCONNECTED:
                    self._set_connection_state(ConnectionState.RESYNCING)

                try:
                    quote = await asyncio.to_thread(self._provider.get_latest_quote, symbol)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Live poll failed for %s", symbol, exc_info=True)
                    self._reconnect_attempts += 1
                    self._set_connection_state(ConnectionState.DISCONNECTED)
                    backoff = min(
                        self._config.reconnect_initial_backoff_seconds
                        * (self._config.reconnect_backoff_multiplier ** (self._reconnect_attempts - 1)),
                        self._config.reconnect_max_backoff_seconds,
                    )
                    await asyncio.sleep(backoff)
                    continue

                received_at = self._now()
                self.ingest_quote(symbol, quote, received_at)
                self._last_message_at = received_at
                self._reconnect_attempts = 0
                self._set_connection_state(ConnectionState.CONNECTED)

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

    def _set_connection_state(self, new_state: ConnectionState) -> None:
        if new_state != self._connection_state:
            self._connection_state = new_state
            self._publish(ConnectionStatusEvent(status=self.connection_status()))
