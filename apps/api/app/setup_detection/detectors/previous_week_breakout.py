"""Previous-week-high breakout (bullish) / previous-week-low breakdown
(bearish) -- #3/#4. Same close-only confirmation rule as
previous_day_breakout.py, reusing `FeatureSnapshot.previous_week` rather
than rebuilding weekly aggregation logic here.
"""

from __future__ import annotations

from datetime import datetime, time

from app.features.common import FeatureStatus
from app.market_data.sessions import EXCHANGE_TZ
from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import (
    conflict_if_higher_timeframe_opposed,
    conflict_if_opposing_zone_nearby,
)
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import (
    after_previous_week,
    build_resolved_candidate,
    within_lookback,
)
from app.setup_detection.evidence import check_close_beyond_level, check_rvol, check_trend_alignment
from app.setup_detection.schemas import BreakoutConfirmation, SetupCandidate, SetupType

_SPECS = (
    (SetupType.PREVIOUS_WEEK_HIGH_BREAKOUT, Direction.BULLISH, "previous_week_high"),
    (SetupType.PREVIOUS_WEEK_LOW_BREAKDOWN, Direction.BEARISH, "previous_week_low"),
)


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    previous_week = inputs.feature_snapshot.previous_week
    if previous_week.status != FeatureStatus.OK or previous_week.week_start_date is None:
        return []

    reference_timestamp = datetime.combine(previous_week.week_start_date, time.min, tzinfo=EXCHANGE_TZ)

    results: list[SetupCandidate] = []
    for setup_type, direction, source_name in _SPECS:
        level = previous_week.high if direction == Direction.BULLISH else previous_week.low
        if level is None:
            continue
        results.extend(
            _detect_one(
                inputs,
                setup_type,
                direction,
                level,
                source_name,
                reference_timestamp,
                previous_week.week_end_date,
            )
        )
    return results


def _detect_one(
    inputs: DetectorInputs,
    setup_type: SetupType,
    direction: Direction,
    level: float,
    source_name: str,
    reference_timestamp: datetime,
    week_end_date,
) -> list[SetupCandidate]:
    candidates: list[SetupCandidate] = []
    reference_key = f"{source_name}|{reference_timestamp.isoformat()}"

    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
    four_hour_structure = inputs.structure_by_timeframe.get(Timeframe.FOUR_HOUR)

    for candle in inputs.candles:
        if not after_previous_week(candle.timestamp, week_end_date):
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
            source=f"features.previous_week.{'high' if direction == Direction.BULLISH else 'low'}",
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
        break

    return candidates
