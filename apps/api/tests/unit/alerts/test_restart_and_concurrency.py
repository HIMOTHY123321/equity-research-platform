"""§46/§47: restart-safety and exactly-once semantics for AlertEvent
persistence. The critical test the Phase 14 spec calls out by name:
transition alert already persisted -> restart -> same current state
evaluated again -> no duplicate alert. The mechanism under test is the
database UNIQUE constraint on `dedup_key` (see AlertEventRecord), not an
in-memory set -- so it must survive a brand-new repository/session/thread
pointed at the same on-disk database, and two racing inserts of the exact
same dedup_key must still leave exactly one row.
"""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def _file_session_factory():
    db_path = Path(tempfile.mkdtemp()) / "alerts_restart_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine)


def _event(alert_id: str, dedup_key: str) -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        symbol="SPY",
        decision_plan_id="plan-1",
        alert_type=AlertType.INVALIDATED,
        severity=AlertSeverity.CRITICAL,
        title="Invalidated",
        summary="Invalidation condition met: broke support",
        occurred_at=NOW,
        evaluated_at=NOW,
        transition_id="transition-1",
        dedup_key=dedup_key,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=NOW,
    )


def test_restart_does_not_duplicate_transition_alert():
    session_factory = _file_session_factory()

    # "Before restart": one process records the transition alert and the
    # session/process ends (closed, not just committed-and-kept-open).
    first_session = session_factory()
    first_repo = SqlAlchemyAlertRepository(first_session)
    stored, created = first_repo.record_event(_event("alert-1", "transition:plan-1:transition-1:invalidated"))
    first_session.close()
    assert created is True

    # "After restart": a brand-new repository/session (same on-disk DB,
    # nothing carried over in memory) re-evaluates the same transition and
    # tries to record the identical alert again.
    second_session = session_factory()
    second_repo = SqlAlchemyAlertRepository(second_session)
    stored_again, created_again = second_repo.record_event(
        _event("alert-2", "transition:plan-1:transition-1:invalidated")
    )
    second_session.close()

    assert created_again is False
    assert stored_again.alert_id == stored.alert_id == "alert-1"

    # And the alert history has exactly one row, not two.
    third_session = session_factory()
    third_repo = SqlAlchemyAlertRepository(third_session)
    all_events = third_repo.list_events(symbol="SPY", limit=1000)
    third_session.close()
    assert len(all_events) == 1


def test_concurrent_record_event_same_dedup_key_creates_exactly_one_row():
    session_factory = _file_session_factory()
    # Mirrors app.main's lifespan: tables are created once, synchronously,
    # before anything concurrent runs -- see Base.metadata.create_all(...)
    # there for why (SQLite's checkfirst isn't atomic across threads/
    # connections, so two racing table-creation attempts is a documented,
    # separate concern from the exactly-once dedup semantics this test is
    # actually about).
    warm_session = session_factory()
    SqlAlchemyAlertRepository(warm_session)
    warm_session.close()

    results: list[tuple[AlertEvent, bool]] = []
    errors: list[Exception] = []

    def _record(alert_id: str) -> None:
        session = session_factory()
        try:
            repo = SqlAlchemyAlertRepository(session)
            results.append(repo.record_event(_event(alert_id, "transition:plan-1:transition-1:invalidated")))
        except Exception as exc:  # noqa: BLE001 -- captured for the assertion below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_record, args=(f"alert-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"record_event raised under concurrency: {errors}"
    created_count = sum(1 for _, created in results if created)
    assert created_count == 1

    verify_session = session_factory()
    verify_repo = SqlAlchemyAlertRepository(verify_session)
    all_events = verify_repo.list_events(symbol="SPY", limit=1000)
    verify_session.close()
    assert len(all_events) == 1
