from __future__ import annotations

import uuid

from app.decision_engine.conditions import ConditionContext, evaluate
from app.decision_engine.schemas import (
    BarSemantics,
    ConditionOperator,
    ConditionRole,
    ConditionStatus,
    ConditionType,
    DecisionCondition,
)
from app.schemas.market_data import Timeframe
from tests.unit.decision_engine.conftest import spy_snapshot


def make_condition(
    type_,
    *,
    required_value=None,
    operator=ConditionOperator.GTE,
    timeframe=Timeframe.ONE_HOUR,
    bar_semantics=BarSemantics.COMPLETED_BAR,
):
    return DecisionCondition(
        id=str(uuid.uuid4()),
        role=ConditionRole.ENTRY,
        type=type_,
        description="test condition",
        timeframe=timeframe,
        bar_semantics=bar_semantics,
        operator=operator,
        required_value=required_value,
        status=ConditionStatus.PENDING,
    )


def test_close_above_passes_when_completed_close_exceeds_level():
    snapshot = spy_snapshot()
    close = snapshot.feature_snapshot.latest_candle.close
    condition = make_condition(ConditionType.CLOSE_ABOVE, required_value=close - 1.0)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED
    assert result.actual_value == close
    assert result.evaluated_at == snapshot.as_of


def test_close_above_fails_when_completed_close_below_level():
    snapshot = spy_snapshot()
    close = snapshot.feature_snapshot.latest_candle.close
    condition = make_condition(ConditionType.CLOSE_ABOVE, required_value=close + 1.0)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.FAILED


def test_price_above_marked_completed_bar_uses_close_not_live_price():
    # A price_above condition explicitly marked COMPLETED_BAR must never
    # evaluate against a forming/live price -- only the completed close
    # (see conditions.evaluate's docstring / §17 of the Phase 13 spec).
    snapshot = spy_snapshot()
    close = snapshot.feature_snapshot.latest_candle.close
    condition = make_condition(
        ConditionType.PRICE_ABOVE, required_value=close - 1.0, bar_semantics=BarSemantics.COMPLETED_BAR
    )
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED
    assert result.actual_value == close


def test_price_above_tick_semantics_uses_latest_price():
    snapshot = spy_snapshot()
    price = snapshot.feature_snapshot.session.latest_price
    condition = make_condition(
        ConditionType.PRICE_ABOVE, required_value=price - 1.0, bar_semantics=BarSemantics.TICK
    )
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED
    assert result.actual_value == price


def test_missing_required_value_is_unavailable_not_a_guess():
    snapshot = spy_snapshot()
    condition = make_condition(ConditionType.CLOSE_ABOVE, required_value=None)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.UNAVAILABLE
    assert result.actual_value is None


def test_level_hold_unavailable_when_no_zone_contains_the_level():
    snapshot = spy_snapshot()
    condition = make_condition(ConditionType.LEVEL_HOLD, required_value=-999999.0)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.UNAVAILABLE


def test_level_hold_passes_for_an_unbroken_zone():
    snapshot = spy_snapshot()
    zone = snapshot.levels_snapshot.nearest_support
    assert zone is not None
    condition = make_condition(ConditionType.LEVEL_HOLD, required_value=zone.representative_price)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED


def test_rvol_above_reads_feature_snapshot_relative_volume():
    snapshot = spy_snapshot()
    rvol = snapshot.feature_snapshot.volume.relative_volume
    if rvol is None:
        condition = make_condition(ConditionType.RVOL_ABOVE, required_value=0.0)
        ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)
        assert evaluate(condition, ctx).status == ConditionStatus.UNAVAILABLE
        return
    condition = make_condition(ConditionType.RVOL_ABOVE, required_value=rvol - 0.01)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED
    assert result.actual_value == rvol


def test_catalyst_present_unavailable_without_catalyst_context():
    snapshot = spy_snapshot()
    condition = make_condition(ConditionType.CATALYST_PRESENT, operator=ConditionOperator.PRESENT)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of, catalyst_context=None)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.UNAVAILABLE


def test_time_elapsed_unavailable_without_monitoring_start():
    snapshot = spy_snapshot()
    condition = make_condition(ConditionType.TIME_ELAPSED, required_value=60.0)
    ctx = ConditionContext(snapshot=snapshot, as_of=snapshot.as_of, monitoring_started_at=None)

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.UNAVAILABLE


def test_time_elapsed_passes_once_threshold_reached():
    snapshot = spy_snapshot()
    from datetime import timedelta

    condition = make_condition(ConditionType.TIME_ELAPSED, required_value=30.0)
    ctx = ConditionContext(
        snapshot=snapshot, as_of=snapshot.as_of, monitoring_started_at=snapshot.as_of - timedelta(minutes=60)
    )

    result = evaluate(condition, ctx)

    assert result.status == ConditionStatus.PASSED
    assert result.actual_value == 60.0
