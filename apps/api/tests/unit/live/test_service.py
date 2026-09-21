"""Phase 12.1 (#A/#G/#R/#Q): LiveMarketService -- the centralized
subscription/cache layer. `ingest_quote` is tested directly (synchronous,
deterministic) for the data-correctness guarantees; `subscribe`/
`unsubscribe`/the poll loop are tested with real asyncio to prove the
scheduling/lifecycle contract.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.live.config import DEFAULT_LIVE_CONFIG, FreshnessState, SubscriptionPriority
from app.live.events import CompletedCandleEvent, ConnectionStatusEvent, FormingCandleEvent, QuoteEvent
from app.live.schemas import CandleState, ConnectionState
from app.live.service import LiveMarketService, _SymbolState
from app.market_data.capabilities import ProviderCapabilities
from app.market_data.exceptions import ProviderError
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote, Timeframe

_BASE = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)  # 09:30 EDT -- regular open


def _quote(price: float, at: datetime, is_approximate: bool = True) -> Quote:
    return Quote(
        symbol="SPY",
        timestamp=at,
        session=MarketSession.REGULAR,
        bid_price=price,
        bid_size=0.0,
        ask_price=price,
        ask_size=0.0,
        is_approximate=is_approximate,
    )


class _StubProvider(MarketDataProvider):
    """Deterministic, fully controllable stand-in -- returns queued quotes
    (or raises queued exceptions) one at a time per get_latest_quote call."""

    def __init__(self, capabilities: ProviderCapabilities):
        self._capabilities = capabilities
        self.quotes: list[Quote | Exception] = []
        self.previous_close = 100.0

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def get_candles(self, symbol, timeframe, limit=200):
        return []

    def get_latest_quote(self, symbol):
        if not self.quotes:
            raise ProviderError("no more stubbed quotes")
        item = self.quotes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get_previous_close(self, symbol):
        return PreviousClose(
            symbol=symbol, trading_date=_BASE.date(), close=self.previous_close, volume=1_000_000
        )


_FAST_CAPS = ProviderCapabilities(
    real_time_quotes=True,
    streaming_quotes=False,
    streaming_trades=False,
    streaming_bars=False,
    streaming_news=False,
    historical_intraday=True,
    quote_delay_seconds=0.0,
    min_poll_interval_seconds=0.01,
)


def _service(provider=None) -> LiveMarketService:
    provider = provider or _StubProvider(_FAST_CAPS)
    return LiveMarketService(provider, provider_name="stub", now_fn=lambda: _BASE)


# --------------------------------------------------------------- ingest_quote


def test_ingest_quote_publishes_a_quote_event():
    service = _service()
    queue = service.add_listener()
    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    event = queue.get_nowait()
    assert isinstance(event, QuoteEvent)
    assert event.quote.price == 100.0


def test_latest_quote_reflects_the_ingested_value():
    service = _service()
    service.ingest_quote("SPY", _quote(101.5, _BASE), received_at=_BASE)
    quote = service.latest_quote("SPY")
    assert quote is not None
    assert quote.price == 101.5


def test_duplicate_quote_timestamp_is_dropped():
    service = _service()
    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    service.ingest_quote("SPY", _quote(999.0, _BASE), received_at=_BASE)  # same timestamp, different price
    assert service.latest_quote("SPY").price == 100.0


def test_out_of_order_older_quote_never_overwrites_newer_state():
    service = _service()
    later = _BASE + timedelta(seconds=5)
    service.ingest_quote("SPY", _quote(100.0, later), received_at=later)
    earlier = _BASE  # arrives late, timestamped before what we already have
    service.ingest_quote("SPY", _quote(50.0, earlier), received_at=later + timedelta(seconds=1))
    assert service.latest_quote("SPY").price == 100.0


def test_strictly_newer_quote_is_accepted():
    service = _service()
    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    later = _BASE + timedelta(seconds=1)
    service.ingest_quote("SPY", _quote(105.0, later), received_at=later)
    assert service.latest_quote("SPY").price == 105.0


def test_stale_quote_is_classified_as_stale_not_live():
    service = _service()
    old_source = _BASE
    received_much_later = _BASE + timedelta(seconds=500)
    service.ingest_quote("SPY", _quote(100.0, old_source), received_at=received_much_later)
    assert service.latest_quote("SPY").freshness.freshness_state == FreshnessState.STALE


def test_fresh_quote_is_classified_as_live():
    service = _service()
    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE + timedelta(milliseconds=200))
    assert service.latest_quote("SPY").freshness.freshness_state == FreshnessState.LIVE


def test_percent_change_uses_the_fetched_previous_close():
    service = _service()
    service._symbols["SPY"] = _SymbolState(previous_close=100.0)
    service.ingest_quote("SPY", _quote(110.0, _BASE), received_at=_BASE)
    assert service.latest_quote("SPY").percent_change == pytest.approx(10.0)


def test_no_previous_close_leaves_percent_change_honestly_unavailable():
    service = _service()
    service.ingest_quote("SPY", _quote(110.0, _BASE), received_at=_BASE)
    assert service.latest_quote("SPY").percent_change is None


# ----------------------------------------------------- forming/completed candle


def test_forming_candle_updates_within_the_same_bucket():
    service = _service()
    service._symbols["SPY"] = _SymbolState(timeframes={Timeframe.ONE_HOUR})
    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    within_bucket = _BASE + timedelta(minutes=10)
    service.ingest_quote("SPY", _quote(105.0, within_bucket), received_at=within_bucket)
    candle = service.latest_candle("SPY", Timeframe.ONE_HOUR)
    assert candle is not None
    assert candle.state == CandleState.FORMING
    assert candle.open == 100.0
    assert candle.high == 105.0
    assert candle.close == 105.0


def test_crossing_a_boundary_completes_the_old_bucket_and_starts_a_new_one():
    service = _service()
    service._symbols["SPY"] = _SymbolState(timeframes={Timeframe.ONE_HOUR})
    queue = service.add_listener()

    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    next_hour = _BASE + timedelta(hours=1, minutes=5)
    service.ingest_quote("SPY", _quote(120.0, next_hour), received_at=next_hour)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    completed = [e for e in events if isinstance(e, CompletedCandleEvent)]
    forming = [e for e in events if isinstance(e, FormingCandleEvent)]
    assert len(completed) == 1
    assert completed[0].candle.close == 100.0
    assert completed[0].candle.state == CandleState.COMPLETED
    # A brand-new forming candle starts for the new bucket.
    assert forming[-1].candle.open == 120.0
    assert forming[-1].candle.state == CandleState.FORMING


def test_forming_candle_price_move_never_emits_a_completed_candle_event_within_the_same_bucket():
    service = _service()
    service._symbols["SPY"] = _SymbolState(timeframes={Timeframe.ONE_HOUR})
    queue = service.add_listener()

    service.ingest_quote("SPY", _quote(100.0, _BASE), received_at=_BASE)
    service.ingest_quote("SPY", _quote(999.0, _BASE + timedelta(minutes=1)), received_at=_BASE)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert not any(isinstance(e, CompletedCandleEvent) for e in events)


# ------------------------------------------------------- subscribe/unsubscribe


@pytest.mark.asyncio
async def test_subscribe_starts_exactly_one_poll_task_per_symbol():
    provider = _StubProvider(_FAST_CAPS)
    provider.quotes = [_quote(100.0, _BASE)]
    service = LiveMarketService(provider, provider_name="stub", now_fn=lambda: _BASE)

    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await service.subscribe("SPY", SubscriptionPriority.WATCHLIST)  # a second subscriber, same symbol
    assert len(service._tasks) == 1
    await service.shutdown()


@pytest.mark.asyncio
async def test_unsubscribing_all_refs_cancels_the_poll_task():
    provider = _StubProvider(_FAST_CAPS)
    service = LiveMarketService(provider, provider_name="stub", now_fn=lambda: _BASE)

    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await service.subscribe("SPY", SubscriptionPriority.WATCHLIST)
    await service.unsubscribe("SPY", SubscriptionPriority.VIEWED)
    assert "SPY" in service._tasks  # still one active subscriber
    await service.unsubscribe("SPY", SubscriptionPriority.WATCHLIST)
    assert "SPY" not in service._tasks
    assert "SPY" not in service._symbols


@pytest.mark.asyncio
async def test_resubscribing_after_a_full_unsubscribe_starts_a_fresh_poll_loop():
    provider = _StubProvider(_FAST_CAPS)
    service = LiveMarketService(provider, provider_name="stub", now_fn=lambda: _BASE)

    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    await service.unsubscribe("SPY", SubscriptionPriority.VIEWED)
    assert "SPY" not in service._tasks

    await service.subscribe("SPY", SubscriptionPriority.VIEWED)
    assert "SPY" in service._tasks
    assert not service._tasks["SPY"].done()

    await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cleans_up_every_task_and_symbol():
    provider = _StubProvider(_FAST_CAPS)
    service = LiveMarketService(provider, provider_name="stub", now_fn=lambda: _BASE)
    await service.subscribe("SPY")
    await service.subscribe("AAPL")
    await service.shutdown()
    assert service._tasks == {}
    assert service._symbols == {}


@pytest.mark.asyncio
async def test_poll_failure_then_recovery_transitions_connection_state():
    provider = _StubProvider(_FAST_CAPS)
    provider.quotes = [ProviderError("boom"), _quote(100.0, _BASE)]
    service = LiveMarketService(
        provider,
        provider_name="stub",
        now_fn=lambda: _BASE,
        config=DEFAULT_LIVE_CONFIG.__class__(
            reconnect_initial_backoff_seconds=0.01, reconnect_max_backoff_seconds=0.02
        ),
    )
    queue = service.add_listener()
    await service.subscribe("SPY")

    for _ in range(50):
        if service.connection_status().state == ConnectionState.CONNECTED:
            break
        await asyncio.sleep(0.01)

    assert service.connection_status().state == ConnectionState.CONNECTED
    assert service.connection_status().reconnect_attempts == 0

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    connection_events = [e for e in events if isinstance(e, ConnectionStatusEvent)]
    states_seen = [e.status.state for e in connection_events]
    assert ConnectionState.DISCONNECTED in states_seen
    assert states_seen[-1] == ConnectionState.CONNECTED

    await service.shutdown()
