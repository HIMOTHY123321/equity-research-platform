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
from app.database.session import get_db
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


def _isolated_get_db_override(session_factory):
    """Phase 16: `/api/auth/signup` (used by `_authed_ws_url` below) goes
    through `get_db`, which is otherwise never overridden in this file --
    without this, a websocket-auth test would silently hit the real
    on-disk dev database via the default `get_db`, exactly the risk
    Phase 14.1's FileSessionFactory fix already exists to eliminate for
    every other DB-touching dependency here."""

    def _get_db_override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return _get_db_override


@pytest.fixture
def client(file_session_factory):
    provider = _QueueProvider()
    # Phase 16.1: `get_db`'s own session_factory is captured here (not
    # re-derived inside _isolated_get_db_override) so tests can bind a
    # session to the EXACT SAME engine every HTTP route/WebSocket-auth
    # check uses -- see `_db_session_factory` below and
    # test_ws_alert_event_frame_only_reaches_a_connection_whose_user_
    # monitors_that_symbol for why this matters (a second, disconnected
    # temp-file engine would silently write to a DB no route ever reads).
    db_session_factory = file_session_factory()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.dependency_overrides[get_db] = _isolated_get_db_override(db_session_factory)
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            test_client.db_session_factory = db_session_factory
            yield test_client, provider
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "live_config"):
            del app.state.live_config


@pytest.fixture
def static_client(file_session_factory):
    provider = _StaticProvider()
    db_session_factory = file_session_factory()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.dependency_overrides[get_db] = _isolated_get_db_override(db_session_factory)
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            test_client.db_session_factory = db_session_factory
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


def _receive_frame_of_type(ws, frame_type: str, max_frames: int = 60) -> "dict | None":
    """Reads frames until one of exactly `frame_type` arrives (returned),
    or `max_frames` is exhausted (returns None) -- unlike `_receive_until`,
    every OTHER frame type is skipped, including ones `_ALL_NOISE_TYPES`
    doesn't cover (connection_status, quote, etc.), so a frame this test
    doesn't care about can never satisfy the wait early."""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == frame_type:
            return frame
    return None


_ws_user_counter = 0


def _authed_ws_url(
    test_client: TestClient, path: str = "/api/live/stream", *, email: str | None = None
) -> str:
    """Phase 16.1 (§2): /api/live/stream now authenticates off the SAME
    HttpOnly session cookie every HTTP route uses -- never a query-string
    token. Signs up a fresh test user (against the same isolated per-test
    DB `test_client` already points at); TestClient persists the resulting
    Set-Cookie on its own cookie jar, and `websocket_connect` sends
    whatever is currently in that jar at connect time -- so calling this
    again with a different user before opening a NEW connection correctly
    switches which user that new connection authenticates as, without
    affecting any connection already open (the cookie is only read at
    handshake time)."""
    global _ws_user_counter
    _ws_user_counter += 1
    if email is None:
        email = f"ws-test-{_ws_user_counter}@example.com"
    test_client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    return path


def test_status_endpoint_reports_provider_capabilities(client):
    test_client, _provider = client
    response = test_client.get("/api/live/status")
    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"]["streaming_quotes"] is False
    assert "connection_status" in body


def test_websocket_connect_without_a_session_cookie_is_rejected(client):
    from starlette.websockets import WebSocketDisconnect

    test_client, _provider = client
    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live/stream"):
            pass


def test_websocket_connect_with_a_garbage_session_cookie_is_rejected(client):
    from starlette.websockets import WebSocketDisconnect

    test_client, _provider = client
    test_client.cookies.set("amd_session", "not-a-real-token")
    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live/stream"):
            pass


def test_websocket_connect_with_a_query_string_token_is_rejected(client):
    """Phase 16.1 (§2): the old ?token= transport is gone entirely -- a
    query-string token must never authenticate the handshake, even a
    genuinely valid one, since it would otherwise leak into server logs
    and browser history."""
    from starlette.websockets import WebSocketDisconnect

    test_client, _provider = client
    signup = test_client.post(
        "/api/auth/signup", json={"email": "ws-querystring@example.com", "password": "hunter2hunter2"}
    )
    token = signup.json()["access_token"]
    test_client.cookies.clear()
    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect(f"/api/live/stream?token={token}"):
            pass


def test_subscribing_receives_a_connection_status_then_a_quote(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
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
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
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
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws1:
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

        with test_client.websocket_connect(_authed_ws_url(test_client)) as ws2:
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
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws1:
        ws1.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        frames = _receive_until(ws1, count=3)
        assert any(f["type"] == "quote" for f in frames)

        with test_client.websocket_connect(_authed_ws_url(test_client)) as ws2:
            ws2.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
            second_connection_frames = _receive_until(ws2, count=2)
            quote_frame = next(f for f in second_connection_frames if f["type"] == "quote")
            assert quote_frame["symbol"] == "SPY"
            assert quote_frame["quote"]["price"] == 100.0


def test_two_connections_to_the_same_symbol_share_one_poll_loop(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws1:
        ws1.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        ws1.receive_json()
        with test_client.websocket_connect(_authed_ws_url(test_client)) as ws2:
            ws2.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
            ws2.receive_json()
            assert len(app.state.live_service._tasks) == 1


def test_unrecognized_action_returns_an_error_frame_not_a_crash(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
        _receive_next_meaningful(ws)  # initial connection_status snapshot
        ws.send_json({"action": "bogus"})
        frame = _receive_next_meaningful(ws)
        assert frame["type"] == "error"


def test_malformed_subscribe_message_returns_an_error_frame(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
        _receive_next_meaningful(ws)  # initial connection_status snapshot
        ws.send_json({"action": "subscribe"})  # missing required "symbol"
        frame = _receive_next_meaningful(ws)
        assert frame["type"] == "error"


def test_heartbeat_frames_arrive_on_the_configured_interval(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
        frames = _receive_until(ws, count=3, skip=_UNIVERSE_WIDE_TYPES)
        assert any(f["type"] == "heartbeat" for f in frames)


def test_disconnect_cleans_up_the_subscription(client):
    test_client, _provider = client
    with test_client.websocket_connect(_authed_ws_url(test_client)) as ws:
        ws.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1h"]})
        ws.receive_json()
    status = test_client.get("/api/live/status").json()
    assert "SPY" not in status["connection_status"]["subscribed_symbols"]


# --------------------------------------------------------------- Phase 16.1
# WebSocket per-user isolation (§7): alert_event/decision_state_change/
# monitor_status frames must be filtered per-connection to the connected
# user's own deliveries/monitored symbols -- never broadcast to every
# connection regardless of subscription, as Phase 16 did.


def _emit_alert_via_service(db_session_factory, *, symbol: str, identity: str) -> str:
    """`db_session_factory` must be the SAME sessionmaker the app's `get_db`
    override is bound to (`test_client.db_session_factory`) -- a fresh
    `file_session_factory()` call mints a disconnected second temp-file
    engine that no route or WebSocket-auth check ever reads from."""
    from datetime import datetime, timezone

    from app.alerts.repository import SqlAlchemyAlertRepository
    from app.alerts.schemas import AlertOrigin, AlertType
    from app.alerts.service import AlertService

    session = db_session_factory()
    try:
        repository = SqlAlchemyAlertRepository(session)
        service = AlertService(repository, event_bus=app.state.alert_event_bus)
        event = service.emit_condition_alert(
            symbol=symbol,
            alert_type=AlertType.DATA_STALE,
            identity=identity,
            title="Data stale",
            summary=f"{symbol} market data has not refreshed within the expected window.",
            source_timestamp=datetime.now(timezone.utc),
            origin=AlertOrigin.DEV_FIXTURE,
        )
        assert event is not None
        return event.alert_id
    finally:
        session.close()


def test_ws_alert_event_frame_only_reaches_a_connection_whose_user_monitors_that_symbol(client):
    test_client, _provider = client

    with test_client.websocket_connect(
        _authed_ws_url(test_client, email="ws-iso-a@example.com")
    ) as ws_a:
        test_client.post("/api/monitoring/NVDA")  # cookie jar currently holds user A's session

        with test_client.websocket_connect(
            _authed_ws_url(test_client, email="ws-iso-b@example.com")
        ) as ws_b:
            # B deliberately never subscribes to NVDA monitoring.
            _emit_alert_via_service(test_client.db_session_factory, symbol="NVDA", identity="ws-isolation-1")

            frame_a = _receive_frame_of_type(ws_a, "alert_event")
            assert frame_a is not None
            assert frame_a["symbol"] == "NVDA"

            # B must NOT receive it -- bounded drain (heartbeats keep
            # frames flowing every 0.1s in _FAST_CONFIG) confirms no
            # alert_event ever arrives for B, rather than blocking forever.
            assert _receive_frame_of_type(ws_b, "alert_event", max_frames=20) is None


def test_user_monitors_symbol_predicate_is_isolated_per_user(client):
    """Phase 16.1 (§7): `decision_state_change`/`monitor_status` frames are
    filtered in `_writer()` through the exact same
    `app.api.routes.live._user_monitors_symbol` predicate the
    alert_event-isolation test above already proves is correctly wired
    into the live WebSocket write path -- this test proves the predicate
    itself is correct and per-user in isolation, directly against the same
    DB engine `get_db` uses, without a second real WebSocket round trip
    (which would require emitting a MonitorStatusEvent from off the app's
    event-loop thread -- a genuine cross-thread asyncio.Queue hazard,
    deliberately avoided here rather than papered over with a sleep)."""
    from types import SimpleNamespace
    from uuid import UUID

    from app.api.routes.live import _user_monitors_symbol

    test_client, _provider = client
    fake_websocket = SimpleNamespace(app=app)  # _user_monitors_symbol only reads `.app`

    with test_client.websocket_connect(_authed_ws_url(test_client, email="ws-iso-c@example.com")):
        test_client.post("/api/monitoring/SPY")  # cookie jar currently holds user C's session
        c_user_id = UUID(test_client.get("/api/auth/me").json()["id"])

        with test_client.websocket_connect(_authed_ws_url(test_client, email="ws-iso-d@example.com")):
            d_user_id = UUID(test_client.get("/api/auth/me").json()["id"])

            assert _user_monitors_symbol(fake_websocket, c_user_id, "SPY") is True
            assert _user_monitors_symbol(fake_websocket, d_user_id, "SPY") is False
            assert _user_monitors_symbol(fake_websocket, c_user_id, "AAPL") is False
