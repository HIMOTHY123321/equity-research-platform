"""Phase 20: repository-level coverage for the three new push-preference/
delivery-status methods, plus deliver_alert_to_subscribed_users' changed
return type (list of delivered user_ids, not a bare count) -- same
make_session()/SqlAlchemyAlertRepository pattern as test_repository.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

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


def _sample_event(**overrides) -> AlertEvent:
    fields = dict(
        alert_id="alert-1",
        symbol="SPY",
        alert_type=AlertType.ENTRY_CONDITIONS_MET,
        severity=AlertSeverity.IMPORTANT,
        title="Entry conditions met",
        summary="test",
        occurred_at=NOW,
        evaluated_at=NOW,
        dedup_key="dedup-1",
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=NOW,
    )
    fields.update(overrides)
    return AlertEvent(**fields)


def test_get_user_push_enabled_defaults_to_false():
    repo = SqlAlchemyAlertRepository(make_session())
    assert repo.get_user_push_enabled(uuid4()) is False


def test_set_user_push_enabled_persists_and_is_settable_back():
    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()

    repo.set_user_push_enabled(user_id, True)
    assert repo.get_user_push_enabled(user_id) is True

    repo.set_user_push_enabled(user_id, False)
    assert repo.get_user_push_enabled(user_id) is False


def test_set_user_push_enabled_is_per_user():
    repo = SqlAlchemyAlertRepository(make_session())
    user_a, user_b = uuid4(), uuid4()
    repo.set_user_push_enabled(user_a, True)
    assert repo.get_user_push_enabled(user_a) is True
    assert repo.get_user_push_enabled(user_b) is False


def test_deliver_alert_to_subscribed_users_returns_the_delivered_user_ids_not_a_count():
    repo = SqlAlchemyAlertRepository(make_session())
    user_a, user_b = uuid4(), uuid4()
    repo.upsert_user_monitoring_subscription(
        user_a, MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)
    )
    repo.upsert_user_monitoring_subscription(
        user_b, MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)
    )
    event, created = repo.record_event(_sample_event())
    assert created is True

    delivered = repo.deliver_alert_to_subscribed_users(event)

    assert isinstance(delivered, list)
    assert set(delivered) == {user_a, user_b}


def test_deliver_alert_to_subscribed_users_returns_empty_list_for_an_unmonitored_symbol():
    repo = SqlAlchemyAlertRepository(make_session())
    event, _created = repo.record_event(_sample_event())

    delivered = repo.deliver_alert_to_subscribed_users(event)

    assert delivered == []


def test_record_push_delivery_updates_the_existing_delivery_row():
    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    repo.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)
    )
    event, _created = repo.record_event(_sample_event())
    repo.deliver_alert_to_subscribed_users(event)

    repo.record_push_delivery(user_id, event.alert_id, success=True)

    alerts = repo.list_user_alerts(user_id)
    assert len(alerts) == 1  # the delivery row still exists, unaffected in shape


def test_record_push_delivery_is_a_noop_for_a_nonexistent_delivery():
    repo = SqlAlchemyAlertRepository(make_session())
    # Never raises even though no delivery row exists for this (user, alert).
    repo.record_push_delivery(uuid4(), "nonexistent-alert", success=False, error="network_error")


def test_record_push_delivery_failure_records_the_error_category():
    from sqlalchemy import select

    from app.database.models import UserAlertDeliveryRecord

    session = make_session()
    repo = SqlAlchemyAlertRepository(session)
    user_id = uuid4()
    repo.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)
    )
    event, _created = repo.record_event(_sample_event())
    repo.deliver_alert_to_subscribed_users(event)

    repo.record_push_delivery(user_id, event.alert_id, success=False, error="invalid_credentials")

    row = session.execute(
        select(UserAlertDeliveryRecord).where(
            UserAlertDeliveryRecord.user_id == user_id, UserAlertDeliveryRecord.alert_id == event.alert_id
        )
    ).scalar_one()
    assert row.push_status == "failed"
    assert row.push_error == "invalid_credentials"
    assert row.push_attempted_at is not None


# ------------------------------------------------- Phase 20.1 security review


def test_list_subscribed_user_ids_is_independent_of_alert_type_preference():
    """The push candidate set must NOT depend on in-app alert-type
    preference -- only on monitoring-subscription enabled state."""
    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    repo.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="SPY", enabled=True, added_at=NOW)
    )
    # This user has explicitly muted THESIS_STRENGTHENING in-app...
    repo.set_user_preference(user_id, AlertType.THESIS_STRENGTHENING, False)

    # ...yet still appears in the symbol-subscriber list push dispatch uses.
    assert repo.list_subscribed_user_ids("SPY") == [user_id]


def test_list_subscribed_user_ids_excludes_disabled_subscriptions():
    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    repo.upsert_user_monitoring_subscription(
        user_id, MonitoringSubscription(symbol="SPY", enabled=False, added_at=NOW)
    )
    assert repo.list_subscribed_user_ids("SPY") == []


def test_get_user_pushover_key_encrypted_defaults_to_none():
    repo = SqlAlchemyAlertRepository(make_session())
    assert repo.get_user_pushover_key_encrypted(uuid4()) is None


def test_set_user_pushover_key_encrypted_persists_and_clears():
    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()

    repo.set_user_pushover_key_encrypted(user_id, "ciphertext-blob")
    assert repo.get_user_pushover_key_encrypted(user_id) == "ciphertext-blob"

    repo.set_user_pushover_key_encrypted(user_id, None)
    assert repo.get_user_pushover_key_encrypted(user_id) is None


def test_set_user_pushover_key_encrypted_is_per_user_never_cross_contaminates():
    repo = SqlAlchemyAlertRepository(make_session())
    user_a, user_b = uuid4(), uuid4()

    repo.set_user_pushover_key_encrypted(user_a, "ciphertext-for-a")
    repo.set_user_pushover_key_encrypted(user_b, "ciphertext-for-b")

    assert repo.get_user_pushover_key_encrypted(user_a) == "ciphertext-for-a"
    assert repo.get_user_pushover_key_encrypted(user_b) == "ciphertext-for-b"


def test_the_repository_never_stores_a_plaintext_looking_key_it_only_handles_opaque_ciphertext():
    """Not a crypto test (that's app.notifications.secret_crypto's job)
    -- just confirms the repository layer has no decrypt/encrypt logic
    of its own and stores exactly the string it was given."""
    from app.notifications.secret_crypto import encrypt_secret

    repo = SqlAlchemyAlertRepository(make_session())
    user_id = uuid4()
    encrypted = encrypt_secret("real-plaintext-key", encryption_key="some-encryption-key")

    repo.set_user_pushover_key_encrypted(user_id, encrypted)

    stored = repo.get_user_pushover_key_encrypted(user_id)
    assert stored == encrypted
    assert "real-plaintext-key" not in stored
