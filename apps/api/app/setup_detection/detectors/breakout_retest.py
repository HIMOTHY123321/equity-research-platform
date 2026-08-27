"""Breakout + retest (#8) -- a genuinely sequential, two-stage pattern.
Modeled as a chronological walk, exactly like Phase 4's BOS simulation: the
system never "knows" a breakout will later be retested. A candidate is only
created once a retest has *actually occurred* in the data, at the retest
bar's own timestamp -- never backdated to the original breakout candle
(#3, #35).

Reference levels are the same previous-day/previous-week highs/lows the
single-stage breakout detectors use (#7) -- no separate level system.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_structure.schemas import Direction
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs, build_setup_context
from app.setup_detection.detectors._common import (
    after_previous_day,
    after_previous_week,
    bar_duration_seconds,
    within_lookback,
)
from app.setup_detection.evidence import check_close_beyond_level, check_rvol
from app.setup_detection.fingerprint import build_fingerprint
from app.setup_detection.ids import setup_candidate_id
from app.setup_detection.lifecycle import compute_expires_at, transition
from app.setup_detection.schemas import (
    BreakoutConfirmation,
    EvidenceCheck,
    RuleType,
    SetupCandidate,
    SetupLifecycleState,
    SetupType,
)


def _reference_levels(inputs: DetectorInputs):
    """Yields (direction, level, source, is_eligible) where `is_eligible`
    tells the caller whether a given candle is even chronologically allowed
    to reference this level -- see `after_previous_day`/`after_previous_week`."""
    previous_day = inputs.feature_snapshot.previous_day
    previous_week = inputs.feature_snapshot.previous_week
    levels = []
    if previous_day.status == FeatureStatus.OK:
        eligible = lambda ts: after_previous_day(ts, previous_day.trading_date)  # noqa: E731
        if previous_day.high is not None:
            levels.append((Direction.BULLISH, previous_day.high, "previous_day_high", eligible))
        if previous_day.low is not None:
            levels.append((Direction.BEARISH, previous_day.low, "previous_day_low", eligible))
    if previous_week.status == FeatureStatus.OK:
        eligible = lambda ts: after_previous_week(ts, previous_week.week_end_date)  # noqa: E731
        if previous_week.high is not None:
            levels.append((Direction.BULLISH, previous_week.high, "previous_week_high", eligible))
        if previous_week.low is not None:
            levels.append((Direction.BEARISH, previous_week.low, "previous_week_low", eligible))
    return levels


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    candles = inputs.candles
    candidates: list[SetupCandidate] = []

    for direction, level, source, eligible in _reference_levels(inputs):
        breakout_idx = None
        for idx, candle in enumerate(candles):
            if not eligible(candle.timestamp):
                continue
            check = check_close_beyond_level(
                candle, level, direction, inputs.config.breakout_tolerance_percent, "x", "x", "x"
            )
            if check.passed:
                breakout_idx = idx
                break
        if breakout_idx is None:
            continue

        breakout_candle = candles[breakout_idx]
        tolerance = level * (inputs.config.retest_tolerance_percent / 100)
        retest_candle = None
        window_end = min(len(candles), breakout_idx + 1 + inputs.config.retest_max_bars_after_breakout)
        for idx2 in range(breakout_idx + 1, window_end):
            candle = candles[idx2]
            touched = (
                candle.low <= level + tolerance
                if direction == Direction.BULLISH
                else candle.high >= level - tolerance
            )
            if touched:
                retest_candle = candle
                break
        if retest_candle is None:
            continue
        if not within_lookback(retest_candle.timestamp, candles, inputs.config.detection_lookback_bars):
            continue

        holds = retest_candle.close > level if direction == Direction.BULLISH else retest_candle.close < level

        hard_checks = [
            EvidenceCheck(
                code="breakout_confirmed_before_retest",
                label=f"Confirmed close beyond {level:.2f} on {breakout_candle.timestamp.isoformat()}",
                rule_type=RuleType.HARD,
                passed=True,
                source=f"features.{source}",
            ),
            EvidenceCheck(
                code="retest_touched_level",
                label=f"Price revisited {level:.2f} on {retest_candle.timestamp.isoformat()}",
                rule_type=RuleType.HARD,
                passed=True,
                source="candle.high_low",
            ),
            EvidenceCheck(
                code="retest_held",
                label=f"Retest closed {'above' if direction == Direction.BULLISH else 'below'} {level:.2f}",
                rule_type=RuleType.HARD,
                passed=holds,
                actual=retest_candle.close,
                required=level,
                source="candle.close",
            ),
        ]
        soft_checks = [
            EvidenceCheck(
                code="retest_lower_volume_than_breakout",
                label="Retest volume lower than breakout volume",
                rule_type=RuleType.SOFT,
                passed=retest_candle.volume < breakout_candle.volume,
                actual=retest_candle.volume,
                required=breakout_candle.volume,
                source="candle.volume",
            ),
            check_rvol(
                inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation
            ),
        ]
        structure = inputs.structure_by_timeframe.get(inputs.timeframe)
        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(direction, structure, inputs.timeframe.value)
        if htf_conflict:
            conflicts.append(htf_conflict)

        candidates.append(
            _build_retest_candidate(
                inputs,
                direction,
                level,
                source,
                breakout_candle,
                retest_candle,
                hard_checks,
                soft_checks,
                conflicts,
                holds,
            )
        )

    return candidates


def _build_retest_candidate(
    inputs,
    direction,
    level,
    source,
    breakout_candle,
    retest_candle,
    hard_checks,
    soft_checks,
    conflicts,
    holds,
):
    reference_key = f"retest|{source}|{breakout_candle.timestamp.isoformat()}"
    candidate_id = setup_candidate_id(
        inputs.symbol,
        SetupType.BREAKOUT_RETEST,
        direction,
        inputs.timeframe,
        reference_key,
        breakout_candle.timestamp,
    )

    transitions = [
        transition(
            SetupLifecycleState.CANDIDATE,
            breakout_candle.timestamp,
            "breakout_confirmed",
            f"Breakout of {level:.2f} confirmed",
        ),
        transition(
            SetupLifecycleState.CANDIDATE,
            retest_candle.timestamp,
            "retest_occurred",
            "Price returned to the broken level",
        ),
    ]
    if holds:
        transitions.append(
            transition(
                SetupLifecycleState.QUALIFIED,
                retest_candle.timestamp,
                "retest_held",
                "Retest held and closed through",
            )
        )
        state = SetupLifecycleState.QUALIFIED
        expires_at = compute_expires_at(
            retest_candle.timestamp,
            SetupType.BREAKOUT_RETEST,
            bar_duration_seconds(inputs.timeframe),
            inputs.config,
        )
    else:
        transitions.append(
            transition(
                SetupLifecycleState.REJECTED,
                retest_candle.timestamp,
                "retest_failed",
                "Retest closed back through the level",
            )
        )
        state = SetupLifecycleState.REJECTED
        expires_at = None

    context = build_setup_context(inputs, as_of=retest_candle.timestamp)
    fingerprint = build_fingerprint(
        setup_type=SetupType.BREAKOUT_RETEST,
        direction=direction,
        context=context,
        reference_price=level,
        support_confluence=len(inputs.levels_snapshot.active_support_zones),
        resistance_confluence=len(inputs.levels_snapshot.active_resistance_zones),
        min_gap_percent=inputs.config.min_gap_percent_for_continuation,
    )

    return SetupCandidate(
        id=candidate_id,
        symbol=inputs.symbol,
        timeframe=inputs.timeframe,
        setup_type=SetupType.BREAKOUT_RETEST,
        direction=direction,
        reference_price=level,
        reference_source=source,
        reference_timestamp=breakout_candle.timestamp,
        confirmation=BreakoutConfirmation.CLOSE_BREAK,
        candidate_candle_timestamp=breakout_candle.timestamp,
        created_at=breakout_candle.timestamp,
        current_state=state,
        transitions=transitions,
        hard_checks=hard_checks,
        soft_checks=soft_checks,
        conflicts=conflicts,
        invalidation_criteria=[f"Confirmed close back through {level:.2f} after the retest"],
        context=context,
        fingerprint=fingerprint,
        expires_at=expires_at,
        triggered_at=retest_candle.timestamp if holds else None,
        metadata={"breakout_timestamp": breakout_candle.timestamp.isoformat()},
    )
