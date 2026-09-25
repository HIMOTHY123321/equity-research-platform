from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.prospective import is_prospective_eligible
from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from tests.unit.ai_analysis.conftest import make_session

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def _event(alert_id: str, dedup_key: str, alert_type: AlertType, origin: AlertOrigin) -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        symbol="SPY",
        alert_type=alert_type,
        severity=AlertSeverity.IMPORTANT,
        title="t",
        summary="s",
        occurred_at=NOW,
        evaluated_at=NOW,
        dedup_key=dedup_key,
        origin=origin,
        pipeline_version="test",
        created_at=NOW,
    )


def test_live_prospective_invalidated_is_eligible():
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event) is True


def test_dev_fixture_is_never_eligible_even_for_eligible_type():
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.DEV_FIXTURE)
    assert is_prospective_eligible(event) is False


def test_historical_replay_is_never_eligible_even_for_eligible_type():
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.HISTORICAL_REPLAY)
    assert is_prospective_eligible(event) is False


def test_watching_is_never_eligible_regardless_of_origin():
    event = _event("a1", "k1", AlertType.WATCHING, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event) is False


def test_repository_count_only_includes_eligible_live_prospective_events():
    repo = SqlAlchemyAlertRepository(make_session())
    repo.record_event(_event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE))
    repo.record_event(_event("a2", "k2", AlertType.EXIT_CONDITIONS_MET, AlertOrigin.LIVE_PROSPECTIVE))
    repo.record_event(_event("a3", "k3", AlertType.INVALIDATED, AlertOrigin.DEV_FIXTURE))
    repo.record_event(_event("a4", "k4", AlertType.INVALIDATED, AlertOrigin.HISTORICAL_REPLAY))
    repo.record_event(_event("a5", "k5", AlertType.WATCHING, AlertOrigin.LIVE_PROSPECTIVE))

    assert repo.count_prospective_observations() == 2
