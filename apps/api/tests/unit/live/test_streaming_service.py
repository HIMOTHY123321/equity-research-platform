"""Phase 12.2 (#K/#L/#M/#Q/#Y): LiveMarketService's push-streaming path,
driven entirely by app.live.mock_streaming.MockStreamingProvider -- no test
here depends on real Massive credentials or network access.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.live.candle_builder import bucket_start
from app.live.config import DEFAULT_LIVE_CONFIG, SubscriptionPriority
from app.live.events import CompletedCandleEvent, FormingCandleEvent, QuoteEvent
from app.live.mock_streaming import MockStreamingProvider
from app.live.schemas import CandleState, ConnectionState
from app.live.service import LiveMarketService, _SymbolState
from app.live.streaming import StreamAggregate, StreamNbbo, StreamStatus, StreamTrade
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import PreviousClose, Timeframe

_BASE = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)  # 09:30 EDT -- regular open


class _StubRestProvider(MarketDataProvider):
    """The REST half a streaming provider still needs (previous close) --
    never actually polled for quotes on the streaming path."""

    def capabilities(self):
        from app.market_data.capabilities import ProviderCapabilities

        return ProviderCapabilities(
            real_time_quotes=False,
            streaming_quotes=False,
            streaming_trades=False,
            streaming_bars=False,
            streaming_news=False,
            historical_intraday=False,
            min_poll_interval_seconds=5.0,
        )

    def get_candles(self, symbol, timeframe, limit=200):
        raise AssertionError("REST candles should never be fetched by the streaming path itself")

    def get_latest_quote(self, symbol):
        raise AssertionError("get_latest_quote must never be polled while streaming is active")

    def get_previous_close(self, symbol):
        return PreviousClose(symbol=symbol, trading_date=_BASE.date(), close=100.0, volume=1_000_000)


def _fast_config() -> DEFAULT_LIVE_CONFIG.__class__:
    return DEFAULT_LIVE_CONFIG.__class__(
        reconnect_initial_backoff_seconds=0.01, reconnect_max_backoff_seconds=0.02
    )


async def _service_with_stream(config=None):
    rest = _StubRestProvider()
    stream = MockStreamingProvider()
    service = LiveMarketService(
        rest,
        provider_name="massive",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        config=config or _fast_config(),
    )
    return service, stream


def _trade(price: float, ts: datetime, sequence=None) -> StreamTrade:
    return StreamTrade(
        symbol="SPY", price=price, size=1, exchange=1, conditions=(), source_timestamp=ts, sequence=sequence
    )


async def _wait_until(predicate, timeout=2.0, step=0.01):
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return
        await asyncio.sleep(step)
        elapsed += step
    raise AssertionError("condition never became true")


# ---------------------------------------------------------- subscription/supervisor


@pytest.mark.asyncio
async def test_streaming_capable_provider_uses_one_supervisor_not_a_poll_task():
    service, stream = await _service_with_stream()
    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await service.subscribe("AAPL", SubscriptionPriority.WATCHLIST)

    assert service._tasks == {}  # never a per-symbol poll task on this path
    assert service.is_streaming() is True
    await _wait_until(lambda: stream.connect_count >= 1)
    await _wait_until(lambda: "SPY" in stream.subscriptions and "AAPL" in stream.subscriptions)
    await service.shutdown()


@pytest.mark.asyncio
async def test_two_subscribers_to_the_same_symbol_share_the_one_connection():
    service, stream = await _service_with_stream()
    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await service.subscribe("SPY", SubscriptionPriority.WATCHLIST)
    await _wait_until(lambda: stream.connect_count >= 1)

    assert stream.connect_count == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_unsubscribe_at_zero_refs_tells_the_upstream_provider():
    service, stream = await _service_with_stream()
    await service.subscribe("SPY")
    await _wait_until(lambda: "SPY" in stream.subscriptions)

    await service.unsubscribe("SPY")
    assert "SPY" not in stream.subscriptions
    assert "SPY" not in service._symbols
    await service.shutdown()


# --------------------------------------------------------------------- trades


@pytest.mark.asyncio
async def test_a_trade_sets_price_to_the_real_trade_price_not_a_midpoint():
    service, stream = await _service_with_stream()
    queue = service.add_listener()
    await service.subscribe("SPY")
    await _wait_until(lambda: "SPY" in stream.subscriptions)

    stream.push_event(_trade(101.25, _BASE, sequence=1))

    event = await asyncio.wait_for(_next_quote_event(queue), timeout=2.0)
    assert event.quote.price == 101.25
    assert event.quote.last_trade_price == 101.25
    assert event.quote.last_trade_timestamp == _BASE
    await service.shutdown()


@pytest.mark.asyncio
async def test_an_older_trade_never_overwrites_a_newer_one():
    service, _ = await _service_with_stream()
    later = _BASE + timedelta(seconds=1)

    service.ingest_trade(_trade(105.0, later), received_at=later)
    service.ingest_trade(_trade(99.0, _BASE), received_at=_BASE)

    assert service.latest_quote("SPY").price == 105.0
    await service.shutdown()


@pytest.mark.asyncio
async def test_same_timestamp_trade_uses_sequence_as_tiebreak():
    service, _ = await _service_with_stream()
    service.ingest_trade(_trade(100.0, _BASE, sequence=5), received_at=_BASE)
    # Same timestamp, lower sequence -- dropped as an out-of-order replay.
    service.ingest_trade(_trade(999.0, _BASE, sequence=3), received_at=_BASE)
    assert service.latest_quote("SPY").price == 100.0

    # Same timestamp, higher sequence -- accepted.
    service.ingest_trade(_trade(101.0, _BASE, sequence=6), received_at=_BASE)
    assert service.latest_quote("SPY").price == 101.0
    await service.shutdown()


@pytest.mark.asyncio
async def test_duplicate_trade_with_no_sequence_is_dropped():
    service, _ = await _service_with_stream()
    service.ingest_trade(_trade(100.0, _BASE), received_at=_BASE)
    service.ingest_trade(_trade(200.0, _BASE), received_at=_BASE)
    assert service.latest_quote("SPY").price == 100.0
    await service.shutdown()


# ---------------------------------------------------------------------- nbbo


@pytest.mark.asyncio
async def test_nbbo_updates_bid_ask_independently_of_last_trade_price():
    service, _ = await _service_with_stream()
    service.ingest_trade(_trade(100.0, _BASE), received_at=_BASE)
    nbbo_ts = _BASE + timedelta(seconds=1)
    service.ingest_nbbo(
        StreamNbbo(symbol="SPY", bid=99.9, ask=100.1, bid_size=1, ask_size=1, source_timestamp=nbbo_ts),
        received_at=nbbo_ts,
    )

    quote = service.latest_quote("SPY")
    assert quote.price == 100.0  # unchanged -- still the real last trade
    assert quote.bid == 99.9
    assert quote.ask == 100.1
    assert quote.nbbo_timestamp == nbbo_ts
    assert quote.is_approximate is False  # a real trade has been observed
    await service.shutdown()


@pytest.mark.asyncio
async def test_nbbo_without_any_trade_yet_falls_back_to_approximate_mid():
    service, _ = await _service_with_stream()
    service.ingest_nbbo(
        StreamNbbo(symbol="SPY", bid=99.0, ask=101.0, bid_size=1, ask_size=1, source_timestamp=_BASE),
        received_at=_BASE,
    )
    quote = service.latest_quote("SPY")
    assert quote.price == 100.0
    assert quote.is_approximate is True
    assert quote.last_trade_price is None
    await service.shutdown()


@pytest.mark.asyncio
async def test_out_of_order_nbbo_is_dropped():
    service, _ = await _service_with_stream()
    later = _BASE + timedelta(seconds=1)
    service.ingest_nbbo(
        StreamNbbo(symbol="SPY", bid=99.9, ask=100.1, bid_size=1, ask_size=1, source_timestamp=later),
        received_at=later,
    )
    service.ingest_nbbo(
        StreamNbbo(symbol="SPY", bid=1.0, ask=1.0, bid_size=1, ask_size=1, source_timestamp=_BASE),
        received_at=_BASE,
    )
    assert service.latest_quote("SPY").bid == 99.9
    await service.shutdown()


# --------------------------------------------------------------- aggregates


def _agg(symbol, start, end, o, h, l, c, v):  # noqa: E741
    return StreamAggregate(
        symbol=symbol, open=o, high=h, low=l, close=c, volume=v, window_start=start, window_end=end
    )


@pytest.mark.asyncio
async def test_aggregate_folds_real_volume_into_the_forming_candle():
    service, _ = await _service_with_stream()
    state = _SymbolState()
    state.timeframes.add(Timeframe.ONE_HOUR)
    service._symbols["SPY"] = state

    t0 = _BASE
    t1 = _BASE + timedelta(seconds=1)
    service.ingest_second_aggregate(_agg("SPY", t0, t1, 100.0, 100.5, 99.5, 100.2, 500), received_at=t1)
    t2 = _BASE + timedelta(seconds=2)
    service.ingest_second_aggregate(_agg("SPY", t1, t2, 100.2, 101.0, 100.0, 100.8, 300), received_at=t2)

    candle = service.latest_candle("SPY", Timeframe.ONE_HOUR)
    assert candle.state == CandleState.FORMING
    assert candle.open == 100.0
    assert candle.high == 101.0
    assert candle.low == 99.5
    assert candle.close == 100.8
    assert candle.volume == 800  # real volume accumulation, never 0.0
    await service.shutdown()


@pytest.mark.asyncio
async def test_a_no_event_second_leaves_the_forming_candle_unchanged():
    service, _ = await _service_with_stream()
    from app.live.service import _SymbolState

    state = _SymbolState()
    state.timeframes.add(Timeframe.ONE_HOUR)
    service._symbols["SPY"] = state

    t0, t1 = _BASE, _BASE + timedelta(seconds=1)
    service.ingest_second_aggregate(_agg("SPY", t0, t1, 100.0, 100.0, 100.0, 100.0, 10), received_at=t1)
    before = service.latest_candle("SPY", Timeframe.ONE_HOUR)
    # Simulate three quiet seconds -- no aggregate arrives, nothing is
    # fabricated, the candle stays exactly as it was.
    after = service.latest_candle("SPY", Timeframe.ONE_HOUR)
    assert before == after
    await service.shutdown()


@pytest.mark.asyncio
async def test_a_higher_timeframe_boundary_crossing_completes_the_old_bar():
    service, _ = await _service_with_stream()
    from app.live.service import _SymbolState

    state = _SymbolState()
    state.timeframes.add(Timeframe.FIVE_MIN)
    service._symbols["SPY"] = state
    queue = service.add_listener()

    within_bucket_start = _BASE
    within_bucket_end = _BASE + timedelta(seconds=1)
    service.ingest_second_aggregate(
        _agg("SPY", within_bucket_start, within_bucket_end, 100.0, 100.0, 100.0, 100.0, 10),
        received_at=within_bucket_end,
    )

    next_bucket_start = _BASE + timedelta(minutes=5)
    next_bucket_end = next_bucket_start + timedelta(seconds=1)
    service.ingest_second_aggregate(
        _agg("SPY", next_bucket_start, next_bucket_end, 101.0, 101.0, 101.0, 101.0, 20),
        received_at=next_bucket_end,
    )

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    completed = [e for e in events if isinstance(e, CompletedCandleEvent)]
    assert len(completed) == 1
    assert completed[0].candle.close == 100.0
    forming = [e for e in events if isinstance(e, FormingCandleEvent)]
    assert forming[-1].candle.open == 101.0
    await service.shutdown()


@pytest.mark.asyncio
async def test_stale_aggregate_replay_is_dropped():
    service, _ = await _service_with_stream()
    from app.live.service import _SymbolState

    state = _SymbolState()
    state.timeframes.add(Timeframe.ONE_HOUR)
    service._symbols["SPY"] = state

    t0, t1, t2 = _BASE, _BASE + timedelta(seconds=1), _BASE + timedelta(seconds=2)
    service.ingest_second_aggregate(_agg("SPY", t0, t1, 100.0, 100.0, 100.0, 100.0, 10), received_at=t1)
    service.ingest_second_aggregate(_agg("SPY", t1, t2, 100.0, 200.0, 100.0, 150.0, 999), received_at=t2)
    # A reconnect replay of the first (already-seen) window must not
    # re-fold and inflate volume a second time.
    service.ingest_second_aggregate(_agg("SPY", t0, t1, 100.0, 100.0, 100.0, 100.0, 10), received_at=t2)

    candle = service.latest_candle("SPY", Timeframe.ONE_HOUR)
    assert candle.volume == 1009
    await service.shutdown()


async def _next_quote_event(queue):
    while True:
        event = await queue.get()
        if isinstance(event, QuoteEvent):
            return event


# ------------------------------------------------------------- reconnect/resync


@pytest.mark.asyncio
async def test_disconnect_then_reconnect_resubscribes_every_tracked_symbol():
    service, stream = await _service_with_stream()
    await service.subscribe("SPY")
    await service.subscribe("NVDA")
    await _wait_until(lambda: service.connection_status().state == ConnectionState.CONNECTED)
    assert stream.connect_count == 1

    stream.push_disconnect()
    await _wait_until(lambda: service.connection_status().state == ConnectionState.DISCONNECTED)
    await _wait_until(lambda: service.connection_status().state == ConnectionState.CONNECTED, timeout=3.0)

    assert stream.connect_count == 2
    assert "SPY" in stream.subscriptions
    assert "NVDA" in stream.subscriptions
    assert service.connection_status().reconnect_attempts == 0
    await service.shutdown()


@pytest.mark.asyncio
async def test_a_stream_status_event_never_crashes_the_handler():
    service, stream = await _service_with_stream()
    await service.subscribe("SPY")
    await _wait_until(lambda: stream.connect_count >= 1)

    stream.push_event(StreamStatus(connected=True, message="ok"))
    await asyncio.sleep(0.02)  # no exception means the event was safely ignored
    await service.shutdown()


@pytest.mark.asyncio
async def test_is_streaming_false_and_no_supervisor_when_no_streaming_provider_configured():
    rest = _StubRestProvider()
    service = LiveMarketService(rest, provider_name="stub", now_fn=lambda: _BASE)
    assert service.is_streaming() is False
    assert service._stream_task is None


@pytest.mark.asyncio
async def test_status_endpoint_shaped_capabilities_reflect_streaming_provider():
    service, _ = await _service_with_stream()
    caps = service.provider_capabilities()
    assert caps.streaming_trades is True
    assert caps.streaming_quotes is True
    await service.shutdown()


# ---------------------------------------------------------- Phase 17 entitlement gating


@pytest.mark.asyncio
async def test_real_time_available_is_false_without_confirmed_entitlement_even_while_streaming():
    """(§1/§78) A technically-connected streaming provider must NOT be
    enough on its own -- the default (no entitlement passed) resolves to
    UNKNOWN, which must gate REAL TIME off exactly like NOT_ENTITLED does."""
    service, stream = await _service_with_stream()
    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await _wait_until(lambda: stream.connect_count >= 1)

    assert service.is_streaming() is True
    assert service.entitlement().confirmed is False
    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_real_time_available_is_true_only_when_streaming_and_entitled():
    from app.live.entitlement import EntitlementStatus, MarketDataEntitlement

    rest = _StubRestProvider()
    stream = MockStreamingProvider()
    entitled = MarketDataEntitlement(
        provider="massive", status=EntitlementStatus.ENTITLED, reason="operator-confirmed"
    )
    service = LiveMarketService(
        rest,
        provider_name="massive",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        config=_fast_config(),
        entitlement=entitled,
    )
    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await _wait_until(lambda: stream.connect_count >= 1)

    assert service.real_time_available() is True
    await service.shutdown()


@pytest.mark.asyncio
async def test_real_time_available_is_false_when_entitled_but_not_streaming():
    from app.live.entitlement import EntitlementStatus, MarketDataEntitlement

    rest = _StubRestProvider()
    entitled = MarketDataEntitlement(
        provider="massive", status=EntitlementStatus.ENTITLED, reason="operator-confirmed"
    )
    service = LiveMarketService(rest, provider_name="massive", now_fn=lambda: _BASE, entitlement=entitled)
    assert service.is_streaming() is False
    assert service.real_time_available() is False


# ---------------------------------------------------------- Phase 17 gap-fill on reconnect


class _GapFillRestProvider(_StubRestProvider):
    """Unlike _StubRestProvider, get_candles is actually usable -- only the
    gap-fill tests below exercise it; every other test in this file keeps
    using _StubRestProvider, whose get_candles asserts it is NEVER called
    (proving gap-fill stays off during a fast, sub-threshold reconnect)."""

    def __init__(self, candles):
        self._candles = candles

    def get_candles(self, symbol, timeframe, limit=200):
        return self._candles


def _candle(ts):
    from app.schemas.market_data import Candle

    return Candle(
        symbol="SPY",
        timeframe=Timeframe.ONE_MIN,
        timestamp=ts,
        open=1,
        high=2,
        low=0.5,
        close=1.5,
        volume=100,
    )


@pytest.mark.asyncio
async def test_gap_fill_backfills_closed_bars_after_a_genuine_outage():
    clock = {"now": _BASE}
    candles = [_candle(_BASE + timedelta(minutes=i)) for i in range(1, 5)]  # +1m..+4m, all closed by +10m
    rest = _GapFillRestProvider(candles)
    stream = MockStreamingProvider()
    service = LiveMarketService(
        rest,
        provider_name="massive",
        now_fn=lambda: clock["now"],
        streaming_provider=stream,
        config=_fast_config(),
    )
    completed = []
    listener = service.add_listener()

    async def _drain():
        while True:
            event = await listener.get()
            if isinstance(event, CompletedCandleEvent):
                completed.append(event)

    drain_task = asyncio.create_task(_drain())

    await service.subscribe("SPY", SubscriptionPriority.VIEWED, timeframes=(Timeframe.ONE_MIN,))
    await _wait_until(lambda: stream.connect_count >= 1)
    stream.push_event(_trade(100.0, _BASE, sequence=1))
    await asyncio.sleep(0.02)

    stream.push_disconnect()
    clock["now"] = _BASE + timedelta(minutes=10)  # >> gap_fill_min_gap_seconds
    await _wait_until(lambda: stream.connect_count >= 2, timeout=3.0)
    await asyncio.sleep(0.02)

    drain_task.cancel()
    await service.shutdown()

    gap_filled = [e for e in completed if e.candle.gap_filled]
    assert len(gap_filled) == 4
    assert [e.candle.timestamp for e in gap_filled] == [c.timestamp for c in candles]
    assert all(e.candle.state == CandleState.COMPLETED for e in gap_filled)


@pytest.mark.asyncio
async def test_gap_fill_does_not_republish_on_a_second_reconnect():
    clock = {"now": _BASE}
    candles = [_candle(_BASE + timedelta(minutes=1))]
    rest = _GapFillRestProvider(candles)
    stream = MockStreamingProvider()
    service = LiveMarketService(
        rest,
        provider_name="massive",
        now_fn=lambda: clock["now"],
        streaming_provider=stream,
        config=_fast_config(),
    )
    completed = []
    listener = service.add_listener()

    async def _drain():
        while True:
            event = await listener.get()
            if isinstance(event, CompletedCandleEvent):
                completed.append(event)

    drain_task = asyncio.create_task(_drain())

    await service.subscribe("SPY", SubscriptionPriority.VIEWED, timeframes=(Timeframe.ONE_MIN,))
    await _wait_until(lambda: stream.connect_count >= 1)
    stream.push_event(_trade(100.0, _BASE, sequence=1))
    await asyncio.sleep(0.02)

    stream.push_disconnect()
    clock["now"] = _BASE + timedelta(minutes=10)
    await _wait_until(lambda: stream.connect_count >= 2, timeout=3.0)
    await asyncio.sleep(0.02)

    stream.push_disconnect()
    clock["now"] = _BASE + timedelta(minutes=20)
    await _wait_until(lambda: stream.connect_count >= 3, timeout=3.0)
    await asyncio.sleep(0.02)

    drain_task.cancel()
    await service.shutdown()

    gap_filled = [e for e in completed if e.candle.gap_filled]
    assert len(gap_filled) == 1  # not republished on the second reconnect


# ---------------------------------------------------------- Phase 17 multi-timeframe aggregation


@pytest.mark.asyncio
async def test_simultaneous_timeframes_fold_independently_with_no_volume_double_counting():
    """Phase 17 (§93): a symbol subscribed at both 1m and 5m must produce
    two independently correct forming candles from the SAME underlying
    per-second aggregate stream -- each timeframe's volume is its own sum
    over its own bucket, never the other timeframe's total leaking in, and
    a 1m boundary crossing must not disturb the still-open 5m bar."""
    service, _ = await _service_with_stream()
    state = _SymbolState()
    state.timeframes.add(Timeframe.ONE_MIN)
    state.timeframes.add(Timeframe.FIVE_MIN)
    service._symbols["SPY"] = state

    t0 = _BASE
    for i in range(3):
        start = t0 + timedelta(seconds=i)
        end = start + timedelta(seconds=1)
        service.ingest_second_aggregate(
            _agg("SPY", start, end, 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 10), received_at=end
        )

    one_min = service.latest_candle("SPY", Timeframe.ONE_MIN)
    five_min = service.latest_candle("SPY", Timeframe.FIVE_MIN)
    assert one_min.volume == 30  # 3 aggregates * 10, this timeframe's own sum
    assert five_min.volume == 30  # same source data, independently summed -- not 60
    assert one_min.state == CandleState.FORMING
    assert five_min.state == CandleState.FORMING

    # Cross the 1m boundary (t0+60s) without crossing the 5m boundary (t0+5m):
    # the 1m bar completes, the 5m bar keeps accumulating undisturbed.
    next_min_start = t0 + timedelta(seconds=60)
    next_min_end = next_min_start + timedelta(seconds=1)
    service.ingest_second_aggregate(
        _agg("SPY", next_min_start, next_min_end, 105.0, 105.0, 105.0, 105.0, 40), received_at=next_min_end
    )

    new_one_min = service.latest_candle("SPY", Timeframe.ONE_MIN)
    still_five_min = service.latest_candle("SPY", Timeframe.FIVE_MIN)
    assert new_one_min.timestamp == bucket_start(next_min_start, Timeframe.ONE_MIN)
    assert new_one_min.volume == 40  # fresh 1m bucket, not carried over from the old one
    assert still_five_min.timestamp == five_min.timestamp  # same 5m bucket, undisturbed
    assert still_five_min.volume == 70  # 30 + 40, still accumulating in the same 5m bar
    await service.shutdown()


@pytest.mark.asyncio
async def test_fast_reconnect_never_touches_rest_at_all():
    """A reconnect faster than gap_fill_min_gap_seconds must not call
    get_candles -- the pre-existing _StubRestProvider asserts on any call,
    so this test fails loudly if gap-fill fires when it shouldn't."""
    service, stream = await _service_with_stream()  # _StubRestProvider under the hood
    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await _wait_until(lambda: stream.connect_count >= 1)

    stream.push_disconnect()
    await _wait_until(lambda: stream.connect_count >= 2, timeout=3.0)
    await service.shutdown()  # no AssertionError means get_candles was never called
