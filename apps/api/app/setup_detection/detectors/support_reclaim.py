"""Support reclaim (#11, bullish only -- the bearish mirror is resistance
rejection, which is a genuinely different mechanic and lives in its own
module). References come from Phase 5 zones (the current nearest support,
*and* recently-broken support zones -- a reclaim is very often exactly "the
zone that broke is now being recovered", so excluding broken zones would
miss the most classic case), with a previous-day-low fallback when no zone
exists at all yet.

Hard: price genuinely traded below the reference within the reclaim lookback
window (not just the immediately preceding bar -- a real reclaim, not noise),
and the current completed candle closes back above it.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import (
    after_previous_day,
    build_resolved_candidate,
    within_lookback,
)
from app.setup_detection.evidence import check_rvol, check_trend_alignment
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType
from app.support_resistance.schemas import LevelKind


def _reference_sources(inputs: DetectorInputs):
    """Yields (level, source, reference_timestamp, reference_key, eligible)."""
    seen_levels = set()

    zone = inputs.levels_snapshot.nearest_support
    if zone is not None:
        seen_levels.add(zone.id)
        yield (
            zone.representative_price,
            "support_zone",
            zone.known_at,
            f"support_zone|{zone.id}",
            lambda ts, known_at=zone.known_at: ts >= known_at,
        )

    for zone in inputs.levels_snapshot.recent_broken_zones:
        if zone.kind != LevelKind.SUPPORT or zone.id in seen_levels:
            continue
        seen_levels.add(zone.id)
        yield (
            zone.representative_price,
            "recently_broken_support_zone",
            zone.known_at,
            f"support_zone|{zone.id}",
            lambda ts, known_at=zone.known_at: ts >= known_at,
        )

    previous_day = inputs.feature_snapshot.previous_day
    if previous_day.status == FeatureStatus.OK and previous_day.low is not None:
        yield (
            previous_day.low,
            "previous_day_low",
            None,
            f"previous_day_low|{previous_day.trading_date}",
            lambda ts: after_previous_day(ts, previous_day.trading_date),
        )


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
    candidates: list[SetupCandidate] = []
    window = inputs.config.reclaim_lookback_bars

    for level, source, reference_timestamp, reference_key, eligible in _reference_sources(inputs):
        candidate = _find_reclaim(
            inputs, level, source, reference_timestamp, reference_key, eligible, window, daily_structure
        )
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _find_reclaim(
    inputs, level, source, reference_timestamp, reference_key, eligible, window, daily_structure
):
    for idx in range(1, len(inputs.candles)):
        candle = inputs.candles[idx]
        if not eligible(candle.timestamp):
            continue
        if not within_lookback(candle.timestamp, inputs.candles, inputs.config.detection_lookback_bars):
            continue
        if candle.close <= level:
            continue

        prior_window = inputs.candles[max(0, idx - window) : idx]
        was_below = any(c.close < level for c in prior_window)
        if not was_below:
            continue

        hard_checks = [
            EvidenceCheck(
                code="was_below_reference",
                label=f"Traded below {level:.2f} within the last {window} bars",
                rule_type=RuleType.HARD,
                passed=True,
                source=f"levels.{source}",
            ),
            EvidenceCheck(
                code="close_above_reference",
                label=f"Close above {level:.2f}",
                rule_type=RuleType.HARD,
                passed=True,
                actual=candle.close,
                required=level,
                source=f"levels.{source}",
            ),
        ]
        soft_checks = [
            check_rvol(
                inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation
            ),
            check_trend_alignment(
                daily_structure.trend.trend if daily_structure else None,
                Direction.BULLISH,
                code="daily_structure_aligned",
                label="Daily structure aligned",
                source="structure.1d.trend",
            ),
        ]
        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(Direction.BULLISH, daily_structure, "daily")
        if htf_conflict:
            conflicts.append(htf_conflict)

        return build_resolved_candidate(
            inputs,
            SetupType.SUPPORT_RECLAIM,
            Direction.BULLISH,
            candle.timestamp,
            reference_price=level,
            reference_source=source,
            reference_timestamp=reference_timestamp,
            reference_key=reference_key,
            hard_checks=hard_checks,
            soft_checks=soft_checks,
            conflicts=conflicts,
            invalidation_criteria=[f"Confirmed close back below {level:.2f}"],
        )

    return None
