"""Gap fill (#14). Tracked, not scored: a gap-fill candidate exists the
moment a qualifying-size gap forms at the session open, and TRIGGERS the
instant price actually trades back through the previous close -- found by
scanning today's own candles for the first bar that does so, not inferred
from a running snapshot alone, so `triggered_at` is the real event
timestamp rather than "now".
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_data.sessions import exchange_trading_date
from app.market_structure.schemas import Direction
from app.setup_detection.context import DetectorInputs, build_setup_context
from app.setup_detection.detectors._common import bar_duration_seconds
from app.setup_detection.fingerprint import build_fingerprint
from app.setup_detection.ids import setup_candidate_id
from app.setup_detection.lifecycle import compute_expires_at, transition
from app.setup_detection.schemas import (
    EvidenceCheck,
    RuleType,
    SetupCandidate,
    SetupLifecycleState,
    SetupType,
)


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    gap = inputs.feature_snapshot.gap
    if gap.status != FeatureStatus.OK or gap.gap_percent is None or gap.direction not in ("up", "down"):
        return []
    if abs(gap.gap_percent) < inputs.config.min_gap_percent_for_continuation:
        return []
    if gap.session_open is None or gap.previous_close is None or not inputs.candles:
        return []

    today = exchange_trading_date(inputs.as_of)
    todays_candles = sorted(
        (c for c in inputs.candles if exchange_trading_date(c.timestamp) == today), key=lambda c: c.timestamp
    )
    if not todays_candles:
        return []

    gap_up = gap.direction == "up"
    fill_direction = Direction.BEARISH if gap_up else Direction.BULLISH
    gap_size = abs(gap.session_open - gap.previous_close)

    fill_candle = None
    extreme = gap.session_open
    for candle in todays_candles:
        if gap_up:
            extreme = min(extreme, candle.low)
            if candle.low <= gap.previous_close:
                fill_candle = candle
                break
        else:
            extreme = max(extreme, candle.high)
            if candle.high >= gap.previous_close:
                fill_candle = candle
                break

    retracement = abs(gap.session_open - extreme)
    fill_percent = min(100.0, retracement / gap_size * 100) if gap_size else 0.0
    full_fill = fill_candle is not None

    candidate_timestamp = todays_candles[0].timestamp
    hard_check = EvidenceCheck(
        code="qualifying_gap_present",
        label=f"Gap {gap.gap_percent:+.2f}% at session open",
        rule_type=RuleType.HARD,
        passed=True,
        actual=abs(gap.gap_percent),
        required=inputs.config.min_gap_percent_for_continuation,
        source="features.gap",
    )

    candidate_id = setup_candidate_id(
        inputs.symbol,
        SetupType.GAP_FILL,
        fill_direction,
        inputs.timeframe,
        f"gap_fill|{today.isoformat()}",
        candidate_timestamp,
    )
    transitions = [
        transition(
            SetupLifecycleState.CANDIDATE, candidate_timestamp, "gap_detected", "Gap detected at session open"
        ),
        transition(
            SetupLifecycleState.QUALIFIED,
            candidate_timestamp,
            "gap_qualifies_for_tracking",
            "Gap meets minimum size",
        ),
    ]
    state = SetupLifecycleState.QUALIFIED
    triggered_at = None
    if full_fill:
        triggered_at = fill_candle.timestamp
        transitions.append(
            transition(
                SetupLifecycleState.TRIGGERED,
                triggered_at,
                "gap_fully_filled",
                f"Price traded back through {gap.previous_close:.2f}",
            )
        )
        state = SetupLifecycleState.TRIGGERED

    context = build_setup_context(inputs)
    fingerprint = build_fingerprint(
        setup_type=SetupType.GAP_FILL,
        direction=fill_direction,
        context=context,
        reference_price=gap.previous_close,
        support_confluence=len(inputs.levels_snapshot.active_support_zones),
        resistance_confluence=len(inputs.levels_snapshot.active_resistance_zones),
        min_gap_percent=inputs.config.min_gap_percent_for_continuation,
    )
    expires_at = None
    if state == SetupLifecycleState.QUALIFIED:
        expires_at = compute_expires_at(
            candidate_timestamp, SetupType.GAP_FILL, bar_duration_seconds(inputs.timeframe), inputs.config
        )

    return [
        SetupCandidate(
            id=candidate_id,
            symbol=inputs.symbol,
            timeframe=inputs.timeframe,
            setup_type=SetupType.GAP_FILL,
            direction=fill_direction,
            reference_price=gap.previous_close,
            reference_source="previous_day_close",
            reference_timestamp=None,
            candidate_candle_timestamp=candidate_timestamp,
            created_at=candidate_timestamp,
            current_state=state,
            transitions=transitions,
            hard_checks=[hard_check],
            soft_checks=[],
            conflicts=[],
            invalidation_criteria=[f"Session closes without trading back through {gap.previous_close:.2f}"],
            context=context,
            fingerprint=fingerprint,
            expires_at=expires_at,
            triggered_at=triggered_at,
            metadata={
                "gap_percent": gap.gap_percent,
                "gap_size": gap_size,
                "fill_percent": fill_percent,
                "full_fill": full_fill,
                "partial_fill": fill_percent > 0 and not full_fill,
            },
        )
    ]
