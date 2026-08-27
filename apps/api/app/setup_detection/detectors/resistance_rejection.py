"""Resistance rejection (#12, bearish). Consumes Phase 5's own deterministic
rejection events directly (`Zone.interactions` where
`interaction_type == REJECTION` and `is_independent`) rather than
re-implementing a competing wick/close rejection rule -- per the explicit
Phase 6 instruction not to duplicate financial logic across modules.
"""

from __future__ import annotations

from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import build_resolved_candidate, within_lookback
from app.setup_detection.evidence import check_rvol, check_trend_alignment
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType
from app.support_resistance.schemas import InteractionType


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
    candidates: list[SetupCandidate] = []

    for zone in inputs.levels_snapshot.active_resistance_zones:
        rejections = [
            interaction
            for interaction in zone.interactions
            if interaction.interaction_type == InteractionType.REJECTION and interaction.is_independent
        ]
        if not rejections:
            continue
        latest_rejection = max(rejections, key=lambda i: i.timestamp)
        if not within_lookback(
            latest_rejection.timestamp, inputs.candles, inputs.config.detection_lookback_bars
        ):
            continue

        hard_checks = [
            EvidenceCheck(
                code="independent_rejection_confirmed",
                label=f"Independent rejection from resistance zone "
                f"{zone.lower_bound:.2f}-{zone.upper_bound:.2f}",
                rule_type=RuleType.HARD,
                passed=True,
                actual=latest_rejection.close,
                required=zone.representative_price,
                source="levels.zone.interactions",
            )
        ]
        soft_checks = [
            check_rvol(
                inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation
            ),
            check_trend_alignment(
                daily_structure.trend.trend if daily_structure else None,
                Direction.BEARISH,
                code="daily_structure_aligned",
                label="Daily structure aligned",
                source="structure.1d.trend",
            ),
            EvidenceCheck(
                code="zone_strength_above_moderate",
                label=f"Zone strength {zone.strength.total:.0f}/100",
                rule_type=RuleType.SOFT,
                passed=zone.strength.total >= 40,
                actual=zone.strength.total,
                required=40,
                source="levels.zone.strength",
            ),
        ]
        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(Direction.BEARISH, daily_structure, "daily")
        if htf_conflict:
            conflicts.append(htf_conflict)

        candidates.append(
            build_resolved_candidate(
                inputs,
                SetupType.RESISTANCE_REJECTION,
                Direction.BEARISH,
                latest_rejection.timestamp,
                reference_price=zone.representative_price,
                reference_source="resistance_zone",
                reference_timestamp=zone.known_at,
                reference_key=f"resistance_zone|{zone.id}",
                hard_checks=hard_checks,
                soft_checks=soft_checks,
                conflicts=conflicts,
                invalidation_criteria=[f"Confirmed close above {zone.upper_bound:.2f} (zone upper bound)"],
            )
        )

    return candidates
