"""Previous-day-high breakout (bullish) / previous-day-low breakdown
(bearish) -- #1/#2. Reference level comes directly from Phase 3's
`FeatureSnapshot.previous_day`, never rebuilt from raw candles here.

Hard rule: a completed primary-timeframe candle within the lookback window
closes beyond PDH/PDL by more than `breakout_tolerance_percent` (#7 --
close-only, exact equality never counts, matching the BOS convention).
Soft: RVOL confirmation, daily structure alignment, no opposing zone
directly overhead/below.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import (
    conflict_if_higher_timeframe_opposed,
    conflict_if_opposing_zone_nearby,
)
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import (
    after_previous_day,
    build_resolved_candidate,
    within_lookback,
)
from app.setup_detection.evidence import check_close_beyond_level, check_rvol, check_trend_alignment
from app.setup_detection.schemas import BreakoutConfirmation, SetupCandidate, SetupType

_SPECS = (
    (SetupType.PREVIOUS_DAY_HIGH_BREAKOUT, Direction.BULLISH, "previous_day_high"),
    (SetupType.PREVIOUS_DAY_LOW_BREAKDOWN, Direction.BEARISH, "previous_day_low"),
)


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    previous_day = inputs.feature_snapshot.previous_day
    if previous_day.status != FeatureStatus.OK or previous_day.trading_date is None:
        return []

    results: list[SetupCandidate] = []
    for setup_type, direction, source_name in _SPECS:
        level = previous_day.high if direction == Direction.BULLISH else previous_day.low
        if level is None:
            continue
        results.extend(_detect_one(inputs, setup_type, direction, level, source_name))
    return results


def _detect_one(
    inputs: DetectorInputs,
    setup_type: SetupType,
    direction: Direction,
    level: float,
    source_name: str,
) -> list[SetupCandidate]:
    candidates: list[SetupCandidate] = []
    reference_timestamp = None
    if inputs.feature_snapshot.previous_day.trading_date is not None:
        from datetime import datetime, time

        from app.market_data.sessions import EXCHANGE_TZ

        reference_timestamp = datetime.combine(
            inputs.feature_snapshot.previous_day.trading_date, time.min, tzinfo=EXCHANGE_TZ
        )
    reference_key = f"{source_name}|{reference_timestamp.isoformat() if reference_timestamp else 'na'}"

    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
    four_hour_structure = inputs.structure_by_timeframe.get(Timeframe.FOUR_HOUR)

    for candle in inputs.candles:
        if not after_previous_day(candle.timestamp, inputs.feature_snapshot.previous_day.trading_date):
            continue
        if not within_lookback(candle.timestamp, inputs.candles, inputs.config.detection_lookback_bars):
            continue

        hard_close = check_close_beyond_level(
            candle,
            level,
            direction,
            inputs.config.breakout_tolerance_percent,
            code="close_beyond_level",
            label=f"Close {'above' if direction == Direction.BULLISH else 'below'} "
            f"{source_name.replace('_', ' ')}",
            source=f"features.previous_day.{'high' if direction == Direction.BULLISH else 'low'}",
        )
        if not hard_close.passed:
            continue

        soft_checks = [
            check_rvol(
                inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation
            ),
            check_trend_alignment(
                daily_structure.trend.trend if daily_structure else None,
                direction,
                code="daily_structure_aligned",
                label="Daily structure aligned",
                source="structure.1d.trend",
            ),
            check_trend_alignment(
                four_hour_structure.trend.trend if four_hour_structure else None,
                direction,
                code="four_hour_structure_aligned",
                label="4H structure aligned",
                source="structure.4h.trend",
            ),
        ]

        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(direction, daily_structure, "daily")
        if htf_conflict:
            conflicts.append(htf_conflict)
        zone_conflict = conflict_if_opposing_zone_nearby(
            direction, level, inputs.levels_snapshot, inputs.config.opposing_zone_proximity_percent
        )
        if zone_conflict:
            conflicts.append(zone_conflict)

        invalidation = [
            f"Confirmed close back {'below' if direction == Direction.BULLISH else 'above'} "
            f"{level:.2f} ({source_name.replace('_', ' ')})"
        ]

        candidates.append(
            build_resolved_candidate(
                inputs,
                setup_type,
                direction,
                candle.timestamp,
                reference_price=level,
                reference_source=source_name,
                reference_timestamp=reference_timestamp,
                reference_key=reference_key,
                hard_checks=[hard_close],
                soft_checks=soft_checks,
                conflicts=conflicts,
                invalidation_criteria=invalidation,
                confirmation=BreakoutConfirmation.CLOSE_BREAK,
            )
        )
        # Duplicate-signal suppression (#26): only the first bar that closes
        # beyond this trading day's PDH/PDL opens a candidate for it.
        break

    return candidates
