"""§28/§6: DATA_STALE/DATA_RECOVERED must be transition-based (emitted
exactly once when crossing into/out of STALE), never repeated time-bucket
noise while a symbol simply remains stale across many monitor passes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertType
from app.alerts.service import AlertService
from app.monitoring.service import MonitoringService
from tests.unit.ai_analysis.conftest import make_session

# 2026-01-05 is a Monday; 15:00 UTC = 10:00 America/New_York, regular session.
_REGULAR_SESSION_AS_OF = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _service() -> MonitoringService:
    return MonitoringService(make_session, market_provider=None)


def _snapshot(candle_age_seconds: float, as_of: datetime):
    return SimpleNamespace(
        feature_snapshot=SimpleNamespace(
            latest_candle=SimpleNamespace(timestamp=as_of - timedelta(seconds=candle_age_seconds))
        )
    )


def _alert_service() -> AlertService:
    return AlertService(SqlAlchemyAlertRepository(make_session()))


def _tick(service, alert_service, age_seconds: float, minutes_offset: int) -> None:
    as_of = _REGULAR_SESSION_AS_OF + timedelta(minutes=minutes_offset)
    service._check_freshness_transition("SPY", _snapshot(age_seconds, as_of), as_of, alert_service)


def test_first_observation_never_alerts_even_if_already_stale():
    service = _service()
    alert_service = _alert_service()

    _tick(service, alert_service, 300, 0)

    assert alert_service._repository.unread_count() == 0


def test_fresh_to_stale_emits_exactly_one_data_stale():
    service = _service()
    alert_service = _alert_service()

    _tick(service, alert_service, 1, 0)  # seed: LIVE
    _tick(service, alert_service, 300, 1)  # -> STALE

    events = alert_service._repository.list_events(symbol="SPY")
    assert [e.alert_type for e in events] == [AlertType.DATA_STALE]


def test_remaining_stale_across_many_passes_emits_zero_additional_data_stale():
    service = _service()
    alert_service = _alert_service()

    _tick(service, alert_service, 1, 0)  # seed: LIVE
    for i in range(1, 11):
        _tick(service, alert_service, 300, i)

    events = alert_service._repository.list_events(symbol="SPY")
    assert len([e for e in events if e.alert_type == AlertType.DATA_STALE]) == 1


def test_stale_to_fresh_emits_exactly_one_data_recovered():
    service = _service()
    alert_service = _alert_service()
    alert_service._repository.set_preference(AlertType.DATA_RECOVERED, True)

    _tick(service, alert_service, 1, 0)  # seed: LIVE
    _tick(service, alert_service, 300, 1)  # -> STALE
    _tick(service, alert_service, 1, 2)  # -> LIVE

    events = alert_service._repository.list_events(symbol="SPY")
    types = [e.alert_type for e in events]
    assert types.count(AlertType.DATA_STALE) == 1
    assert types.count(AlertType.DATA_RECOVERED) == 1


def test_fresh_stale_fresh_stale_emits_two_separate_data_stale_episodes():
    service = _service()
    alert_service = _alert_service()

    _tick(service, alert_service, 1, 0)  # seed: LIVE
    _tick(service, alert_service, 300, 1)  # -> STALE (1st)
    _tick(service, alert_service, 1, 2)  # -> LIVE
    _tick(service, alert_service, 300, 3)  # -> STALE (2nd)

    events = alert_service._repository.list_events(symbol="SPY")
    stale_events = [e for e in events if e.alert_type == AlertType.DATA_STALE]
    assert len(stale_events) == 2
    assert stale_events[0].dedup_key != stale_events[1].dedup_key
