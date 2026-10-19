from __future__ import annotations

from uuid import uuid4

import pytest

import app.alerts.push as push_module
from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin, AlertType, MonitoringSubscription
from app.alerts.service import AlertService, transition_alert_type
from app.config import Settings
from app.decision_engine.schemas import DecisionState
from app.decision_engine.state_machine import build_transition
from app.notifications.pushover import PushoverSendResult
from app.notifications.secret_crypto import encrypt_secret
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan


def _service() -> AlertService:
    return AlertService(SqlAlchemyAlertRepository(make_session()))


def test_transition_alert_type_maps_invalidated():
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)
    assert transition_alert_type(transition) == AlertType.INVALIDATED


def test_transition_alert_type_returns_none_for_abstain():
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=plan.as_of)
    assert transition_alert_type(transition) is None


def test_emit_transition_alert_creates_event_with_deterministic_reason():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.INVALIDATED, reason="Invalidation condition met: broke support", as_of=plan.as_of
    )

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is not None
    assert event.alert_type == AlertType.INVALIDATED
    assert event.summary == transition.reason
    assert event.decision_plan_id == plan.decision_plan_id
    assert event.origin == AlertOrigin.LIVE_PROSPECTIVE


def test_emit_transition_alert_is_idempotent_for_same_transition():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)

    first = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    second = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert first is not None and second is not None
    assert first.alert_id == second.alert_id


def test_emit_transition_alert_respects_disabled_preference():
    repo = SqlAlchemyAlertRepository(make_session())
    repo.set_preference(AlertType.INVALIDATED, False)
    service = AlertService(repo)
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None
    assert repo.unread_count() == 0


def test_emit_transition_alert_returns_none_for_abstain():
    service = _service()
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=plan.as_of)

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None


def test_emit_transition_alert_rejects_banned_language():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.INVALIDATED, reason="Strong sell, guaranteed loss", as_of=plan.as_of
    )

    with pytest.raises(ValueError):
        service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)


def test_emit_condition_alert_dedupes_within_cooldown():
    from datetime import datetime, timezone

    service = _service()
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    first = service.emit_condition_alert(
        symbol="SPY",
        alert_type=AlertType.DATA_STALE,
        identity="freshness",
        title="Data stale",
        summary="SPY market data has not refreshed within the expected window.",
        source_timestamp=ts,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
    )
    second = service.emit_condition_alert(
        symbol="SPY",
        alert_type=AlertType.DATA_STALE,
        identity="freshness",
        title="Data stale",
        summary="SPY market data has not refreshed within the expected window.",
        source_timestamp=ts,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
    )

    assert first is not None and second is not None
    assert first.alert_id == second.alert_id


# -------------------------------------------------- Phase 20.1 security review
# THESIS_STRENGTHENING's DEFAULT_ALERT_PREFERENCES entry stays False (restored
# from the brief True detour during Phase 20) -- _record's push-eligible
# bypass must let the underlying AlertEvent exist (for dedup + push) WITHOUT
# ever widening who sees it in their in-app Alert Center.


def _push_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key="test-pushover-key-encryption-key-at-least-32-chars",
    )
    base.update(overrides)
    return Settings(**base)


def test_thesis_strengthening_default_preference_is_still_false():
    from app.alerts.schemas import DEFAULT_ALERT_PREFERENCES

    assert DEFAULT_ALERT_PREFERENCES[AlertType.THESIS_STRENGTHENING] is False


def test_thesis_strengthening_in_app_default_is_unchanged_no_user_gets_a_delivery_by_default():
    """Proof 5: a user who monitors the symbol but never explicitly
    enabled their own THESIS_STRENGTHENING in-app preference gets NO
    UserAlertDeliveryRecord for it -- exactly the pre-existing default,
    even though the underlying AlertEvent now gets recorded (for dedup/
    push purposes)."""
    from datetime import datetime as _dt

    repository = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    repository.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="AAPL", enabled=True, added_at=_dt(2026, 1, 1))
    )
    service = AlertService(repository)
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.THESIS_STRENGTHENING, reason="getting stronger", as_of=plan.as_of
    )

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is not None  # recorded, for dedup/push purposes
    assert repository.user_unread_count(user_id) == 0  # but NOT delivered in-app, same as before
    assert repository.list_user_alerts(user_id) == []


def test_explicit_push_opt_in_for_thesis_strengthening_still_delivers_a_push(monkeypatch):
    """Proof 6: a user who explicitly opted into push (enabled + own key
    configured) still receives a push for THESIS_STRENGTHENING, even
    though its in-app default stays off for everyone (proof 5)."""
    from datetime import datetime as _dt

    captured_calls = []

    class _RecordingFactory:
        def __call__(self, app_token, user_key):
            captured_calls.append((app_token, user_key))

            class _Provider:
                def send(self, message):
                    return PushoverSendResult(success=True)

                def close(self):
                    pass

            return _Provider()

    settings = _push_settings()
    monkeypatch.setattr(push_module, "get_settings", lambda: settings)
    # Monkeypatch the default provider factory push.py falls back to when
    # AlertService calls dispatch_push_notifications without one explicitly
    # (the real end-to-end call path, exactly as production uses it).
    monkeypatch.setattr(push_module, "_default_provider_factory", _RecordingFactory())

    repository = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    repository.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="AAPL", enabled=True, added_at=_dt(2026, 1, 1))
    )
    repository.set_user_push_enabled(user_id, True)
    repository.set_user_pushover_key_encrypted(
        user_id, encrypt_secret("this-users-own-key", encryption_key=settings.pushover_key_encryption_key)
    )

    service = AlertService(repository)
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.THESIS_STRENGTHENING, reason="getting stronger", as_of=plan.as_of
    )

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is not None
    assert captured_calls == [("test-app-token", "this-users-own-key")]


def test_an_explicit_operator_disable_still_blocks_push_bypass():
    """The push-eligible bypass only activates when the ONLY blocker is
    the bare default -- an explicit operator override to False must
    still fully block recording (and therefore push), exactly as
    before Phase 20 ever existed."""
    repository = SqlAlchemyAlertRepository(make_session())
    repository.set_preference(AlertType.THESIS_STRENGTHENING, False)
    service = AlertService(repository)
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.THESIS_STRENGTHENING, reason="getting stronger", as_of=plan.as_of
    )

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None
