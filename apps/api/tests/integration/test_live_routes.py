"""Integration tests for Phase 12.1's WS /api/live/stream and GET
/api/live/status -- the real FastAPI app, real lifespan (so the actual
process-wide LiveMarketService/RecomputationEngine/ForecastMonitor/
NewsMonitor singletons run), with a fast, fully-controllable fake
MarketDataProvider injected via app.dependency_overrides (lifespan itself
respects overrides -- see app.main.lifespan).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_provider, get_news_provider, get_session_factory
from app.live.config import LiveConfig
from app.main import app
from app.market_data.capabilities import ProviderCapabilities
from app.market_data.exceptions import ProviderError
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote

# Phase 14.1: these fixtures trigger the REAL app lifespan, which now
# also starts MonitoringService -- without an isolated session factory it
# would run real per-symbol setup-detection scans against the shared
# on-disk dev database on every single test below, racing concurrent
# `checkfirst=True` table creation across the whole file (the root cause
# of a full-suite hang found during Phase 14.1 validation). An isolated
# on-disk (not `:memory:`) DB per test: RecomputationEngine/ForecastMonitor/
# NewsMonitor/MonitoringService each fire off their own `asyncio.to_thread`
# scan concurrently at lifespan startup, and a single shared `:memory:`
# connection (StaticPool) is not safe under genuinely concurrent access
# from multiple OS threads the way a real per-connection file DB is. The
# `file_session_factory` fixture (tests/conftest.py) also ensures the
# Engine it creates is disposed at teardown -- an un-disposed file-based
# Engine's connection pool/file handle otherwise stays alive for the rest
# of the pytest process (see FileSessionFactory's docstring).

_BASE = datetime.now(timezone.utc)

_FAST_CONFIG = LiveConfig(
    target_interval_seconds=0.02,
    heartbeat_interval_seconds=0.1,
    reconnect_initial_backoff_seconds=0.02,
    reconnect_max_backoff_seconds=0.05,
    forecast_monitor_interval_seconds=3600,  # not exercised by these tests
    news_monitor_interval_seconds=3600,
)


class _QueueProvider(MarketDataProvider):
    """Returns a fresh, monotonically-timestamped quote every call --
    fast and fully deterministic, no real network I/O."""

    def __init__(self):
        self._tick = 0
        self.raise_next = False

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            real_time_quotes=True,
            streaming_quotes=False,
            streaming_trades=False,
            streaming_bars=False,
            streaming_news=False,
            historical_intraday=True,
            quote_delay_seconds=0.05,
            min_poll_interval_seconds=0.02,
        )

    def get_candles(self, symbol, timeframe, limit=200):
        return []

    def get_latest_quote(self, symbol):
        if self.raise_next:
            self.raise_next = False
            raise ProviderError("simulated outage")
        self._tick += 1
        ts = _BASE + timedelta(milliseconds=self._tick)
        price = 100.0 + self._tick
        return Quote(
            symbol=symbol,
            timestamp=ts,
            session=MarketSession.REGULAR,
            bid_price=price,
            bid_size=0.0,
            ask_price=price,
            ask_size=0.0,
            is_approximate=False,
        )

    def get_previous_close(self, symbol):
        return PreviousClose(symbol=symbol, trading_date=_BASE.date(), close=100.0, volume=1_000_000)


class _StaticProvider(MarketDataProvider):
    """Returns the exact same quote every call -- reproduces the real
    yfinance-honest-timestamp scenario (Hardening pass): the underlying
    market data genuinely hasn't changed, so every poll is correctly
    deduplicated and no new QuoteEvent is ever published to the bus."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            real_time_quotes=True,
            streaming_quotes=False,
            streaming_trades=False,
            streaming_bars=False,
            streaming_news=False,
            historical_intraday=True,
            quote_delay_seconds=0.05,
            min_poll_interval_seconds=0.02,
        )

    def get_candles(self, symbol, timeframe, limit=200):
        return []

    def get_latest_quote(self, symbol):
        return Quote(
            symbol=symbol,
            timestamp=_BASE,
            session=MarketSession.REGULAR,
            bid_price=100.0,
            bid_size=0.0,
            ask_price=100.0,
            ask_size=0.0,
            is_approximate=False,
        )

    def get_previous_close(self, symbol):
        return PreviousClose(symbol=symbol, trading_date=_BASE.date(), close=100.0, volume=1_000_000)


@pytest.fixture
def client(file_session_factory):
    provider = _QueueProvider()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            yield test_client, provider
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "live_config"):
            del app.state.live_config


@pytest.fixture
def static_client(file_session_factory):
    provider = _StaticProvider()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            yield test_client, provider
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "live_config"):
            del app.state.live_config


# Phase 14.1: MonitoringService now runs for real in every one of these
# lifespan-triggering tests and broadcasts `monitor_status` (and
# occasionally `decision_state_change`) frames to every connection
# regardless of what that connection subscribed to (§19 -- intentional,
# see app.api.routes.live._UNIVERSE_WIDE_FRAME_TYPES). `_FAST_CONFIG`'s
# 0.1s heartbeat also means a `heartbeat` frame can land in the same small
# window. Tests below that assert on a specific expected frame type must
# tolerate any of these interleaving at any point, exactly as a real
# client must -- `_receive_until` skips them by default; the one test that
# specifically checks for heartbeats opts back in.
_UNIVERSE_WIDE_TYPES = {"monitor_status", "decision_state_change"}
_ALL_NOISE_TYPES = _UNIVERSE_WIDE_TYPES | {"heartbeat"}


def _receive_until(ws, count: int, max_frames: int = 60, skip: frozenset = _ALL_NOISE_TYPES) -> list[dict]:
    """Collects `count` frames, skipping (not counting) any frame type in
    `skip` that interleaves -- by default every noise type (monitor_status/
    decision_state_change/heartbeat); pass a narrower `skip` set for a test
    that specifically cares about one of those."""
    collected: list[dict] = []
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] in skip:
            continue
        collected.append(frame)
        if len(collected) >= count:
            break
    return collected


def _receive_next_meaningful(ws, max_frames: int = 40) -> dict:
    return _receive_until(ws, count=1, max_frames=max_frames)[0]


def test_status_endpoint_reports_provider_capabilities(client):
    test_client, _provider = client
    response = test_client.get("/api/live/status")
    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"]["streaming_quotes"] is False
    assert "connection_status" in body


def test_subscribing_receives_a_connection_status_then_a_quote(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        ws.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        frames = _receive_until(ws, count=3)
        types_seen = {f["type"] for f in frames}
        assert "connection_status" in types_seen
        assert "quote" in types_seen
        quote_frame = next(f for f in frames if f["type"] == "quote")
        assert quote_frame["symbol"] == "SPY"
        assert quote_frame["quote"]["price"] > 0


def test_a_forming_candle_frame_follows_the_quote(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        ws.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        frames = _receive_until(ws, count=4)
        assert any(f["type"] == "forming_candle" for f in frames)


def test_a_new_connection_receives_the_current_connection_status_immediately(client):
    # Regression guard: connection_status events are only published on a
    # *transition* (LiveMarketService._set_connection_state) -- a brand-new
    # connection made while the service is already CONNECTED from an
    # earlier subscriber must still learn the current state right away,
    # not sit on a client-side default of DISCONNECTED forever.
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws1:
        ws1.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        first = ws1.receive_json()
        assert first["type"] == "connection_status"
        # Wait for the underlying poll loop to actually succeed once, so
        # the service's own connection_state has genuinely transitioned to
        # CONNECTED before the second connection opens.
        for _ in range(5):
            frame = ws1.receive_json()
            if frame["type"] == "connection_status" and frame["status"]["state"] == "connected":
                break

        with test_client.websocket_connect("/api/live/stream") as ws2:
            snapshot = ws2.receive_json()
            assert snapshot["type"] == "connection_status"
            assert snapshot["status"]["state"] == "connected"


def test_a_new_connection_gets_the_already_known_quote_even_with_no_new_data(static_client):
    # Hardening pass regression: found via manual browser testing after
    # fixing yfinance's fabricated quote timestamp (see
    # YFinanceMarketDataProvider.get_latest_quote) -- once duplicate
    # (unchanged) polls are correctly deduplicated and stop publishing new
    # QuoteEvents, a *second* connection subscribing to an already-tracked
    # symbol must still see the already-known quote immediately, not sit on
    # "no quote yet" until the underlying data source happens to change
    # (which for yfinance can be minutes away).
    test_client, _provider = static_client
    with test_client.websocket_connect("/api/live/stream") as ws1:
        ws1.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        frames = _receive_until(ws1, count=3)
        assert any(f["type"] == "quote" for f in frames)

        with test_client.websocket_connect("/api/live/stream") as ws2:
            ws2.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
            second_connection_frames = _receive_until(ws2, count=2)
            quote_frame = next(f for f in second_connection_frames if f["type"] == "quote")
            assert quote_frame["symbol"] == "SPY"
            assert quote_frame["quote"]["price"] == 100.0


def test_two_connections_to_the_same_symbol_share_one_poll_loop(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws1:
        ws1.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        ws1.receive_json()
        with test_client.websocket_connect("/api/live/stream") as ws2:
            ws2.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
            ws2.receive_json()
            assert len(app.state.live_service._tasks) == 1


def test_unrecognized_action_returns_an_error_frame_not_a_crash(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        _receive_next_meaningful(ws)  # initial connection_status snapshot
        ws.send_json({"action": "bogus"})
        frame = _receive_next_meaningful(ws)
        assert frame["type"] == "error"


def test_malformed_subscribe_message_returns_an_error_frame(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        _receive_next_meaningful(ws)  # initial connection_status snapshot
        ws.send_json({"action": "subscribe"})  # missing required "symbol"
        frame = _receive_next_meaningful(ws)
        assert frame["type"] == "error"


def test_heartbeat_frames_arrive_on_the_configured_interval(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        frames = _receive_until(ws, count=3, skip=_UNIVERSE_WIDE_TYPES)
        assert any(f["type"] == "heartbeat" for f in frames)


def test_disconnect_cleans_up_the_subscription(client):
    test_client, _provider = client
    with test_client.websocket_connect("/api/live/stream") as ws:
        ws.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        ws.receive_json()
    status = test_client.get("/api/live/status").json()
    assert "SPY" not in status["connection_status"]["subscribed_symbols"]
