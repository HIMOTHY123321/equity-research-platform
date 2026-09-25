"""§48 (non-negotiable): AlertEvent generation can only use evidence
available at AlertEvent.evaluated_at. AlertService itself does no lookahead
work -- emit_transition_alert is a pure function of an already-computed
DecisionPlan/DecisionTransition pair -- so this test proves the guarantee
transfers end to end: two AlertEvents built from the "short" (candles
truncated at T) and "long" (future candles appended) fixture runs used in
tests/unit/decision_engine/test_fixtures.py's own anti-lookahead spot check
must be identical in every field a future event could have tainted.
"""

from __future__ import annotations

from datetime import timedelta

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin
from app.alerts.service import AlertService, transition_alert_type
from app.decision_engine.fixtures import (
    FIXTURE_SCENARIOS,
    _FixtureProvider,
    build_fixture_plan,
    fixture_provider,
    fixture_snapshot_at,
)
from app.decision_engine.service import evaluate_plan
from app.schemas.market_data import Candle, MarketSession, Timeframe
from tests.unit.ai_analysis.conftest import make_session


def test_alert_generated_at_t_is_identical_regardless_of_future_candles():
    scenario = FIXTURE_SCENARIOS["strengthen_invalidate"]
    t = scenario.steps[0].as_of
    plan = build_fixture_plan(scenario, t)

    short_provider = fixture_provider(scenario)
    snapshot_short = fixture_snapshot_at(scenario, t, short_provider)
    result_short = evaluate_plan(plan, snapshot_short, t)

    extra_future_candle = Candle(
        symbol=scenario.symbol,
        timeframe=Timeframe.ONE_DAY,
        timestamp=scenario.candles[-1].timestamp + timedelta(days=30),
        session=MarketSession.REGULAR,
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=9_999_999.0,
    )
    long_provider = _FixtureProvider(scenario.symbol, [*scenario.candles, extra_future_candle])
    snapshot_long = fixture_snapshot_at(scenario, t, long_provider)
    result_long = evaluate_plan(plan, snapshot_long, t)

    assert [tr.to_state for tr in result_short.transitions] == [tr.to_state for tr in result_long.transitions]
    assert len(result_short.transitions) > 0, (
        "fixture must actually produce a transition at T for this to prove anything"
    )

    service_short = AlertService(SqlAlchemyAlertRepository(make_session()))
    service_long = AlertService(SqlAlchemyAlertRepository(make_session()))

    for tr_short, tr_long in zip(result_short.transitions, result_long.transitions):
        if transition_alert_type(tr_short) is None:
            continue
        alert_short = service_short.emit_transition_alert(
            result_short.plan, tr_short, origin=AlertOrigin.LIVE_PROSPECTIVE
        )
        alert_long = service_long.emit_transition_alert(
            result_long.plan, tr_long, origin=AlertOrigin.LIVE_PROSPECTIVE
        )
        assert alert_short is not None and alert_long is not None
        # Every field a future candle could have tainted (severity/title/
        # summary/state/trigger condition ids) must match exactly.
        # alert_id/created_at/evaluated_at are per-call generated, not
        # derived from evidence; transition_id/dedup_key embed a fresh
        # random uuid from build_transition on every call (same non-issue
        # as alert_id) -- excluded for the same reason, not because they
        # could legitimately differ due to a future-data leak.
        excluded = {"alert_id", "created_at", "evaluated_at", "transition_id", "dedup_key"}
        assert alert_short.model_dump(exclude=excluded) == alert_long.model_dump(exclude=excluded)
