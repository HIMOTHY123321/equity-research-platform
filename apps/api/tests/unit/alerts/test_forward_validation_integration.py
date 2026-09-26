"""Phase 14.1 §5: only RESOLVED eligible prospective alerts count toward
Forward Validation -- creating an alert alone must never increment the
count, repeated resolver passes never duplicate an outcome, and a
process-restart-simulating fresh repository/session pair over the same
on-disk DB never produces a duplicate resolved observation either.
"""

from __future__ import annotations

from datetime import timedelta

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.resolver import resolve_pending_outcomes
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Candle, MarketSession, Timeframe
from tests.unit.decision_engine.test_state_machine import make_plan, utc

_START = utc(2026, 1, 1)


def _candle(index: int, close: float) -> Candle:
    return Candle(
        symbol="AAPL",
        timeframe=Timeframe.FIVE_MIN,
        timestamp=_START + timedelta(minutes=5 * index),
        session=MarketSession.REGULAR,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1_000_000.0,
    )


class _FakeProvider(MarketDataProvider):
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        return self._candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _alert(**overrides) -> AlertEvent:
    fields = dict(
        alert_id="alert-1",
        symbol="AAPL",
        decision_plan_id="plan-1",
        setup_id="setup-1",
        alert_type=AlertType.ENTRY_CONDITIONS_MET,
        severity=AlertSeverity.IMPORTANT,
        title="Entry conditions met",
        summary="All predefined entry conditions are now satisfied",
        occurred_at=_START + timedelta(minutes=5 * 5),
        evaluated_at=_START + timedelta(minutes=5 * 5),
        timeframe="5m",
        setup_type="breakout_retest",
        direction="bullish",
        dedup_key="dedup-1",
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=_START + timedelta(minutes=5 * 5),
    )
    fields.update(overrides)
    return AlertEvent(**fields)


def test_alert_created_has_zero_resolved_observations_before_horizon_completes(file_session_factory):
    session_factory = file_session_factory()
    session = session_factory()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    session.close()

    verify_session = session_factory()
    verify_alert_repo = SqlAlchemyAlertRepository(verify_session)
    verify_decision_repo = SqlAlchemyDecisionEngineRepository(verify_session)
    assert verify_alert_repo.count_prospective_observations(verify_decision_repo) == 1
    assert verify_alert_repo.count_resolved_prospective_observations(verify_decision_repo) == 0
    verify_session.close()


def test_resolver_pass_after_horizon_completes_produces_exactly_one_resolved_observation(
    file_session_factory,
):
    session_factory = file_session_factory()
    session = session_factory()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    session.close()

    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    resolve_session = session_factory()
    resolved = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(resolve_session),
        SqlAlchemyDecisionEngineRepository(resolve_session),
        provider,
    )
    resolve_session.close()

    assert len(resolved) == 1

    verify_session = session_factory()
    verify_alert_repo = SqlAlchemyAlertRepository(verify_session)
    verify_decision_repo = SqlAlchemyDecisionEngineRepository(verify_session)
    assert verify_alert_repo.count_resolved_prospective_observations(verify_decision_repo) == 1
    verify_session.close()


def test_resolver_pass_run_again_produces_no_duplicate(file_session_factory):
    session_factory = file_session_factory()
    session = session_factory()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    session.close()

    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    first_session = session_factory()
    first_resolved = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(first_session), SqlAlchemyDecisionEngineRepository(first_session), provider
    )
    first_session.close()
    assert len(first_resolved) == 1

    second_session = session_factory()
    second_resolved = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(second_session),
        SqlAlchemyDecisionEngineRepository(second_session),
        provider,
    )
    second_session.close()
    assert len(second_resolved) == 0

    verify_session = session_factory()
    verify_alert_repo = SqlAlchemyAlertRepository(verify_session)
    verify_decision_repo = SqlAlchemyDecisionEngineRepository(verify_session)
    assert verify_alert_repo.count_resolved_prospective_observations(verify_decision_repo) == 1
    verify_session.close()


def test_restart_simulated_by_fresh_session_over_same_db_produces_no_duplicate(file_session_factory):
    """A brand-new repository/session pair (nothing carried over in memory,
    exactly what a real process restart looks like) resolving the same
    already-resolved alert must not create a second outcome row."""
    session_factory = file_session_factory()
    session = session_factory()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    session.close()

    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    pre_restart_session = session_factory()
    resolve_pending_outcomes(
        SqlAlchemyAlertRepository(pre_restart_session),
        SqlAlchemyDecisionEngineRepository(pre_restart_session),
        provider,
    )
    pre_restart_session.close()

    # "restart": entirely new repository/session objects, same on-disk DB.
    post_restart_session = session_factory()
    post_restart_resolved = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(post_restart_session),
        SqlAlchemyDecisionEngineRepository(post_restart_session),
        provider,
    )
    post_restart_session.close()

    assert post_restart_resolved == []

    verify_session = session_factory()
    verify_alert_repo = SqlAlchemyAlertRepository(verify_session)
    verify_decision_repo = SqlAlchemyDecisionEngineRepository(verify_session)
    assert verify_alert_repo.count_resolved_prospective_observations(verify_decision_repo) == 1
    verify_session.close()


def test_dev_fixture_alerts_never_increment_prospective_or_resolved_counts(file_session_factory):
    session_factory = file_session_factory()
    session = session_factory()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    fixture_plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(
        update={"symbol": "ZFXA", "setup_id": "fixture:strengthen_invalidate"}
    )
    decision_repo.save_plan(fixture_plan)
    alert_repo.record_event(_alert(symbol="ZFXA", origin=AlertOrigin.DEV_FIXTURE))
    session.close()

    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    resolve_session = session_factory()
    resolved = resolve_pending_outcomes(
        SqlAlchemyAlertRepository(resolve_session),
        SqlAlchemyDecisionEngineRepository(resolve_session),
        provider,
    )
    resolve_session.close()
    assert resolved == []

    verify_session = session_factory()
    verify_alert_repo = SqlAlchemyAlertRepository(verify_session)
    verify_decision_repo = SqlAlchemyDecisionEngineRepository(verify_session)
    assert verify_alert_repo.count_prospective_observations(verify_decision_repo) == 0
    assert verify_alert_repo.count_resolved_prospective_observations(verify_decision_repo) == 0
    verify_session.close()
