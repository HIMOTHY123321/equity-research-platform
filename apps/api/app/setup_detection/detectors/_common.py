"""Shared plumbing every detector uses to turn a set of evidence checks into
a fully-formed SetupCandidate -- kept here instead of duplicated 15 times.
Multi-stage detectors (breakout_retest, failed breakouts, gap_fill) build
their own transition sequences inline, since those state machines are
genuinely different from the single-transition case this module covers
(see docs/decisions/0007 on not combining distinct behaviors).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.market_data.sessions import exchange_trading_date
from app.market_structure.common import TIMEFRAME_DURATION
from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.context import DetectorInputs, build_setup_context
from app.setup_detection.fingerprint import build_fingerprint
from app.setup_detection.ids import setup_candidate_id
from app.setup_detection.lifecycle import compute_expires_at, transition
from app.setup_detection.qualification import failed_hard_checks, is_qualified
from app.setup_detection.schemas import (
    BreakoutConfirmation,
    ConflictCheck,
    EvidenceCheck,
    SetupCandidate,
    SetupLifecycleState,
    SetupType,
)


def bar_duration_seconds(timeframe: Timeframe) -> float:
    if timeframe == Timeframe.ONE_DAY:
        return timedelta(days=1).total_seconds()
    duration = TIMEFRAME_DURATION.get(timeframe)
    if duration is None:
        raise ValueError(f"No known duration for timeframe {timeframe.value}")
    return duration.total_seconds()


def build_resolved_candidate(
    inputs: DetectorInputs,
    setup_type: SetupType,
    direction: Direction,
    candidate_candle_timestamp: datetime,
    reference_price: Optional[float],
    reference_source: Optional[str],
    reference_timestamp: Optional[datetime],
    reference_key: str,
    hard_checks: list[EvidenceCheck],
    soft_checks: list[EvidenceCheck],
    conflicts: list[ConflictCheck],
    invalidation_criteria: list[str],
    confirmation: Optional[BreakoutConfirmation] = None,
    metadata: Optional[dict] = None,
) -> SetupCandidate:
    """The common case: a single completed candle both creates the
    candidate and immediately resolves it to QUALIFIED or REJECTED --
    appropriate for any detector whose trigger condition is itself the
    confirmation (a completed close beyond a level, a completed rejection
    interaction, etc). Multi-stage detectors don't use this."""
    qualified = is_qualified(hard_checks)
    candidate_id = setup_candidate_id(
        inputs.symbol, setup_type, direction, inputs.timeframe, reference_key, candidate_candle_timestamp
    )

    transitions = [
        transition(
            SetupLifecycleState.CANDIDATE,
            candidate_candle_timestamp,
            "candidate_detected",
            f"{setup_type.value} candidate detected",
        )
    ]
    if qualified:
        transitions.append(
            transition(
                SetupLifecycleState.QUALIFIED,
                candidate_candle_timestamp,
                "hard_rules_satisfied",
                "All hard requirements satisfied",
            )
        )
        state = SetupLifecycleState.QUALIFIED
        expires_at = compute_expires_at(
            candidate_candle_timestamp, setup_type, bar_duration_seconds(inputs.timeframe), inputs.config
        )
    else:
        failed = failed_hard_checks(hard_checks)
        reason = "; ".join(check.label for check in failed) or "hard rule failed"
        transitions.append(
            transition(SetupLifecycleState.REJECTED, candidate_candle_timestamp, "hard_rule_failed", reason)
        )
        state = SetupLifecycleState.REJECTED
        expires_at = None

    context = build_setup_context(inputs)
    fingerprint = build_fingerprint(
        setup_type=setup_type,
        direction=direction,
        context=context,
        reference_price=reference_price,
        support_confluence=len(inputs.levels_snapshot.active_support_zones),
        resistance_confluence=len(inputs.levels_snapshot.active_resistance_zones),
        min_gap_percent=inputs.config.min_gap_percent_for_continuation,
    )

    return SetupCandidate(
        id=candidate_id,
        symbol=inputs.symbol,
        timeframe=inputs.timeframe,
        setup_type=setup_type,
        direction=direction,
        reference_price=reference_price,
        reference_source=reference_source,
        reference_timestamp=reference_timestamp,
        confirmation=confirmation,
        candidate_candle_timestamp=candidate_candle_timestamp,
        created_at=candidate_candle_timestamp,
        current_state=state,
        transitions=transitions,
        hard_checks=hard_checks,
        soft_checks=soft_checks,
        conflicts=conflicts,
        invalidation_criteria=invalidation_criteria,
        context=context,
        fingerprint=fingerprint,
        expires_at=expires_at,
        metadata=metadata or {},
    )


def within_lookback(candidate_candle_timestamp: datetime, candles: list, lookback_bars: int) -> bool:
    """True if `candidate_candle_timestamp` falls within the last
    `lookback_bars` completed candles -- bounds how far back a brand-new
    candidate can be created from (#29/#40), independent of how much
    history a detector reads to find its reference level."""
    if not candles:
        return False
    window = candles[-lookback_bars:]
    return any(c.timestamp == candidate_candle_timestamp for c in window)


def after_previous_day(candle_timestamp: datetime, previous_day_trading_date) -> bool:
    """Anti-lookahead guard (#35): `FeatureSnapshot.previous_day` is a
    single value anchored to `as_of` (whatever "yesterday" means right
    now) -- it is only a valid reference for candles on or after the very
    next trading day. A candle from further back predates that "yesterday"
    entirely, so comparing it against this level would be lookahead (a
    real bug found this way against live SPY data: a candle three days
    before `as_of` was being checked against a PDH that didn't exist yet).
    """
    if previous_day_trading_date is None:
        return False
    return exchange_trading_date(candle_timestamp) > previous_day_trading_date


def after_previous_week(candle_timestamp: datetime, previous_week_end_date) -> bool:
    """Same guard as `after_previous_day`, for `FeatureSnapshot.previous_week`."""
    if previous_week_end_date is None:
        return False
    return (
        exchange_trading_date(candle_timestamp).isocalendar()[:2] > previous_week_end_date.isocalendar()[:2]
    )
