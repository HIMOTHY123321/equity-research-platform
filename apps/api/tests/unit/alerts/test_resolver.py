"""Phase 14.1 (§33): the prospective outcome resolver -- the one place
future data is allowed to enter the alerts package."""

from __future__ import annotations

from datetime import timedelta

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.resolver import resolve_alert_horizon_outcomes, resolve_alert_outcome
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.decision_engine.state_machine import build_transition
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Candle, MarketSession, Timeframe
from tests.unit.ai_analysis.conftest import make_session
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


def _repos():
    session = make_session()
    return SqlAlchemyAlertRepository(session), SqlAlchemyDecisionEngineRepository(session)


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
        occurred_at=_START + timedelta(minutes=5 * 5),  # index 5
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


def test_returns_none_when_insufficient_future_data():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    candles = [_candle(i, 100.0 + i) for i in range(10)]  # only 4 bars after index 5
    provider = _FakeProvider(candles)

    outcome = resolve_alert_outcome(_alert(), decision_repo, alert_repo, provider)

    assert outcome is None


def test_resolves_with_full_horizon_available():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    # index 5 is the base (close=105); 25 more bars follow (indices 6..30),
    # rising by 1 each bar -- more than the 20-bar horizon needed.
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    outcome = resolve_alert_outcome(_alert(), decision_repo, alert_repo, provider)

    assert outcome is not None
    assert outcome.alert_id == "alert-1"
    # base close = 105 (index 5); 1-bar close = 106 -> +0.952%
    assert outcome.return_1_bar_percent is not None
    assert outcome.return_1_bar_percent > 0
    assert outcome.return_20_bar_percent is not None
    assert outcome.return_20_bar_percent > outcome.return_1_bar_percent  # steadily rising bullish series
    assert outcome.mfe_bars_until is not None


def test_dev_fixture_symbol_never_resolves_even_with_full_future_data():
    alert_repo, decision_repo = _repos()
    plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(update={"symbol": "ZFXA"})
    decision_repo.save_plan(plan)
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    outcome = resolve_alert_outcome(_alert(symbol="ZFXA"), decision_repo, alert_repo, provider)

    assert outcome is None


def test_returns_none_when_already_resolved():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)
    alert = _alert()

    first = resolve_alert_outcome(alert, decision_repo, alert_repo, provider)
    assert first is not None
    alert_repo.save_outcome(first)

    second = resolve_alert_outcome(alert, decision_repo, alert_repo, provider)
    assert second is None


def test_bars_to_invalidation_reads_off_the_plans_own_later_transition():
    alert_repo, decision_repo = _repos()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    decision_repo.save_plan(plan)
    invalidated_at = _START + timedelta(minutes=5 * 8)  # 3 bars after occurred_at (index 5 -> 8)
    transition = build_transition(
        plan, DecisionState.INVALIDATED, reason="broke support", as_of=invalidated_at
    )
    decision_repo.record_transition(transition)
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    outcome = resolve_alert_outcome(_alert(), decision_repo, alert_repo, provider)

    assert outcome is not None
    assert outcome.bars_to_invalidation == 3


# ------------------------------------------------------- per-horizon resolution


def test_only_horizons_with_enough_future_data_resolve():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    # occurred_at is index 5; only 6 bars follow (indices 6..11) -- enough
    # for the 1/3/5-bar horizons, not enough for 10 or 20.
    candles = [_candle(i, 100.0 + i) for i in range(12)]
    provider = _FakeProvider(candles)

    outcomes = resolve_alert_horizon_outcomes(_alert(), decision_repo, alert_repo, provider)

    resolved_horizons = {o.horizon_bars for o in outcomes}
    assert resolved_horizons == {1, 3, 5}


def test_repeated_calls_only_resolve_newly_available_horizons():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    candles = [_candle(i, 100.0 + i) for i in range(12)]
    provider = _FakeProvider(candles)
    alert = _alert()

    first_pass = resolve_alert_horizon_outcomes(alert, decision_repo, alert_repo, provider)
    for outcome in first_pass:
        alert_repo.save_horizon_outcome(outcome)
    assert {o.horizon_bars for o in first_pass} == {1, 3, 5}

    # No new bars arrived -- a second pass must not re-offer already-
    # resolved horizons (exactly-once per (alert_id, horizon_bars)).
    second_pass = resolve_alert_horizon_outcomes(alert, decision_repo, alert_repo, provider)
    assert second_pass == []

    # More bars arrive -- now 10 and 20 become resolvable too, while 1/3/5
    # are correctly skipped as already-resolved.
    more_candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider_more = _FakeProvider(more_candles)
    third_pass = resolve_alert_horizon_outcomes(alert, decision_repo, alert_repo, provider_more)
    assert {o.horizon_bars for o in third_pass} == {10, 20}


def test_horizon_outcomes_are_never_rewritten_once_saved():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)
    alert = _alert()

    outcomes = resolve_alert_horizon_outcomes(alert, decision_repo, alert_repo, provider)
    one_bar = next(o for o in outcomes if o.horizon_bars == 1)
    stored_first, created_first = alert_repo.save_horizon_outcome(one_bar)
    assert created_first is True

    stored_second, created_second = alert_repo.save_horizon_outcome(one_bar)
    assert created_second is False
    assert stored_second == stored_first


def test_dev_fixture_symbol_never_resolves_any_horizon():
    alert_repo, decision_repo = _repos()
    plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(update={"symbol": "ZFXA"})
    decision_repo.save_plan(plan)
    candles = [_candle(i, 100.0 + i) for i in range(31)]
    provider = _FakeProvider(candles)

    outcomes = resolve_alert_horizon_outcomes(_alert(symbol="ZFXA"), decision_repo, alert_repo, provider)

    assert outcomes == []
