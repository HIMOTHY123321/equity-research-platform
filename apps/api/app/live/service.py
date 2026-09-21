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

from app.live.candle_builder import bucket_start, fold_aggregate_into_candle, fold_price_into_candle
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
from app.live.latency import LatencySummary, LatencyTracker
from app.live.market_hours import current_live_session
from app.live.schemas import (
    CandleState,
    ConnectionState,
    ConnectionStatus,
    FreshnessInfo,
    LiveCandle,
    LiveQuote,
)
from app.live.streaming import (
    ALL_CHANNELS,
    StreamAggregate,
    StreamingMarketDataProvider,
    StreamNbbo,
    StreamStatus,
    StreamTrade,
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
    # Phase 12.2 streaming state -- unused (left at defaults) on the
    # yfinance/Alpaca poll path.
    stream_channels: frozenset = field(default_factory=frozenset)
    last_trade_timestamp: Optional[datetime] = None
    last_trade_sequence: Optional[int] = None
    last_nbbo_timestamp: Optional[datetime] = None
    last_nbbo_sequence: Optional[int] = None
    last_aggregate_window_end: Optional[datetime] = None


def _is_newer(
    timestamp: datetime,
    sequence: Optional[int],
    last_timestamp: Optional[datetime],
    last_sequence: Optional[int],
) -> bool:
    """(#E/#M) Ordering policy shared by trade/NBBO ingestion: a strictly
    later source timestamp is always accepted; an equal timestamp is only
    accepted if both sides carry a sequence number and the new one is
    strictly greater (the provider's own tiebreak for same-instant events).
    Anything else -- an older timestamp, an equal timestamp with no usable
    sequence, a duplicate replay after reconnect -- is dropped. Older state
    never overwrites newer state."""
    if last_timestamp is None:
        return True
    if timestamp != last_timestamp:
        return timestamp > last_timestamp
    if sequence is None or last_sequence is None:
        return False
    return sequence > last_sequence


def _latest_timestamp(a: datetime, b: Optional[datetime]) -> datetime:
    if b is None or a >= b:
        return a
    return b


class LiveMarketService:
    def __init__(
        self,
        provider: MarketDataProvider,
        provider_name: str,
        config: LiveConfig = DEFAULT_LIVE_CONFIG,
        now_fn=lambda: datetime.now(timezone.utc),
        streaming_provider: Optional[StreamingMarketDataProvider] = None,
        latency_tracker: Optional[LatencyTracker] = None,
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
        # Phase 12.2 (#A/#K): when set and its capabilities() genuinely
        # declare streaming, ALL symbol subscriptions share this ONE
        # supervisor task / ONE upstream connection instead of one poll task
        # per symbol -- see _use_streaming/_stream_supervisor.
        self._streaming_provider = streaming_provider
        self._stream_task: Optional[asyncio.Task] = None
        self._latency = latency_tracker or LatencyTracker()

    # ------------------------------------------------------------- capability

    def provider_capabilities(self) -> ProviderCapabilities:
        if self._use_streaming():
            return self._streaming_provider.capabilities()
        return self._provider.capabilities()

    def is_streaming(self) -> bool:
        return self._use_streaming()

    def latency_summary(self) -> list[LatencySummary]:
        return self._latency.summary()

    def _use_streaming(self) -> bool:
        if self._streaming_provider is None:
            return False
        caps = self._streaming_provider.capabilities()
        return caps.streaming_trades or caps.streaming_quotes

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

        if self._use_streaming():
            # (#K) one shared supervisor/connection for every symbol -- never
            # a task per symbol on this path.
            state.stream_channels = ALL_CHANNELS
            await self._ensure_stream_supervisor()
            if self._connection_state == ConnectionState.CONNECTED:
                with contextlib.suppress(Exception):
                    await self._streaming_provider.subscribe(symbol, state.stream_channels)
            # else: the supervisor's own post-connect resubscribe loop (see
            # _stream_supervisor) will pick this symbol up once connected.
        else:
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
            if self._use_streaming() and state.stream_channels:
                with contextlib.suppress(Exception):
                    await self._streaming_provider.unsubscribe(symbol, state.stream_channels)
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
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None
        if self._streaming_provider is not None:
            with contextlib.suppress(Exception):
                await self._streaming_provider.disconnect()
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

    # ------------------------------------------------------- streaming (#K/#Q)

    async def _ensure_stream_supervisor(self) -> None:
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._stream_supervisor())

    async def _stream_supervisor(self) -> None:
        """(#K/#Q) The ONE task that owns the upstream streaming connection
        for every subscribed symbol. On any failure: DISCONNECTED, backoff,
        RESYNCING, reconnect, re-authenticate, resubscribe every symbol this
        service still tracks -- only then does the next successful event
        loop bring the state back to CONNECTED. A dropped connection never
        silently falls back to a different provider (#P) -- it stays
        DISCONNECTED/RESYNCING until this same upstream genuinely recovers."""
        try:
            while True:
                try:
                    await self._streaming_provider.connect()
                    for symbol, state in list(self._symbols.items()):
                        if state.stream_channels:
                            await self._streaming_provider.subscribe(symbol, state.stream_channels)
                    self._reconnect_attempts = 0
                    self._set_connection_state(ConnectionState.CONNECTED)
                    async for event in self._streaming_provider.events():
                        self._handle_stream_event(event)
                        self._last_message_at = self._now()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Streaming connection lost", exc_info=True)
                    self._reconnect_attempts += 1
                    self._set_connection_state(ConnectionState.DISCONNECTED)
                    backoff = min(
                        self._config.reconnect_initial_backoff_seconds
                        * (self._config.reconnect_backoff_multiplier ** (self._reconnect_attempts - 1)),
                        self._config.reconnect_max_backoff_seconds,
                    )
                    await asyncio.sleep(backoff)
                    self._set_connection_state(ConnectionState.RESYNCING)
        except asyncio.CancelledError:
            return

    def _handle_stream_event(self, event) -> None:
        received_at = self._now()
        if isinstance(event, StreamTrade):
            self.ingest_trade(event, received_at)
        elif isinstance(event, StreamNbbo):
            self.ingest_nbbo(event, received_at)
        elif isinstance(event, StreamAggregate):
            self.ingest_second_aggregate(event, received_at)
        elif isinstance(event, StreamStatus):
            return

    def ingest_trade(self, trade: StreamTrade, received_at: datetime) -> None:
        """(#G) The primary displayed price -- a real executed trade, never
        a bid/ask midpoint. Out-of-order/duplicate trades are dropped via
        _is_newer, never allowed to overwrite a newer price."""
        state = self._symbols.setdefault(trade.symbol, _SymbolState())
        if not _is_newer(
            trade.source_timestamp, trade.sequence, state.last_trade_timestamp, state.last_trade_sequence
        ):
            return
        state.last_trade_timestamp = trade.source_timestamp
        state.last_trade_sequence = trade.sequence
        self._latency.record(
            "trade",
            trade.symbol,
            self._provider_name,
            (received_at - trade.source_timestamp).total_seconds(),
        )

        previous = state.last_live_quote
        anchor_ts = _latest_timestamp(
            trade.source_timestamp, previous.freshness.source_timestamp if previous else None
        )
        session = current_live_session(anchor_ts)
        age_seconds = max((received_at - anchor_ts).total_seconds(), 0.0)
        freshness = FreshnessInfo(
            source_timestamp=anchor_ts,
            received_at=received_at,
            age_seconds=age_seconds,
            provider=self._provider_name,
            market_session=session,
            freshness_state=classify_freshness(
                age_seconds, connected=True, session=session, config=self._config
            ),
        )
        percent_change = (
            (trade.price - state.previous_close) / state.previous_close * 100
            if state.previous_close
            else None
        )

        live_quote = LiveQuote(
            symbol=trade.symbol,
            price=trade.price,
            bid=previous.bid if previous else trade.price,
            ask=previous.ask if previous else trade.price,
            spread=previous.spread if previous else 0.0,
            is_approximate=False,
            previous_close=state.previous_close,
            percent_change=percent_change,
            last_trade_price=trade.price,
            last_trade_size=trade.size,
            last_trade_timestamp=trade.source_timestamp,
            last_trade_exchange=trade.exchange,
            nbbo_timestamp=previous.nbbo_timestamp if previous else None,
            freshness=freshness,
        )
        state.last_live_quote = live_quote
        self._publish(QuoteEvent(symbol=trade.symbol, quote=live_quote))

    def ingest_nbbo(self, nbbo: StreamNbbo, received_at: datetime) -> None:
        """(#G) NBBO is tracked and displayed independently of last-trade
        price -- this never overwrites `price` unless no real trade has
        been observed yet for this symbol (approximate mid, same honest
        degradation the yfinance path already uses)."""
        state = self._symbols.setdefault(nbbo.symbol, _SymbolState())
        if not _is_newer(
            nbbo.source_timestamp, nbbo.sequence, state.last_nbbo_timestamp, state.last_nbbo_sequence
        ):
            return
        state.last_nbbo_timestamp = nbbo.source_timestamp
        state.last_nbbo_sequence = nbbo.sequence
        self._latency.record(
            "quote", nbbo.symbol, self._provider_name, (received_at - nbbo.source_timestamp).total_seconds()
        )

        previous = state.last_live_quote
        has_trade = previous is not None and previous.last_trade_price is not None
        price = previous.last_trade_price if has_trade else (nbbo.bid + nbbo.ask) / 2
        anchor_ts = _latest_timestamp(
            nbbo.source_timestamp, previous.last_trade_timestamp if previous else None
        )
        session = current_live_session(anchor_ts)
        age_seconds = max((received_at - anchor_ts).total_seconds(), 0.0)
        freshness = FreshnessInfo(
            source_timestamp=anchor_ts,
            received_at=received_at,
            age_seconds=age_seconds,
            provider=self._provider_name,
            market_session=session,
            freshness_state=classify_freshness(
                age_seconds, connected=True, session=session, config=self._config
            ),
        )
        percent_change = (
            (price - state.previous_close) / state.previous_close * 100 if state.previous_close else None
        )

        live_quote = LiveQuote(
            symbol=nbbo.symbol,
            price=price,
            bid=nbbo.bid,
            ask=nbbo.ask,
            spread=max(nbbo.ask - nbbo.bid, 0.0),
            is_approximate=not has_trade,
            previous_close=state.previous_close,
            percent_change=percent_change,
            last_trade_price=previous.last_trade_price if previous else None,
            last_trade_size=previous.last_trade_size if previous else None,
            last_trade_timestamp=previous.last_trade_timestamp if previous else None,
            last_trade_exchange=previous.last_trade_exchange if previous else None,
            nbbo_timestamp=nbbo.source_timestamp,
            freshness=freshness,
        )
        state.last_live_quote = live_quote
        self._publish(QuoteEvent(symbol=nbbo.symbol, quote=live_quote))

    def ingest_second_aggregate(self, agg: StreamAggregate, received_at: datetime) -> None:
        """(#H) Real per-second OHLCV folded into every subscribed
        higher-timeframe forming candle -- genuine volume, never the
        yfinance quote path's volume=0.0 approximation. A boundary crossing
        here publishes CompletedCandleEvent exactly as the quote-driven fold
        does; RecomputationEngine re-fetches the authoritative bar via REST
        regardless of source, so this never itself becomes the bar of
        record (#I/#J)."""
        state = self._symbols.setdefault(agg.symbol, _SymbolState())
        if (
            state.last_aggregate_window_end is not None
            and agg.window_end <= state.last_aggregate_window_end
        ):
            return
        state.last_aggregate_window_end = agg.window_end
        self._latency.record(
            "aggregate",
            agg.symbol,
            self._provider_name,
            (received_at - agg.window_end).total_seconds(),
        )

        session = current_live_session(agg.window_end)
        age_seconds = max((received_at - agg.window_end).total_seconds(), 0.0)
        freshness = FreshnessInfo(
            source_timestamp=agg.window_end,
            received_at=received_at,
            age_seconds=age_seconds,
            provider=self._provider_name,
            market_session=session,
            freshness_state=classify_freshness(
                age_seconds, connected=True, session=session, config=self._config
            ),
        )
        for timeframe in state.timeframes:
            self._fold_forming_candle_from_aggregate(state, agg.symbol, timeframe, agg, freshness)

    def _fold_forming_candle_from_aggregate(
        self, state: _SymbolState, symbol: str, timeframe: Timeframe, agg: StreamAggregate, freshness
    ) -> None:
        bucket_open = bucket_start(agg.window_start, timeframe)
        existing = state.forming_candles.get(timeframe)
        if existing is not None and existing.timestamp != bucket_open:
            completed = existing.model_copy(update={"state": CandleState.COMPLETED, "freshness": freshness})
            self._publish(CompletedCandleEvent(symbol=symbol, candle=completed))
            existing = None

        updated = fold_aggregate_into_candle(
            existing,
            symbol=symbol,
            timeframe=timeframe,
            bucket_open=bucket_open,
            open_=agg.open,
            high=agg.high,
            low=agg.low,
            close=agg.close,
            volume=agg.volume,
            freshness=freshness,
        )
        state.forming_candles[timeframe] = updated
        self._publish(FormingCandleEvent(symbol=symbol, candle=updated))
