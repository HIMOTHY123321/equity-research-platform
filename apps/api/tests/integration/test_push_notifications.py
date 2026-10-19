"""Phase 20/20.1: end-to-end phone-push notification coverage through the
real FastAPI app + real AlertService wiring (never a reimplementation of
the dispatch logic) -- same db_env/_signup_and_monitor pattern as
test_alerts_routes.py. A FakeProviderFactory is injected by monkeypatching
app.alerts.push._default_provider_factory so no real network/Pushover
account is ever touched, while the REST routes, repository, and
AlertService._record wiring are all exercised for real.

Security review focus: there is no global Pushover user key anymore --
every test that expects a push explicitly configures that specific user's
OWN key via PUT /api/alerts/push-key first, and the cross-user isolation
tests below assert on the EXACT key each Pushover call carried.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.alerts.push as push_module
from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin
from app.alerts.service import AlertService
from app.config import Settings
from app.database.session import get_db
from app.decision_engine.schemas import DecisionState
from app.decision_engine.state_machine import build_transition
from app.main import app
from app.notifications.pushover import PushoverSendResult
from tests.integration.test_live_routes import client as live_client  # noqa: F401 -- fixture import
from tests.unit.decision_engine.test_state_machine import make_plan

_ = live_client  # keep the fixture import "used" for linters

NOW = datetime(2026, 10, 19, 14, 35, tzinfo=timezone.utc)


class FakeProviderFactory:
    """Records every (app_token, user_key) pair asked for and every
    message sent through it -- the exact thing a cross-user leak would
    show up in."""

    def __init__(self, result: PushoverSendResult | None = None, raise_exc: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.sent: list[tuple[str, object]] = []
        self._result = result or PushoverSendResult(success=True)
        self._raise_exc = raise_exc

    def __call__(self, app_token: str, user_key: str):
        self.calls.append((app_token, user_key))
        factory = self

        class _Provider:
            def send(self, message):
                factory.sent.append((user_key, message))
                if factory._raise_exc is not None:
                    raise factory._raise_exc
                return factory._result

            def close(self):
                pass

        return _Provider()


def _test_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key="test-pushover-key-encryption-key-at-least-32-chars",
        app_url="https://ai-market-desk-web.onrender.com",
    )
    base.update(overrides)
    return Settings(**base)


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
    yield session_factory
    app.dependency_overrides.clear()


@pytest.fixture
def fake_provider(monkeypatch):
    factory = FakeProviderFactory()
    monkeypatch.setattr(push_module, "_default_provider_factory", factory)
    monkeypatch.setattr(push_module, "get_settings", lambda: _test_settings())
    # The routes layer (PUT /api/alerts/push-key) also calls get_settings
    # to find pushover_key_encryption_key for encryption -- must use the
    # SAME settings object so the key it encrypts can be decrypted by
    # push.py's own get_settings() call during dispatch.
    import app.api.routes.alerts as alerts_routes

    monkeypatch.setattr(alerts_routes, "get_settings", lambda: _test_settings())
    return factory


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _signup_monitor_and_configure_push(
    client: TestClient, *symbols: str, email: str, pushover_key: str = "default-test-key"
) -> str:
    token = client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"}).json()[
        "access_token"
    ]
    for symbol in symbols:
        client.post(f"/api/monitoring/{symbol}", headers=_auth(token))
    client.put("/api/alerts/push-key", json={"pushover_user_key": pushover_key}, headers=_auth(token))
    client.put("/api/alerts/push-preference", json={"enabled": True}, headers=_auth(token))
    return token


def _signup_and_monitor(client: TestClient, *symbols: str, email: str) -> str:
    token = client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"}).json()[
        "access_token"
    ]
    for symbol in symbols:
        client.post(f"/api/monitoring/{symbol}", headers=_auth(token))
    return token


def _emit_entry_conditions_met(session_factory, *, symbol="SPY"):
    session = session_factory()
    repository = SqlAlchemyAlertRepository(session)
    service = AlertService(repository)
    plan = make_plan(DecisionState.WATCHING).model_copy(update={"symbol": symbol})
    transition = build_transition(plan, DecisionState.ENTRY_CONDITIONS_MET, reason="test", as_of=NOW)
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    session.close()
    return event


# ---------------------------------------------------------------- Preferences


def test_push_preference_defaults_to_disabled_and_unconfigured(db_env):
    with TestClient(app) as client:
        token = _signup_and_monitor(client, email="push-default@example.com")
        response = client.get("/api/alerts/push-preference", headers=_auth(token))
        assert response.status_code == 200
        assert response.json() == {"enabled": False, "key_configured": False}


def test_push_preference_can_be_enabled_and_persists(db_env, fake_provider):
    with TestClient(app) as client:
        token = _signup_and_monitor(client, email="push-enable@example.com")
        client.put("/api/alerts/push-key", json={"pushover_user_key": "my-key"}, headers=_auth(token))
        put_response = client.put(
            "/api/alerts/push-preference", json={"enabled": True}, headers=_auth(token)
        )
        assert put_response.json() == {"enabled": True, "key_configured": True}

        get_response = client.get("/api/alerts/push-preference", headers=_auth(token))
        assert get_response.json() == {"enabled": True, "key_configured": True}


def test_push_key_can_be_set_and_removed(db_env, fake_provider):
    with TestClient(app) as client:
        token = _signup_and_monitor(client, email="push-key-crud@example.com")

        set_response = client.put(
            "/api/alerts/push-key", json={"pushover_user_key": "a-real-looking-key"}, headers=_auth(token)
        )
        assert set_response.json() == {"key_configured": True}

        delete_response = client.delete("/api/alerts/push-key", headers=_auth(token))
        assert delete_response.json() == {"key_configured": False}

        get_response = client.get("/api/alerts/push-preference", headers=_auth(token))
        assert get_response.json()["key_configured"] is False


def test_push_key_response_never_echoes_the_submitted_key(db_env, fake_provider):
    with TestClient(app) as client:
        token = _signup_and_monitor(client, email="push-key-no-echo@example.com")
        response = client.put(
            "/api/alerts/push-key",
            json={"pushover_user_key": "super-secret-destination-key"},
            headers=_auth(token),
        )
        assert "super-secret-destination-key" not in response.text
        assert response.json() == {"key_configured": True}


def test_push_status_reports_unconfigured_by_default(db_env):
    with TestClient(app) as client:
        response = client.get("/api/alerts/push-status")
        assert response.status_code == 200
        assert response.json()["configured"] is False


def test_push_status_response_never_contains_credential_values(db_env, monkeypatch):
    import app.api.routes.alerts as alerts_routes

    monkeypatch.setattr(
        alerts_routes,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            environment="test",
            push_notifications_enabled=True,
            pushover_app_token="super-secret-app-token",
            pushover_key_encryption_key="super-secret-encryption-key",
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/alerts/push-status")
        assert response.status_code == 200
        assert "super-secret-app-token" not in response.text
        assert "super-secret-encryption-key" not in response.text
        assert response.json() == {"configured": True}


def test_missing_encryption_key_reports_unconfigured_rather_than_crashing(db_env, monkeypatch):
    """Phase 20.2 proof 3 (route level): PUSH_NOTIFICATIONS_ENABLED and
    PUSHOVER_APP_TOKEN are both set, but PUSHOVER_KEY_ENCRYPTION_KEY is
    missing -- the status endpoint must report `configured: False`, not
    raise, and submitting a key must fail safely rather than crash."""
    import app.api.routes.alerts as alerts_routes

    settings_without_encryption_key = Settings(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key="",
    )
    monkeypatch.setattr(alerts_routes, "get_settings", lambda: settings_without_encryption_key)

    with TestClient(app) as client:
        status_response = client.get("/api/alerts/push-status")
        assert status_response.status_code == 200
        assert status_response.json() == {"configured": False}

        token = _signup_and_monitor(client, "SPY", email="push-no-encryption-key@example.com")
        key_response = client.put(
            "/api/alerts/push-key", json={"pushover_user_key": "some-key"}, headers=_auth(token)
        )
        assert key_response.status_code == 503


# ---------------------------------------------------------------- Dispatch / isolation


def test_entry_conditions_met_sends_exactly_one_push_to_a_monitoring_push_enabled_user(
    db_env, fake_provider
):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-entry@example.com", pushover_key="entry-key"
        )

    event = _emit_entry_conditions_met(db_env, symbol="SPY")
    assert event is not None
    assert len(fake_provider.sent) == 1
    user_key, message = fake_provider.sent[0]
    assert user_key == "entry-key"
    assert "SPY" in message.title


def test_two_users_with_separate_destinations_receive_separate_calls_to_their_own_keys(
    db_env, fake_provider
):
    """Proof 1 + 2 of the security review, at the full route+dispatch
    level: User A's and User B's pushes must go to THEIR OWN keys,
    never to each other's."""
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-user-a@example.com", pushover_key="key-a"
        )
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-user-b@example.com", pushover_key="key-b"
        )

    event = _emit_entry_conditions_met(db_env, symbol="SPY")

    assert event is not None
    assert len(fake_provider.calls) == 2
    sent_keys = {key for _app_token, key in fake_provider.calls}
    assert sent_keys == {"key-a", "key-b"}


def test_a_user_without_a_configured_key_is_skipped_but_other_users_still_get_their_push(
    db_env, fake_provider
):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-with-key@example.com", pushover_key="has-a-key"
        )
    with TestClient(app) as client:
        token = _signup_and_monitor(client, "SPY", email="push-without-key@example.com")
        # Enabled, but never configured a key.
        client.put("/api/alerts/push-preference", json={"enabled": True}, headers=_auth(token))

    event = _emit_entry_conditions_met(db_env, symbol="SPY")

    assert event is not None
    assert len(fake_provider.calls) == 1
    assert fake_provider.calls[0][1] == "has-a-key"


def test_unmonitored_symbol_sends_no_push(db_env, fake_provider):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(client, "AAPL", email="push-unmonitored@example.com")

    # This user monitors AAPL, not SPY -- the transition below is for SPY.
    event = _emit_entry_conditions_met(db_env, symbol="SPY")
    assert event is not None
    assert fake_provider.sent == []


def test_disabled_push_preference_sends_no_push_even_when_monitoring_and_key_configured(
    db_env, fake_provider
):
    with TestClient(app) as client:
        token = _signup_and_monitor(client, "SPY", email="push-disabled@example.com")
        client.put(
            "/api/alerts/push-key",
            json={"pushover_user_key": "configured-but-disabled"},
            headers=_auth(token),
        )
        # Deliberately never enabling push -- the conservative default.

    event = _emit_entry_conditions_met(db_env, symbol="SPY")
    assert event is not None
    assert fake_provider.sent == []


def test_missing_encryption_key_disables_dispatch_even_with_a_valid_stored_key(
    db_env, fake_provider, monkeypatch
):
    """Phase 20.2 proof 3 (dispatch level): a user fully configured
    (monitoring, push enabled, key stored while the encryption key WAS
    present) must still receive nothing once the encryption key goes
    missing -- dispatch fails safe, never crashes, never falls back to
    some other derivation."""
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-encryption-key-removed@example.com", pushover_key="orphaned-key"
        )

    monkeypatch.setattr(
        push_module, "get_settings", lambda: _test_settings(pushover_key_encryption_key="")
    )

    event = _emit_entry_conditions_met(db_env, symbol="SPY")
    assert event is not None
    assert fake_provider.sent == []


def test_a_second_identical_transition_never_sends_a_duplicate_push(db_env, fake_provider):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(
            client, "SPY", email="push-dedup@example.com", pushover_key="dedup-key"
        )

    session = db_env()
    repository = SqlAlchemyAlertRepository(session)
    service = AlertService(repository)
    plan = make_plan(DecisionState.WATCHING).model_copy(update={"symbol": "SPY"})
    transition = build_transition(plan, DecisionState.ENTRY_CONDITIONS_MET, reason="test", as_of=NOW)

    first = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    second = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    session.close()

    assert first is not None and second is not None
    assert first.alert_id == second.alert_id  # same dedup_key -- the SAME underlying AlertEvent
    assert len(fake_provider.sent) == 1  # never two pushes for one transition


def test_watching_state_never_sends_a_push(db_env, fake_provider):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(client, "SPY", email="push-watching@example.com")

    from app.alerts.schemas import AlertType

    session = db_env()
    repository = SqlAlchemyAlertRepository(session)
    repository.set_preference(AlertType.WATCHING, True)
    service = AlertService(repository)
    plan = make_plan(DecisionState.EVALUATING).model_copy(update={"symbol": "SPY"})
    transition = build_transition(plan, DecisionState.WATCHING, reason="watching", as_of=NOW)
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    session.close()

    assert event is not None
    assert fake_provider.sent == []


def test_abstain_state_never_sends_a_push(db_env, fake_provider):
    with TestClient(app) as client:
        _signup_monitor_and_configure_push(client, "SPY", email="push-abstain@example.com")

    session = db_env()
    repository = SqlAlchemyAlertRepository(session)
    service = AlertService(repository)
    plan = make_plan(DecisionState.EVALUATING).model_copy(update={"symbol": "SPY"})
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=NOW)
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    session.close()

    assert event is None  # ABSTAIN produces no AlertEvent at all
    assert fake_provider.sent == []


def test_a_provider_exception_does_not_prevent_the_alert_from_being_recorded(db_env, monkeypatch):
    """The Pushover-is-down scenario: AlertService._record must still
    return the stored AlertEvent even if push dispatch blows up inside."""
    exploding = FakeProviderFactory(raise_exc=RuntimeError("Pushover is unreachable"))
    monkeypatch.setattr(push_module, "_default_provider_factory", exploding)
    monkeypatch.setattr(push_module, "get_settings", lambda: _test_settings())
    import app.api.routes.alerts as alerts_routes

    monkeypatch.setattr(alerts_routes, "get_settings", lambda: _test_settings())

    with TestClient(app) as client:
        _signup_monitor_and_configure_push(client, "SPY", email="push-exploding@example.com")

    event = _emit_entry_conditions_met(db_env, symbol="SPY")

    assert event is not None  # the Decision Engine's alert record is unaffected
    assert len(exploding.calls) == 1  # it did try


def test_real_time_available_is_unaffected_by_a_push_notification_dispatch(live_client, fake_provider):
    """Critical market-data rule: push notification delivery must never
    touch REAL TIME truth conditions. Reuses test_live_routes.py's own
    real `client` fixture (real app lifespan, no streaming provider
    configured) so this is the exact same honest-`False` baseline that
    file's own tests already rely on."""
    test_client, _provider = live_client
    test_client.post(
        "/api/auth/signup", json={"email": "push-realtime@example.com", "password": "hunter2hunter2"}
    )
    test_client.post("/api/monitoring/SPY")
    test_client.put("/api/alerts/push-key", json={"pushover_user_key": "realtime-key"})
    test_client.put("/api/alerts/push-preference", json={"enabled": True})

    before = test_client.get("/api/live/status").json()
    assert before["real_time_available"] is False

    session = test_client.db_session_factory()
    repository = SqlAlchemyAlertRepository(session)
    service = AlertService(repository)
    plan = make_plan(DecisionState.WATCHING).model_copy(update={"symbol": "SPY"})
    transition = build_transition(plan, DecisionState.ENTRY_CONDITIONS_MET, reason="test", as_of=NOW)
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    session.close()

    assert event is not None
    assert len(fake_provider.sent) == 1  # the push genuinely fired

    after = test_client.get("/api/live/status").json()
    assert after["real_time_available"] is False
