"""Range breakout (#17): a completed close beyond the *existing*
`MarketStructureSnapshot.active_range` bound for the primary timeframe.
Reuses Phase 4's active-range calculation directly -- no separate range
system is reconstructed here.
"""

from __future__ import annotations

from app.market_structure.schemas import Direction, StructureStatus
from app.setup_detection.conflicts import (
    conflict_if_higher_timeframe_opposed,
    conflict_if_opposing_zone_nearby,
)
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import build_resolved_candidate, within_lookback
from app.setup_detection.evidence import check_close_beyond_level, check_rvol, check_trend_alignment
from app.setup_detection.schemas import BreakoutConfirmation, SetupCandidate, SetupType

_SPECS = ((SetupType.RANGE_BREAKOUT, Direction.BULLISH), (SetupType.RANGE_BREAKOUT, Direction.BEARISH))


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    structure = inputs.structure_by_timeframe.get(inputs.timeframe)
    if structure is None or structure.active_range.status != StructureStatus.OK:
        return []

    candidates: list[SetupCandidate] = []
    for setup_type, direction in _SPECS:
        level = structure.active_range.high if direction == Direction.BULLISH else structure.active_range.low
        defining_swing = (
            structure.latest_swing_high if direction == Direction.BULLISH else structure.latest_swing_low
        )
        # Anti-lookahead (#35): the active range's own boundary only became
        # knowable at its defining swing's confirmed_at. A candle before
        # that instant traded against a level that, at the time, was not
        # yet "the active range" -- judging it here would be lookahead,
        # even though the range's *current* value happens to match a price
        # that same older candle also touched (a real bug found this way
        # against live SPY data during the Phase 6 build).
        if level is None or defining_swing is None:
            continue
        candidates.extend(_detect_one(inputs, setup_type, direction, level, structure, defining_swing))
    return candidates


def _detect_one(
    inputs: DetectorInputs, setup_type, direction, level, structure, defining_swing
) -> list[SetupCandidate]:
    source_name = "active_range_high" if direction == Direction.BULLISH else "active_range_low"
    candidates: list[SetupCandidate] = []

    for candle in inputs.candles:
        if candle.timestamp < defining_swing.confirmed_at:
            continue
        if not within_lookback(candle.timestamp, inputs.candles, inputs.config.detection_lookback_bars):
            continue

        hard_close = check_close_beyond_level(
            candle,
            level,
            direction,
            inputs.config.range_breakout_tolerance_percent,
            code="close_beyond_range",
            label=f"Close {'above' if direction == Direction.BULLISH else 'below'} active range "
            f"{'high' if direction == Direction.BULLISH else 'low'}",
            source=f"structure.{inputs.timeframe.value}.active_range",
        )
        if not hard_close.passed:
            continue

        soft_checks = [
            check_rvol(
                inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation
            ),
            check_trend_alignment(
                structure.trend.trend,
                direction,
                code="primary_structure_aligned",
                label="Primary-timeframe structure aligned",
                source=f"structure.{inputs.timeframe.value}.trend",
            ),
        ]

        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(
            direction, inputs.structure_by_timeframe.get(inputs.timeframe), inputs.timeframe.value
        )
        if htf_conflict:
            conflicts.append(htf_conflict)
        zone_conflict = conflict_if_opposing_zone_nearby(
            direction, level, inputs.levels_snapshot, inputs.config.opposing_zone_proximity_percent
        )
        if zone_conflict:
            conflicts.append(zone_conflict)

        reference_key = f"{source_name}|{structure.active_range.high}|{structure.active_range.low}"
        candidates.append(
            build_resolved_candidate(
                inputs,
                setup_type,
                direction,
                candle.timestamp,
                reference_price=level,
                reference_source=source_name,
                reference_timestamp=defining_swing.pivot_timestamp,
                reference_key=reference_key,
                hard_checks=[hard_close],
                soft_checks=soft_checks,
                conflicts=conflicts,
                invalidation_criteria=[
                    f"Confirmed close back {'below' if direction == Direction.BULLISH else 'above'} "
                    f"{level:.2f}"
                ],
                confirmation=BreakoutConfirmation.CLOSE_BREAK,
            )
        )
        break

    return candidates
