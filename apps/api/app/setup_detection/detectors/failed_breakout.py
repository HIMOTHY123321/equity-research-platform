"""Failed breakout (#9) -- two deliberately distinct variants, never
combined:

- `wick_failed_breakout`: price wicks beyond the level intrabar but the
  candle never closes beyond it. This never confirmed in the first place,
  so it's REJECTED the moment it's observed.
- `confirmed_breakout_failure`: a completed close beyond the level *did*
  confirm (a real breakout, per #7), but a later completed close within
  `failed_breakout_bars` moves back through the level -- a genuine
  qualify-then-invalidate lifecycle, not a same-bar rejection.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_structure.schemas import Direction
from app.setup_detection.context import DetectorInputs, build_setup_context
from app.setup_detection.detectors._common import after_previous_day, after_previous_week, within_lookback
from app.setup_detection.evidence import check_close_beyond_level
from app.setup_detection.fingerprint import build_fingerprint
from app.setup_detection.ids import setup_candidate_id
from app.setup_detection.lifecycle import transition
from app.setup_detection.schemas import (
    BreakoutConfirmation,
    EvidenceCheck,
    RuleType,
    SetupCandidate,
    SetupLifecycleState,
    SetupType,
)


def _reference_levels(inputs: DetectorInputs):
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
        wick_emitted = False
        confirmed_idx = None

        for idx, candle in enumerate(candles):
            if not eligible(candle.timestamp):
                continue
            close_check = check_close_beyond_level(
                candle, level, direction, inputs.config.breakout_tolerance_percent, "x", "x", "x"
            )
            if close_check.passed:
                confirmed_idx = idx
                break

            wicked = (candle.high > level) if direction == Direction.BULLISH else (candle.low < level)
            if (
                wicked
                and not wick_emitted
                and within_lookback(candle.timestamp, candles, inputs.config.detection_lookback_bars)
            ):
                candidates.append(_build_wick_failure(inputs, direction, level, source, candle))
                wick_emitted = True

        if confirmed_idx is None:
            continue

        breakout_candle = candles[confirmed_idx]
        window = candles[confirmed_idx + 1 : confirmed_idx + 1 + inputs.config.failed_breakout_bars]
        failure_candle = None
        for candle in window:
            closed_back = (candle.close < level) if direction == Direction.BULLISH else (candle.close > level)
            if closed_back:
                failure_candle = candle
                break

        if failure_candle is not None and within_lookback(
            failure_candle.timestamp, candles, inputs.config.detection_lookback_bars
        ):
            candidates.append(
                _build_confirmed_failure(inputs, direction, level, source, breakout_candle, failure_candle)
            )

    return candidates


def _build_wick_failure(inputs, direction, level, source, candle) -> SetupCandidate:
    hard_check = EvidenceCheck(
        code="wick_only_no_close_confirmation",
        label=f"Wicked {'above' if direction == Direction.BULLISH else 'below'} {level:.2f} but closed back "
        f"{'below' if direction == Direction.BULLISH else 'above'} it",
        rule_type=RuleType.HARD,
        passed=False,
        actual=candle.close,
        required=level,
        source=f"features.{source}",
    )
    reference_key = f"wick_failure|{source}|{candle.timestamp.isoformat()}"
    candidate_id = setup_candidate_id(
        inputs.symbol,
        SetupType.WICK_FAILED_BREAKOUT,
        direction,
        inputs.timeframe,
        reference_key,
        candle.timestamp,
    )
    transitions = [
        transition(
            SetupLifecycleState.CANDIDATE,
            candle.timestamp,
            "wick_beyond_level",
            "Price wicked beyond the level",
        ),
        transition(
            SetupLifecycleState.REJECTED,
            candle.timestamp,
            "no_close_confirmation",
            "Close never confirmed the breakout",
        ),
    ]
    context = build_setup_context(inputs, as_of=candle.timestamp)
    fingerprint = build_fingerprint(
        SetupType.WICK_FAILED_BREAKOUT,
        direction,
        context,
        level,
        len(inputs.levels_snapshot.active_support_zones),
        len(inputs.levels_snapshot.active_resistance_zones),
        inputs.config.min_gap_percent_for_continuation,
    )
    return SetupCandidate(
        id=candidate_id,
        symbol=inputs.symbol,
        timeframe=inputs.timeframe,
        setup_type=SetupType.WICK_FAILED_BREAKOUT,
        direction=direction,
        reference_price=level,
        reference_source=source,
        confirmation=BreakoutConfirmation.WICK_BREACH,
        candidate_candle_timestamp=candle.timestamp,
        created_at=candle.timestamp,
        current_state=SetupLifecycleState.REJECTED,
        transitions=transitions,
        hard_checks=[hard_check],
        soft_checks=[],
        conflicts=[],
        invalidation_criteria=[],
        context=context,
        fingerprint=fingerprint,
    )


def _build_confirmed_failure(
    inputs, direction, level, source, breakout_candle, failure_candle
) -> SetupCandidate:
    hard_checks = [
        EvidenceCheck(
            code="breakout_confirmed",
            label=f"Confirmed close beyond {level:.2f}",
            rule_type=RuleType.HARD,
            passed=True,
            source=f"features.{source}",
        ),
        EvidenceCheck(
            code="reversed_within_window",
            label=f"Closed back through {level:.2f} within {inputs.config.failed_breakout_bars} bars",
            rule_type=RuleType.HARD,
            passed=True,
            actual=failure_candle.close,
            required=level,
            source="candle.close",
        ),
    ]
    reference_key = f"confirmed_failure|{source}|{breakout_candle.timestamp.isoformat()}"
    candidate_id = setup_candidate_id(
        inputs.symbol,
        SetupType.CONFIRMED_BREAKOUT_FAILURE,
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
            SetupLifecycleState.TRIGGERED,
            breakout_candle.timestamp,
            "breakout_triggered",
            "Breakout was live",
        ),
        transition(
            SetupLifecycleState.INVALIDATED,
            failure_candle.timestamp,
            "closed_back_through_level",
            "Price closed back through the broken level",
        ),
    ]
    context = build_setup_context(inputs, as_of=failure_candle.timestamp)
    fingerprint = build_fingerprint(
        SetupType.CONFIRMED_BREAKOUT_FAILURE,
        direction,
        context,
        level,
        len(inputs.levels_snapshot.active_support_zones),
        len(inputs.levels_snapshot.active_resistance_zones),
        inputs.config.min_gap_percent_for_continuation,
    )
    return SetupCandidate(
        id=candidate_id,
        symbol=inputs.symbol,
        timeframe=inputs.timeframe,
        setup_type=SetupType.CONFIRMED_BREAKOUT_FAILURE,
        direction=direction,
        reference_price=level,
        reference_source=source,
        reference_timestamp=breakout_candle.timestamp,
        confirmation=BreakoutConfirmation.CLOSE_BREAK,
        candidate_candle_timestamp=breakout_candle.timestamp,
        created_at=breakout_candle.timestamp,
        current_state=SetupLifecycleState.INVALIDATED,
        transitions=transitions,
        hard_checks=hard_checks,
        soft_checks=[],
        conflicts=[],
        invalidation_criteria=[],
        context=context,
        fingerprint=fingerprint,
        invalidated_at=failure_candle.timestamp,
        invalidation_reason=f"Closed back through {level:.2f}",
        triggered_at=breakout_candle.timestamp,
    )
