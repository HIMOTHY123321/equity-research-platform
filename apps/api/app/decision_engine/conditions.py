"""Deterministic evaluation of the 22 typed condition kinds (§4 of the
Phase 13 spec) against the SAME canonical snapshot objects every other
subsystem already computes (app.ai_analysis.market_snapshot.MarketSnapshot
plus an optional catalyst context) -- no new computation engine is built
here, only reading off already-produced deterministic facts.

Every evaluator returns a NEW DecisionCondition (input conditions are
frozen) with `status`/`actual_value`/`evaluated_at` filled in. A condition
whose required snapshot data is missing becomes UNAVAILABLE, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.ai_analysis.market_snapshot import MarketSnapshot
from app.decision_engine.schemas import (
    BarSemantics,
    ConditionOperator,
    ConditionStatus,
    ConditionType,
    DecisionCondition,
)
from app.market_structure.schemas import Direction, TrendClass
from app.news.schemas import SetupCatalystContext, SetupCatalystContextLabel
from app.support_resistance.schemas import Zone, ZoneLifecycle

_TREND_CODE: dict[TrendClass, float] = {
    TrendClass.BEARISH: -1.0,
    TrendClass.RANGING: 0.0,
    TrendClass.BULLISH: 1.0,
    TrendClass.INSUFFICIENT_DATA: -2.0,
}


@dataclass(frozen=True)
class ConditionContext:
    """Everything a single condition evaluation might need, beyond the
    shared MarketSnapshot -- kept separate rather than widening
    MarketSnapshot itself, since these are Decision-Engine-specific
    concerns (catalyst presence, elapsed monitoring time)."""

    snapshot: MarketSnapshot
    as_of: datetime
    catalyst_context: Optional[SetupCatalystContext] = None
    monitoring_started_at: Optional[datetime] = None


def _unavailable(condition: DecisionCondition, as_of: datetime) -> DecisionCondition:
    return condition.model_copy(update={"status": ConditionStatus.UNAVAILABLE, "evaluated_at": as_of})


def _compare(actual: float, operator: ConditionOperator, required: float) -> bool:
    if operator == ConditionOperator.GTE:
        return actual >= required
    if operator == ConditionOperator.LTE:
        return actual <= required
    if operator == ConditionOperator.GT:
        return actual > required
    if operator == ConditionOperator.LT:
        return actual < required
    if operator == ConditionOperator.EQ:
        return actual == required
    raise ValueError(f"Operator {operator} requires a numeric comparison but received one of PRESENT/ABSENT")


def _resolved(
    condition: DecisionCondition, as_of: datetime, actual_value: Optional[float], passed: Optional[bool]
) -> DecisionCondition:
    if actual_value is None or passed is None:
        return _unavailable(condition, as_of)
    return condition.model_copy(
        update={
            "status": ConditionStatus.PASSED if passed else ConditionStatus.FAILED,
            "actual_value": actual_value,
            "evaluated_at": as_of,
        }
    )


def _latest_price(snapshot: MarketSnapshot) -> Optional[float]:
    session = snapshot.feature_snapshot.session
    if session.latest_price is not None:
        return session.latest_price
    return snapshot.feature_snapshot.latest_candle.close


def _completed_close(snapshot: MarketSnapshot) -> Optional[float]:
    return snapshot.feature_snapshot.latest_candle.close


def _zone_containing(zones: list[Zone], price: float) -> Optional[Zone]:
    for zone in zones:
        if zone.lower_bound <= price <= zone.upper_bound:
            return zone
    return None


def _eval_price_above(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    price = _latest_price(ctx.snapshot)
    if price is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, price, price >= c.required_value)


def _eval_price_below(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    price = _latest_price(ctx.snapshot)
    if price is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, price, price <= c.required_value)


def _eval_close_above(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    close = _completed_close(ctx.snapshot)
    if close is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, close, close >= c.required_value)


def _eval_close_below(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    close = _completed_close(ctx.snapshot)
    if close is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, close, close <= c.required_value)


def _all_zones(ctx: ConditionContext) -> list[Zone]:
    levels = ctx.snapshot.levels_snapshot
    return [*levels.active_support_zones, *levels.active_resistance_zones]


def _eval_level_hold(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    if c.required_value is None:
        return _unavailable(c, ctx.as_of)
    zone = _zone_containing(_all_zones(ctx), c.required_value)
    if zone is None:
        return _unavailable(c, ctx.as_of)
    holding = zone.lifecycle != ZoneLifecycle.BROKEN
    return _resolved(c, ctx.as_of, zone.representative_price, holding)


def _eval_level_reclaim(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    price = _latest_price(ctx.snapshot)
    if price is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    try:
        passed = _compare(price, c.operator, c.required_value)
    except ValueError:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, price, passed)


def _eval_level_rejection(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    candle = ctx.snapshot.feature_snapshot.latest_candle
    if candle.high is None or candle.low is None or candle.close is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    level = c.required_value
    if c.operator == ConditionOperator.LT:
        # Rejection from above: price reached the level but closed back below it.
        touched = candle.high >= level
        passed = touched and candle.close < level
    elif c.operator == ConditionOperator.GT:
        # Rejection from below: price reached the level but closed back above it.
        touched = candle.low <= level
        passed = touched and candle.close > level
    else:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, candle.close, passed)


def _structure_for(c: DecisionCondition, ctx: ConditionContext):
    return ctx.snapshot.structure_by_timeframe.get(c.timeframe)


def _eval_breakout_confirmed(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    structure = _structure_for(c, ctx)
    if structure is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    tolerance = abs(c.required_value) * 0.001
    matches = [
        b for b in structure.breaks_of_structure if abs(b.broken_level - c.required_value) <= tolerance
    ]
    return _resolved(c, ctx.as_of, float(len(matches)), len(matches) > 0)


def _eval_retest_confirmed(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    if c.required_value is None:
        return _unavailable(c, ctx.as_of)
    zone = _zone_containing(_all_zones(ctx), c.required_value)
    if zone is None:
        return _unavailable(c, ctx.as_of)
    retests = [i for i in zone.interactions if i.interaction_type.value in ("touch", "rejection")]
    return _resolved(c, ctx.as_of, float(len(retests)), len(retests) > 0)


def _eval_structure_bos(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    structure = _structure_for(c, ctx)
    if structure is None:
        return _unavailable(c, ctx.as_of)
    required_direction = Direction.BULLISH if c.required_value == 1.0 else Direction.BEARISH
    matches = [b for b in structure.breaks_of_structure if b.direction == required_direction]
    return _resolved(c, ctx.as_of, float(len(matches)), len(matches) > 0)


def _eval_structure_choch(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    structure = _structure_for(c, ctx)
    if structure is None:
        return _unavailable(c, ctx.as_of)
    required_direction = Direction.BULLISH if c.required_value == 1.0 else Direction.BEARISH
    matches = [ch for ch in structure.changes_of_character if ch.direction == required_direction]
    return _resolved(c, ctx.as_of, float(len(matches)), len(matches) > 0)


def _eval_trend_alignment(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    structure = _structure_for(c, ctx)
    if structure is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    actual_code = _TREND_CODE[structure.trend.trend]
    return _resolved(c, ctx.as_of, actual_code, actual_code == c.required_value)


def _eval_rvol_above(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    rvol = ctx.snapshot.feature_snapshot.volume.relative_volume
    if rvol is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, rvol, rvol >= c.required_value)


def _eval_rvol_below(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    rvol = ctx.snapshot.feature_snapshot.volume.relative_volume
    if rvol is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, rvol, rvol <= c.required_value)


def _eval_volume_confirmation(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    rvol = ctx.snapshot.feature_snapshot.volume.relative_volume
    if rvol is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, rvol, rvol >= c.required_value)


def _eval_support_holds(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    zone = ctx.snapshot.levels_snapshot.nearest_support
    if zone is None:
        return _unavailable(c, ctx.as_of)
    holding = zone.lifecycle != ZoneLifecycle.BROKEN
    return _resolved(c, ctx.as_of, zone.representative_price, holding)


def _eval_resistance_holds(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    zone = ctx.snapshot.levels_snapshot.nearest_resistance
    if zone is None:
        return _unavailable(c, ctx.as_of)
    holding = zone.lifecycle != ZoneLifecycle.BROKEN
    return _resolved(c, ctx.as_of, zone.representative_price, holding)


def _gap_filled_percent(ctx: ConditionContext) -> Optional[float]:
    gap = ctx.snapshot.feature_snapshot.gap
    price = _latest_price(ctx.snapshot)
    if gap.session_open is None or gap.gap_absolute is None or price is None or gap.gap_absolute == 0:
        return None
    return abs(price - gap.session_open) / abs(gap.gap_absolute) * 100.0


def _eval_gap_fill_threshold(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    filled = _gap_filled_percent(ctx)
    if filled is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, filled, filled >= c.required_value)


def _eval_gap_hold_threshold(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    filled = _gap_filled_percent(ctx)
    if filled is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, filled, filled <= c.required_value)


def _eval_volatility_regime(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    atr = ctx.snapshot.feature_snapshot.atr.value
    if atr is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    try:
        passed = _compare(atr, c.operator, c.required_value)
    except ValueError:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, atr, passed)


def _eval_catalyst_present(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    if ctx.catalyst_context is None:
        return _unavailable(c, ctx.as_of)
    present = ctx.catalyst_context.label != SetupCatalystContextLabel.NO_RECENT_CATALYST
    return _resolved(c, ctx.as_of, 1.0 if present else 0.0, present)


def _eval_catalyst_absent(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    if ctx.catalyst_context is None:
        return _unavailable(c, ctx.as_of)
    absent = ctx.catalyst_context.label == SetupCatalystContextLabel.NO_RECENT_CATALYST
    return _resolved(c, ctx.as_of, 1.0 if absent else 0.0, absent)


def _eval_time_elapsed(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    if ctx.monitoring_started_at is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    elapsed_minutes = (ctx.as_of - ctx.monitoring_started_at).total_seconds() / 60.0
    return _resolved(c, ctx.as_of, elapsed_minutes, elapsed_minutes >= c.required_value)


def _eval_session_condition(c: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    session = ctx.snapshot.feature_snapshot.data_quality.latest_candle_session
    if session is None or c.required_value is None:
        return _unavailable(c, ctx.as_of)
    from app.schemas.market_data import MarketSession

    ordering = list(MarketSession)
    try:
        actual_code = float(ordering.index(session))
    except ValueError:
        return _unavailable(c, ctx.as_of)
    return _resolved(c, ctx.as_of, actual_code, actual_code == c.required_value)


_EVALUATORS = {
    ConditionType.PRICE_ABOVE: _eval_price_above,
    ConditionType.PRICE_BELOW: _eval_price_below,
    ConditionType.CLOSE_ABOVE: _eval_close_above,
    ConditionType.CLOSE_BELOW: _eval_close_below,
    ConditionType.LEVEL_HOLD: _eval_level_hold,
    ConditionType.LEVEL_RECLAIM: _eval_level_reclaim,
    ConditionType.LEVEL_REJECTION: _eval_level_rejection,
    ConditionType.BREAKOUT_CONFIRMED: _eval_breakout_confirmed,
    ConditionType.RETEST_CONFIRMED: _eval_retest_confirmed,
    ConditionType.STRUCTURE_BOS: _eval_structure_bos,
    ConditionType.STRUCTURE_CHOCH: _eval_structure_choch,
    ConditionType.TREND_ALIGNMENT: _eval_trend_alignment,
    ConditionType.RVOL_ABOVE: _eval_rvol_above,
    ConditionType.RVOL_BELOW: _eval_rvol_below,
    ConditionType.VOLUME_CONFIRMATION: _eval_volume_confirmation,
    ConditionType.SUPPORT_HOLDS: _eval_support_holds,
    ConditionType.RESISTANCE_HOLDS: _eval_resistance_holds,
    ConditionType.GAP_FILL_THRESHOLD: _eval_gap_fill_threshold,
    ConditionType.GAP_HOLD_THRESHOLD: _eval_gap_hold_threshold,
    ConditionType.VOLATILITY_REGIME: _eval_volatility_regime,
    ConditionType.CATALYST_PRESENT: _eval_catalyst_present,
    ConditionType.CATALYST_ABSENT: _eval_catalyst_absent,
    ConditionType.TIME_ELAPSED: _eval_time_elapsed,
    ConditionType.SESSION_CONDITION: _eval_session_condition,
}


def evaluate(condition: DecisionCondition, ctx: ConditionContext) -> DecisionCondition:
    """Dispatches on `condition.type`. COMPLETED_BAR conditions never read a
    forming/live price -- close-based evaluators only ever read
    `feature_snapshot.latest_candle`, which is documented as being computed
    from the latest *completed* candle (see app.features.schemas.
    CandleFeatures), never a still-forming bar."""
    if condition.bar_semantics == BarSemantics.COMPLETED_BAR and condition.type in (
        ConditionType.PRICE_ABOVE,
        ConditionType.PRICE_BELOW,
    ):
        # A price_above/price_below condition marked COMPLETED_BAR must use
        # the completed-bar close, not the live/forming price.
        evaluator = _eval_close_above if condition.type == ConditionType.PRICE_ABOVE else _eval_close_below
        return evaluator(condition, ctx)

    evaluator = _EVALUATORS.get(condition.type)
    if evaluator is None:
        return _unavailable(condition, ctx.as_of)
    return evaluator(condition, ctx)
