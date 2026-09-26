"""Phase 14.1 §8: end-to-end restart/recovery -- a genuine process restart
is simulated by throwing away every in-memory object (the MonitoringService
instance, its event bus, all repositories) and constructing entirely new
ones against the SAME on-disk database, exactly like a real backend
restart would. Everything that must survive is verified to survive, and
nothing that must stay exactly-once is duplicated.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.resolver import resolve_pending_outcomes
from app.market_data.provider import MarketDataProvider
from app.monitoring.service import MonitoringService
from app.monitoring.universe import MonitoringUniverse
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.watchlist.repository import InMemoryWatchlistRepository
from tests.unit.setup_detection.conftest import load_real_candles

_RAW_SPY_1H = load_real_candles("SPY_1h")
_SHIFT = datetime.now(timezone.utc) - _RAW_SPY_1H[-1].timestamp


def _shifted(candles):
    return [c.model_copy(update={"timestamp": c.timestamp + _SHIFT}) for c in candles]


SPY_1H = _shifted(_RAW_SPY_1H)


def _daily_candle(index: int, close: float) -> Candle:
    return Candle(
        symbol="AAPL",
        timeframe=Timeframe.ONE_DAY,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        session=MarketSession.REGULAR,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1_000_000.0,
    )


class _FakeProvider(MarketDataProvider):
    def get_candles(self, symbol, timeframe, limit=200, before=None):
        if symbol == "SPY" and timeframe.value in ("1h", "4h"):
            return SPY_1H[-limit:]
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _new_service(file_session_factory, db_path: Path, symbols: tuple[str, ...]) -> MonitoringService:
    """A brand-new MonitoringService, brand-new session_factory, brand-new
    watchlist repository, brand-new event bus -- nothing shared with any
    previously-constructed instance, exactly what a real process restart
    looks like. `file_session_factory` still tracks the fresh Engine this
    creates (against the SAME db_path) so it gets disposed at teardown."""
    session_factory = file_session_factory(db_path)
    watchlist = InMemoryWatchlistRepository(initial_symbols=symbols)
    return MonitoringService(session_factory, watchlist, _FakeProvider())


def test_alert_and_monitoring_state_all_survive_a_simulated_restart(file_session_factory):
    from app.alerts.schemas import AlertType

    db_path = Path(tempfile.mkdtemp()) / "restart_e2e.db"

    # Enable every transition alert type up front (WATCHING defaults off,
    # see DEFAULT_ALERT_PREFERENCES) so whichever state the real SPY
    # fixture reaches in one pass actually produces a recorded alert --
    # this test is about restart survival, not preference defaults.
    warm_session = file_session_factory(db_path)()
    warm_repo = SqlAlchemyAlertRepository(warm_session)
    for alert_type in AlertType:
        warm_repo.set_preference(alert_type, True)
    warm_session.close()

    # --- "before restart": first process lifetime -----------------------
    service_1 = _new_service(file_session_factory, db_path, ("SPY",))
    transitions_1 = service_1.scan_once()
    assert len(transitions_1) > 0, "fixture must produce at least one transition for this to prove anything"

    session_1 = file_session_factory(db_path)()
    alert_repo_1 = SqlAlchemyAlertRepository(session_1)
    alerts_before = alert_repo_1.list_events(symbol="SPY", limit=1000)
    assert len(alerts_before) > 0
    unread_before = alert_repo_1.unread_count(symbol="SPY")
    assert unread_before == len(alerts_before)
    # Acknowledge one -- read state must survive the restart too.
    alert_repo_1.acknowledge(alerts_before[0].alert_id, acknowledged_at=datetime.now(timezone.utc))
    assert alert_repo_1.unread_count(symbol="SPY") == unread_before - 1
    session_1.close()

    # --- "restart": every in-memory object above is discarded here ------
    service_2 = _new_service(file_session_factory, db_path, ("SPY",))
    service_2.scan_once()  # same state re-evaluated

    session_2 = file_session_factory(db_path)()
    alert_repo_2 = SqlAlchemyAlertRepository(session_2)
    alerts_after = alert_repo_2.list_events(symbol="SPY", limit=1000)

    # No duplicate alert: re-evaluating the same already-reached state
    # after "restart" must not add new rows for transitions already seen.
    assert len(alerts_after) == len(alerts_before)
    # Unread state survived the restart.
    assert alert_repo_2.unread_count(symbol="SPY") == unread_before - 1
    session_2.close()


def test_monitoring_subscription_survives_a_simulated_restart(file_session_factory):
    db_path = Path(tempfile.mkdtemp()) / "restart_monitoring_e2e.db"

    watchlist = InMemoryWatchlistRepository(initial_symbols=("SPY", "NVDA"))

    session_1 = file_session_factory(db_path)()
    alert_repo_1 = SqlAlchemyAlertRepository(session_1)
    universe_1 = MonitoringUniverse(alert_repo_1, watchlist)
    universe_1.disable("NVDA")
    assert universe_1.list_enabled_symbols() == ["SPY"]
    session_1.close()

    # "restart": brand-new session/repository/universe over the same file.
    session_2 = file_session_factory(db_path)()
    alert_repo_2 = SqlAlchemyAlertRepository(session_2)
    universe_2 = MonitoringUniverse(alert_repo_2, watchlist)
    assert universe_2.list_enabled_symbols() == ["SPY"]  # NVDA's disabled state persisted
    session_2.close()


def test_resolved_prospective_observation_survives_restart_and_is_not_reresolved(file_session_factory):
    db_path = Path(tempfile.mkdtemp()) / "restart_resolution_e2e.db"

    from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
    from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
    from app.decision_engine.schemas import DecisionState
    from tests.unit.decision_engine.test_state_machine import make_plan

    class _AAPLProvider(MarketDataProvider):
        def get_candles(self, symbol, timeframe, limit=200, before=None):
            return [_daily_candle(i, 100.0 + i) for i in range(31)][-limit:]

        def get_latest_quote(self, symbol):
            raise NotImplementedError

        def get_previous_close(self, symbol):
            raise NotImplementedError

    occurred_at = datetime(2026, 1, 6, tzinfo=timezone.utc)

    session_1 = file_session_factory(db_path)()
    SqlAlchemyDecisionEngineRepository(session_1).save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    SqlAlchemyAlertRepository(session_1).record_event(
        AlertEvent(
            alert_id="alert-1",
            symbol="AAPL",
            decision_plan_id="plan-1",
            setup_id="setup-1",
            alert_type=AlertType.ENTRY_CONDITIONS_MET,
            severity=AlertSeverity.IMPORTANT,
            title="Entry conditions met",
            summary="All predefined entry conditions are now satisfied",
            occurred_at=occurred_at,
            evaluated_at=occurred_at,
            timeframe="1d",
            dedup_key="dedup-1",
            origin=AlertOrigin.LIVE_PROSPECTIVE,
            pipeline_version="test",
            created_at=occurred_at,
        )
    )
    session_1.close()

    session_2 = file_session_factory(db_path)()
    resolved_1 = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(session_2), SqlAlchemyDecisionEngineRepository(session_2), _AAPLProvider()
    )
    session_2.close()
    assert len(resolved_1) == 1

    # "restart": brand-new session/repositories over the same file.
    session_3 = file_session_factory(db_path)()
    resolved_2 = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(session_3), SqlAlchemyDecisionEngineRepository(session_3), _AAPLProvider()
    )
    session_3.close()
    assert resolved_2 == []  # no second resolution written

    session_4 = file_session_factory(db_path)()
    decision_repo = SqlAlchemyDecisionEngineRepository(session_4)
    assert SqlAlchemyAlertRepository(session_4).count_resolved_prospective_observations(decision_repo) == 1
    session_4.close()
