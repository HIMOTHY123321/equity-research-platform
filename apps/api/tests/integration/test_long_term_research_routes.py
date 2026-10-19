"""Long-Term Research API -- end-to-end through the real FastAPI app.
Market data and fundamentals are faked (no network); the Pushover
provider factory is monkeypatched, same pattern as
test_push_notifications.py. REAL TIME semantics (app.live) are never
touched by this feature -- see test_real_time_semantics_remain_untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.long_term_research.push as ltr_push_module
from app.api.deps import get_fundamentals_provider, get_market_data_provider
from app.database.session import get_db
from app.long_term_research.fundamentals import FixtureFundamentalsProvider
from app.long_term_research.schemas import LongTermResearchState
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.notifications.pushover import PushoverSendResult
from tests.unit.long_term_research.helpers import (
    strong_positive_candles,
    strong_positive_fundamentals,
)

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeMarketDataProvider(MarketDataProvider):
    def __init__(self, candles_by_symbol: dict[str, list]):
        self._candles = candles_by_symbol

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        candles = self._candles.get(symbol, [])
        if before is not None:
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


class _FakeProviderFactory:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, app_token, user_key):
        self.calls.append((app_token, user_key))
        factory = self

        class _Provider:
            def send(self, message):
                factory_calls = factory
                _ = factory_calls
                return PushoverSendResult(success=True)

            def close(self):
                pass

        return _Provider()


@pytest.fixture
def db_env():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session_factory = sessionmaker(bind=engine)

    def _get_db_override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_market_data_provider] = lambda: _FakeMarketDataProvider(
        {"AAPL": strong_positive_candles(AS_OF)}
    )
    app.dependency_overrides[get_fundamentals_provider] = lambda: FixtureFundamentalsProvider(
        {"AAPL": strong_positive_fundamentals(AS_OF)}
    )
    yield session_factory
    app.dependency_overrides.clear()


@pytest.fixture
def fake_pushover(monkeypatch):
    factory = _FakeProviderFactory()
    monkeypatch.setattr(ltr_push_module, "_default_provider_factory", factory)
    return factory


def _signup_and_add_to_watchlist(client: TestClient, *symbols: str, email: str) -> str:
    token = client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"}).json()[
        "access_token"
    ]
    # Triggers SqlAlchemyWatchlistRepository's lazy default-watchlist
    # creation/seeding (app.watchlist.repository.
    # _get_or_create_default_watchlist) -- a brand-new signup has NO
    # watchlist row at all until something reads/writes it once.
    client.get("/api/watchlist", headers=_auth(token))
    for symbol in symbols:
        client.post("/api/watchlist/symbols", json={"ticker": symbol}, headers=_auth(token))
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_manual_scan_persists_and_returns_a_snapshot_for_the_callers_watchlist(db_env):
    """A new signup's default watchlist is pre-seeded with several
    symbols (see app.watchlist.repository.DEFAULT_WATCHLIST_SYMBOLS,
    which includes AAPL) -- the scan covers all of them, not just the
    one this test cares about, so we only assert on AAPL's own result
    rather than an exact count."""
    with TestClient(app) as client:
        token = _signup_and_add_to_watchlist(client, email="ltr-manual@example.com")
        response = client.post("/api/long-term-research/scan", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    by_symbol = {r["symbol"]: r for r in body["results"]}
    assert by_symbol["AAPL"]["research_state"] == LongTermResearchState.ACCUMULATION_CANDIDATE.value


def test_manual_scan_never_requires_waiting_for_the_scheduled_job(db_env):
    """The manual "RUN LONG-TERM SCAN" button has no idempotency gate --
    running it twice in a row must work both times."""
    with TestClient(app) as client:
        token = _signup_and_add_to_watchlist(client, email="ltr-repeat@example.com")
        first = client.post("/api/long-term-research/scan", headers=_auth(token))
        second = client.post("/api/long-term-research/scan", headers=_auth(token))

    assert first.status_code == 200
    assert second.status_code == 200


def test_list_and_get_long_term_research_are_scoped_to_the_callers_own_watchlist(db_env):
    """Research snapshots are symbol-level (shared/global, like the rest
    of this app's market research), so two users with overlapping
    default watchlists legitimately see the same symbols -- isolation is
    proven here with a symbol ONLY user A added (not in the default
    seed), which must never appear in user B's list."""
    with TestClient(app) as client:
        token_a = _signup_and_add_to_watchlist(client, "IBM", email="ltr-user-a@example.com")
        token_b = client.post(
            "/api/auth/signup", json={"email": "ltr-user-b@example.com", "password": "hunter2hunter2"}
        ).json()["access_token"]
        client.get("/api/watchlist", headers=_auth(token_b))  # seed user B's own default watchlist

        client.post("/api/long-term-research/scan", headers=_auth(token_a))

        list_for_a = client.get("/api/long-term-research", headers=_auth(token_a))
        list_for_b = client.get("/api/long-term-research", headers=_auth(token_b))

    symbols_for_a = {r["symbol"] for r in list_for_a.json()}
    symbols_for_b = {r["symbol"] for r in list_for_b.json()}
    assert "IBM" in symbols_for_a
    assert "IBM" not in symbols_for_b


def test_get_single_symbol_returns_404_before_any_scan_has_run(db_env):
    with TestClient(app) as client:
        token = _signup_and_add_to_watchlist(client, "AAPL", email="ltr-404@example.com")
        response = client.get("/api/long-term-research/AAPL", headers=_auth(token))
    assert response.status_code == 404


def test_scheduled_scan_requires_the_correct_shared_secret(db_env, monkeypatch):
    import app.api.routes.long_term_research as routes_module
    from app.config import Settings

    settings = Settings(_env_file=None, environment="test", scheduler_shared_secret="correct-secret")
    monkeypatch.setattr(routes_module, "get_settings", lambda: settings)

    with TestClient(app) as client:
        wrong_secret = client.post(
            "/api/long-term-research/scheduled-scan", headers={"X-Scheduler-Secret": "wrong"}
        )
        missing_secret = client.post("/api/long-term-research/scheduled-scan")
        correct_secret = client.post(
            "/api/long-term-research/scheduled-scan", headers={"X-Scheduler-Secret": "correct-secret"}
        )

    assert wrong_secret.status_code == 401
    assert missing_secret.status_code == 401
    assert correct_secret.status_code == 200


def test_scheduled_scan_rejects_everyone_when_no_secret_is_configured(db_env, monkeypatch):
    import app.api.routes.long_term_research as routes_module
    from app.config import Settings

    settings = Settings(_env_file=None, environment="test", scheduler_shared_secret="")
    monkeypatch.setattr(routes_module, "get_settings", lambda: settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/long-term-research/scheduled-scan", headers={"X-Scheduler-Secret": "anything"}
        )
    assert response.status_code == 401


def test_scheduled_scan_is_idempotent_for_the_same_calendar_day(db_env, monkeypatch):
    import app.api.routes.long_term_research as routes_module
    from app.config import Settings

    settings = Settings(_env_file=None, environment="test", scheduler_shared_secret="secret")
    monkeypatch.setattr(routes_module, "get_settings", lambda: settings)

    with TestClient(app) as client:
        _signup_and_add_to_watchlist(client, "AAPL", email="ltr-sched@example.com")
        first = client.post(
            "/api/long-term-research/scheduled-scan", headers={"X-Scheduler-Secret": "secret"}
        )
        second = client.post(
            "/api/long-term-research/scheduled-scan", headers={"X-Scheduler-Secret": "secret"}
        )

    assert first.json()["ran"] is True
    assert second.json()["ran"] is False


def test_long_term_push_preference_defaults_to_disabled_and_can_be_enabled(db_env):
    with TestClient(app) as client:
        token = _signup_and_add_to_watchlist(client, "AAPL", email="ltr-push-pref@example.com")
        default = client.get("/api/long-term-research/push-preference/me", headers=_auth(token))
        assert default.json() == {"enabled": False, "key_configured": False}

        updated = client.put(
            "/api/long-term-research/push-preference/me", json={"enabled": True}, headers=_auth(token)
        )
        assert updated.json()["enabled"] is True


def test_real_time_semantics_remain_untouched_by_the_long_term_scan(db_env, fake_pushover):
    """Phase 20-style proof 9, reused for this feature: running a
    long-term scan must never flip `real_time_available` or any other
    REAL TIME flag the live routes already report."""
    with TestClient(app) as client:
        token = _signup_and_add_to_watchlist(client, "AAPL", email="ltr-realtime@example.com")

        before = client.get("/api/live/status")
        client.post("/api/long-term-research/scan", headers=_auth(token))
        after = client.get("/api/live/status")

    assert before.status_code == 200
    assert after.status_code == 200
    assert before.json().get("real_time_available") == after.json().get("real_time_available")
    assert after.json().get("real_time_available") is False
