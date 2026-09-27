"""Phase 17 (§60/§79/§99): /api/dev/live-simulator must be reachable ONLY
when explicitly enabled via app.dependency_overrides[get_dev_mock_streaming_provider]
(standing in for settings.enable_dev_live_simulator=True AND
environment != production) -- and a plain 404, indistinguishable from a
route that doesn't exist, in every other configuration. See
app.api.routes.dev_live for the full rationale.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_dev_mock_streaming_provider,
    get_market_data_provider,
    get_news_provider,
    get_session_factory,
)
from app.database.session import get_db
from app.live.config import LiveConfig
from app.live.mock_streaming import MockStreamingProvider
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote

_FAST_CONFIG = LiveConfig(
    target_interval_seconds=0.02,
    heartbeat_interval_seconds=0.1,
    reconnect_initial_backoff_seconds=0.02,
    reconnect_max_backoff_seconds=0.05,
    forecast_monitor_interval_seconds=3600,
    news_monitor_interval_seconds=3600,
)


class _StaticProvider(MarketDataProvider):
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

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        return []

    def get_latest_quote(self, symbol):
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            session=MarketSession.REGULAR,
            bid_price=100.0,
            bid_size=0.0,
            ask_price=100.0,
            ask_size=0.0,
            is_approximate=True,
        )

    def get_previous_close(self, symbol):
        return PreviousClose(
            symbol=symbol, trading_date=datetime.now(timezone.utc).date(), close=100.0, volume=1
        )


def _isolated_get_db_override(db_session_factory):
    def _get_db_override():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    return _get_db_override


@pytest.fixture
def disabled_client(file_session_factory):
    """No override for get_dev_mock_streaming_provider -- the real
    dependency runs, which returns None whenever
    settings.enable_dev_live_simulator is False (the test-env default)."""
    provider = _StaticProvider()
    db_session_factory = file_session_factory()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.dependency_overrides[get_db] = _isolated_get_db_override(db_session_factory)
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "live_config"):
            del app.state.live_config


@pytest.fixture
def enabled_client(file_session_factory):
    provider = _StaticProvider()
    mock_stream = MockStreamingProvider()
    db_session_factory = file_session_factory()
    app.dependency_overrides[get_market_data_provider] = lambda: provider
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    app.dependency_overrides[get_session_factory] = file_session_factory
    app.dependency_overrides[get_db] = _isolated_get_db_override(db_session_factory)
    app.dependency_overrides[get_dev_mock_streaming_provider] = lambda: mock_stream
    app.state.live_config = _FAST_CONFIG
    try:
        with TestClient(app) as test_client:
            yield test_client, mock_stream
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "live_config"):
            del app.state.live_config


def test_simulator_routes_404_when_not_enabled(disabled_client):
    assert disabled_client.get("/api/dev/live-simulator/status").status_code == 404
    trade_response = disabled_client.post(
        "/api/dev/live-simulator/trade", json={"symbol": "SPY", "price": 1}
    )
    assert trade_response.status_code == 404
    assert disabled_client.post("/api/dev/live-simulator/disconnect").status_code == 404


def test_simulator_status_reachable_when_enabled(enabled_client):
    client, _ = enabled_client
    response = client.get("/api/dev/live-simulator/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True


def test_simulator_pushed_trade_reaches_the_real_live_pipeline(enabled_client):
    client, mock_stream = enabled_client
    client.post(
        "/api/auth/signup", json={"email": "dev-sim@example.com", "password": "hunter2hunter2"}
    )
    with client.websocket_connect("/api/live/stream") as ws:
        ws.send_json({"action": "subscribe", "symbol": "SPY", "timeframes": ["1m"]})

        response = client.post("/api/dev/live-simulator/trade", json={"symbol": "SPY", "price": 123.45})
        assert response.status_code == 200

        seen_quote = False
        for _ in range(30):
            frame = ws.receive_json()
            assert frame["schema_version"] == 1
            if frame.get("type") == "quote" and frame.get("symbol") == "SPY":
                assert frame["quote"]["price"] == 123.45
                seen_quote = True
                break
        assert seen_quote


def test_simulator_status_reports_provider_name_as_mock(enabled_client):
    client, _ = enabled_client
    status = client.get("/api/live/status").json()
    assert status["entitlement"]["provider"] == "mock"
    # A mock stream can never be reported as an entitled/licensed feed.
    assert status["entitlement"]["status"] == "not_entitled"
    assert status["real_time_available"] is False


def test_configured_provider_secret_never_appears_in_any_dev_simulator_or_live_status_response(
    enabled_client,
):
    """Phase 17 (§80, CRITICAL): a provider API key is a backend-only
    credential -- app.live.entitlement never embeds the key value itself in
    an entitlement `reason` string (only provider/status/a fixed
    human-readable sentence), and neither /api/live/status nor
    /api/dev/live-simulator/status touch settings.massive_api_key at all.
    This asserts that end-to-end against a real (fake-but-realistic)
    configured secret value, not just by code inspection."""
    from app.api.deps import get_market_data_entitlement
    from app.live.entitlement import resolve_streaming_entitlement
    from app.main import app as main_app

    fake_secret = "sk-massive-test-secret-do-not-leak-9f3a2b"
    entitlement = resolve_streaming_entitlement(
        provider_name="massive", api_key=fake_secret, streaming_entitled_flag=None
    )
    main_app.dependency_overrides[get_market_data_entitlement] = lambda: entitlement

    client, _ = enabled_client
    live_status_text = client.get("/api/live/status").text
    sim_status_text = client.get("/api/dev/live-simulator/status").text

    assert fake_secret not in live_status_text
    assert fake_secret not in sim_status_text
    assert "api_key" not in live_status_text.lower()
    assert "api_key" not in sim_status_text.lower()
