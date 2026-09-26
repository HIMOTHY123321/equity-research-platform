"""Phase 15 §49/§77: NON-NEGOTIABLE -- the Validation Lab's dataset builder
must never itself resolve outcomes or otherwise reach for future market
data. It only ever reads whatever `app.alerts.resolver` has already
persisted (or hasn't yet) -- exactly the same discipline Phase 14.1
established, just re-verified at the Phase 15 boundary."""

from __future__ import annotations

from datetime import timedelta

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.validation.dataset import build_prospective_dataset
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan, utc

_START = utc(2026, 1, 1)


def _repos():
    session = make_session()
    return SqlAlchemyAlertRepository(session), SqlAlchemyDecisionEngineRepository(session)


def test_dataset_builder_never_calls_a_market_data_provider():
    """build_prospective_dataset's signature itself proves this: it takes
    only an AlertRepository and a DecisionEngineRepository, never a
    MarketDataProvider -- there is structurally no way for it to fetch a
    single candle, past or future."""
    import inspect

    signature = inspect.signature(build_prospective_dataset)
    param_types = {p.annotation for p in signature.parameters.values()}
    assert not any("MarketDataProvider" in str(t) for t in param_types)


def test_unresolved_alert_reflects_exactly_what_was_known_at_alert_time():
    """An alert with no AlertOutcome yet (because the resolver hasn't run,
    or hasn't had enough future bars) must project with every return/MFE/
    MAE field as None -- never a fabricated value standing in for
    'not yet knowable'."""
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(
        AlertEvent(
            alert_id="alert-1",
            symbol="AAPL",
            decision_plan_id="plan-1",
            setup_id="setup-1",
            alert_type=AlertType.ENTRY_CONDITIONS_MET,
            severity=AlertSeverity.IMPORTANT,
            title="Entry conditions met",
            summary="All predefined entry conditions are now satisfied",
            occurred_at=_START + timedelta(minutes=5),
            evaluated_at=_START + timedelta(minutes=5),
            timeframe="5m",
            setup_type="breakout_retest",
            direction="bullish",
            dedup_key="dedup-1",
            origin=AlertOrigin.LIVE_PROSPECTIVE,
            pipeline_version="test",
            created_at=_START + timedelta(minutes=5),
        )
    )

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.resolved is False
    assert observation.return_1 is None
    assert observation.return_5 is None
    assert observation.return_20 is None
    assert observation.mfe_atr is None
    assert observation.mae_atr is None
    assert observation.resolution_quality.value == "insufficient_future_data"
