from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import (
    AlertEvent,
    AlertOrigin,
    AlertSeverity,
    AlertType,
    MonitoringSubscription,
)
from tests.unit.ai_analysis.conftest import make_session

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def _repo() -> SqlAlchemyAlertRepository:
    return SqlAlchemyAlertRepository(make_session())


def _event(alert_id: str = "alert-1", dedup_key: str = "dedup-1", **overrides) -> AlertEvent:
    fields = dict(
        alert_id=alert_id,
        symbol="SPY",
        decision_plan_id="plan-1",
        alert_type=AlertType.THESIS_WEAKENING,
        severity=AlertSeverity.IMPORTANT,
        title="Thesis weakening",
        summary="A tracked condition flipped to FAILED.",
        occurred_at=NOW,
        evaluated_at=NOW,
        dedup_key=dedup_key,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=NOW,
    )
    fields.update(overrides)
    return AlertEvent(**fields)


def test_record_event_round_trips():
    repo = _repo()
    event = _event()

    stored, created = repo.record_event(event)

    assert created is True
    assert stored.alert_id == "alert-1"
    fetched = repo.get_event("alert-1")
    assert fetched is not None
    assert fetched.dedup_key == "dedup-1"


def test_record_event_is_idempotent_on_dedup_key():
    repo = _repo()
    first = _event(alert_id="alert-1", dedup_key="same-key")
    duplicate = _event(alert_id="alert-2", dedup_key="same-key")

    _, created_first = repo.record_event(first)
    stored_second, created_second = repo.record_event(duplicate)

    assert created_first is True
    assert created_second is False
    assert stored_second.alert_id == "alert-1"
    assert repo.get_event("alert-2") is None


def test_list_events_filters_by_symbol_and_alert_type():
    repo = _repo()
    repo.record_event(_event(alert_id="a1", dedup_key="k1", symbol="SPY"))
    repo.record_event(_event(alert_id="a2", dedup_key="k2", symbol="QQQ"))

    spy_only = repo.list_events(symbol="SPY")
    assert [e.alert_id for e in spy_only] == ["a1"]


def test_unread_count_and_acknowledge():
    repo = _repo()
    repo.record_event(_event(alert_id="a1", dedup_key="k1"))
    repo.record_event(_event(alert_id="a2", dedup_key="k2"))

    assert repo.unread_count() == 2
    repo.acknowledge("a1", acknowledged_at=NOW)
    assert repo.unread_count() == 1
    assert repo.is_acknowledged("a1") is True
    assert repo.is_acknowledged("a2") is False


def test_acknowledge_does_not_mutate_event_payload():
    repo = _repo()
    repo.record_event(_event(alert_id="a1", dedup_key="k1"))

    repo.acknowledge("a1", acknowledged_at=NOW)

    fetched = repo.get_event("a1")
    assert fetched is not None
    assert fetched.model_dump(mode="json") == _event(alert_id="a1", dedup_key="k1").model_dump(mode="json")


def test_acknowledge_all_marks_every_unread():
    repo = _repo()
    repo.record_event(_event(alert_id="a1", dedup_key="k1"))
    repo.record_event(_event(alert_id="a2", dedup_key="k2"))

    count = repo.acknowledge_all(acknowledged_at=NOW)

    assert count == 2
    assert repo.unread_count() == 0


def test_preferences_default_empty_then_settable():
    repo = _repo()
    assert repo.get_preferences() == []

    repo.set_preference(AlertType.INVALIDATED, True)
    repo.set_preference(AlertType.WATCHING, False)

    prefs = {p.alert_type: p.enabled for p in repo.get_preferences()}
    assert prefs[AlertType.INVALIDATED] is True
    assert prefs[AlertType.WATCHING] is False


def test_set_preference_upserts_not_duplicates():
    repo = _repo()
    repo.set_preference(AlertType.INVALIDATED, True)
    repo.set_preference(AlertType.INVALIDATED, False)

    prefs = repo.get_preferences()
    assert len(prefs) == 1
    assert prefs[0].enabled is False


def test_monitoring_subscription_upsert_and_remove():
    repo = _repo()
    sub = MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)

    repo.upsert_monitoring_subscription(sub)
    subs = repo.list_monitoring_subscriptions()
    assert [s.symbol for s in subs] == ["SPY"]

    repo.upsert_monitoring_subscription(sub.model_copy(update={"enabled": False}))
    subs = repo.list_monitoring_subscriptions()
    assert len(subs) == 1
    assert subs[0].enabled is False

    repo.remove_monitoring_subscription("SPY")
    assert repo.list_monitoring_subscriptions() == []
