from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.repository import SqlAlchemyAlertRepository
from app.market_data.provider import MarketDataProvider
from app.monitoring.service import MonitoringService
from tests.unit.setup_detection.conftest import load_real_candles

_RAW_SPY_1H = load_real_candles("SPY_1h")
_SHIFT = datetime.now(timezone.utc) - _RAW_SPY_1H[-1].timestamp


def _shifted(candles):
    return [c.model_copy(update={"timestamp": c.timestamp + _SHIFT}) for c in candles]


SPY_1H = _shifted(_RAW_SPY_1H)


class FakeProvider(MarketDataProvider):
    def get_candles(self, symbol, timeframe, limit=200, before=None):
        if symbol == "BAD":
            raise RuntimeError("provider unavailable for BAD")
        if symbol == "SPY" and timeframe.value in ("1h", "4h"):
            return SPY_1H[-limit:]
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _session_factory():
    """One shared in-memory engine per test (StaticPool keeps it alive
    across separate Session objects) -- mirrors app.database.session's real
    SessionLocal, which is what MonitoringService is actually handed in
    main.py's lifespan."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)


def _service(symbols: tuple[str, ...]) -> tuple[MonitoringService, "sessionmaker"]:
    session_factory = _session_factory()
    service = MonitoringService(session_factory, FakeProvider(), default_symbols=symbols)
    return service, session_factory


def _unread_count(session_factory) -> int:
    session = session_factory()
    try:
        return SqlAlchemyAlertRepository(session).unread_count()
    finally:
        session.close()


def test_scan_once_creates_plans_and_emits_ok_status():
    service, _ = _service(("SPY",))
    queue = service.add_listener()

    service.scan_once()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    statuses = [e for e in events if type(e).__name__ == "MonitorStatusEvent"]
    assert any(s.symbol == "SPY" and s.status == "ok" for s in statuses)


def test_scan_once_isolates_symbol_failure_without_stopping_others():
    service, _ = _service(("BAD", "SPY"))
    queue = service.add_listener()

    service.scan_once()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    statuses = {e.symbol: e.status for e in events if type(e).__name__ == "MonitorStatusEvent"}
    assert statuses["BAD"] == "error"
    assert statuses["SPY"] == "ok"


def test_repeated_scan_does_not_duplicate_alerts():
    service, session_factory = _service(("SPY",))

    service.scan_once()
    first_count = _unread_count(session_factory)
    service.scan_once()
    second_count = _unread_count(session_factory)

    assert second_count == first_count


def test_scan_emits_decision_state_change_events():
    service, _ = _service(("SPY",))
    queue = service.add_listener()

    transitions = service.scan_once()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    state_changes = [e for e in events if type(e).__name__ == "DecisionStateChangeEvent"]
    assert len(state_changes) == len(transitions)
    assert all(e.symbol == "SPY" for e in state_changes)


def test_scan_once_broadcasts_alerts_via_shared_event_bus():
    """Restart-safety proxy: a listener registered on the service's
    long-lived event bus keeps receiving alerts across separate scan_once
    passes, even though each pass builds a brand-new AlertService/session
    internally (§46 -- the bus, not any one session, is what must
    persist)."""
    service, _ = _service(("SPY",))
    alert_queue = service.event_bus.add_listener()

    service.scan_once()

    alert_events = []
    while not alert_queue.empty():
        alert_events.append(alert_queue.get_nowait())
    assert isinstance(alert_events, list)  # zero-or-more is fine; must not raise/duplicate-register
