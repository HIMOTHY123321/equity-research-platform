"""Phase 12.1 (#G/#H): RecomputationEngine -- proves the event-driven
graph's central invariant directly: only a CompletedCandleEvent ever
triggers authoritative recomputation. A quote tick or a forming-candle
price move must never reach build_market_snapshot.
"""

from __future__ import annotations

from app.live.config import FreshnessState, LiveSessionState
from app.live.events import CompletedCandleEvent, ConnectionStatusEvent, FormingCandleEvent, QuoteEvent
from app.live.recompute import RecomputationEngine
from app.live.schemas import (
    CandleState,
    ConnectionState,
    ConnectionStatus,
    FreshnessInfo,
    LiveCandle,
    LiveQuote,
)
from app.market_data.cache import InMemoryCache
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider

_AS_OF = SPY_1H[-1].timestamp


def _freshness() -> FreshnessInfo:
    return FreshnessInfo(
        source_timestamp=_AS_OF,
        received_at=_AS_OF,
        age_seconds=0.5,
        provider="fixture",
        market_session=LiveSessionState.REGULAR,
        freshness_state=FreshnessState.LIVE,
    )


def _engine() -> RecomputationEngine:
    return RecomputationEngine(
        live_service=None,  # not needed for handle_event's direct-call tests
        market_provider=FakeMarketDataProvider(),
        cache=InMemoryCache(),
        now_fn=lambda: _AS_OF,
    )


def _completed_candle_event() -> CompletedCandleEvent:
    candle = LiveCandle(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR.value,
        timestamp=_AS_OF,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=0.0,
        state=CandleState.COMPLETED,
        freshness=_freshness(),
    )
    return CompletedCandleEvent(symbol="SPY", candle=candle)


def test_completed_candle_event_triggers_a_real_recompute():
    engine = _engine()
    assert engine.latest_snapshot("SPY", Timeframe.ONE_HOUR) is None
    result = engine.handle_event(_completed_candle_event())
    assert result is not None
    snapshot = engine.latest_snapshot("SPY", Timeframe.ONE_HOUR)
    assert snapshot is not None
    assert snapshot.setup_snapshot is not None  # a real, fully-built MarketSnapshot


def test_quote_event_never_triggers_recomputation():
    engine = _engine()
    quote = LiveQuote(
        symbol="SPY", price=1.0, bid=1.0, ask=1.0, spread=0.0, is_approximate=True, freshness=_freshness()
    )
    result = engine.handle_event(QuoteEvent(symbol="SPY", quote=quote))
    assert result is None
    assert engine.latest_snapshot("SPY", Timeframe.ONE_HOUR) is None


def test_forming_candle_event_never_triggers_recomputation():
    engine = _engine()
    forming = LiveCandle(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR.value,
        timestamp=_AS_OF,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=0.0,
        state=CandleState.FORMING,
        freshness=_freshness(),
    )
    result = engine.handle_event(FormingCandleEvent(symbol="SPY", candle=forming))
    assert result is None
    assert engine.latest_snapshot("SPY", Timeframe.ONE_HOUR) is None


def test_connection_status_event_never_triggers_recomputation():
    engine = _engine()
    status = ConnectionStatus(
        state=ConnectionState.CONNECTED, last_message_at=_AS_OF, reconnect_attempts=0, subscribed_symbols=[]
    )
    result = engine.handle_event(ConnectionStatusEvent(status=status))
    assert result is None


def test_recompute_invalidates_the_stale_candle_cache_prefix():
    cache = InMemoryCache()
    cache.set(f"candles:SPY:{Timeframe.ONE_HOUR.value}:200", ["stale"], ttl_seconds=999)
    engine = RecomputationEngine(
        live_service=None, market_provider=FakeMarketDataProvider(), cache=cache, now_fn=lambda: _AS_OF
    )
    engine.handle_event(_completed_candle_event())
    assert cache.get(f"candles:SPY:{Timeframe.ONE_HOUR.value}:200") is None


def test_listeners_receive_a_snapshot_refreshed_event():
    engine = _engine()
    queue = engine.add_listener()
    engine.handle_event(_completed_candle_event())
    refreshed = queue.get_nowait()
    assert refreshed.symbol == "SPY"
    assert refreshed.timeframe == Timeframe.ONE_HOUR


def test_different_symbols_and_timeframes_are_tracked_independently():
    engine = _engine()
    engine.handle_event(_completed_candle_event())
    assert engine.latest_snapshot("SPY", Timeframe.ONE_HOUR) is not None
    assert engine.latest_snapshot("SPY", Timeframe.ONE_DAY) is None
    assert engine.latest_snapshot("AAPL", Timeframe.ONE_HOUR) is None
