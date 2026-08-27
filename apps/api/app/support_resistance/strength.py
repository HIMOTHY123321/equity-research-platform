"""Deterministic 0-100 strength score. Every point is explainable via
StrengthBreakdown -- never a fabricated or probabilistic number, and never
called a "probability" anywhere in this codebase. See the ADR for the fully
worked example this formula reproduces exactly:

    Previous week high         +25   (source_score)
    Daily swing high           +18   (source_score)
    4H swing high               +12   (source_score)                = 55
    Multi-timeframe confluence  +10   (confluence_score, 3 timeframes)
    3 independent rejections    +12   (interaction_score: 6+4+2)
    Recency                      +5   (recency_score)
    --------------------------------
    Total                        82
"""

from __future__ import annotations

from typing import Optional

from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.schemas import (
    InteractionType,
    StrengthBreakdown,
    ZoneEvidenceEntry,
    ZoneInteraction,
)

BROKEN_ZONE_PENALTY_MULTIPLIER = 0.3


def compute_source_score(evidence: list[ZoneEvidenceEntry], config: SupportResistanceConfig) -> float:
    return min(sum(entry.weight for entry in evidence), config.source_score_cap)


def compute_confluence_score(timeframe_count: int, config: SupportResistanceConfig) -> float:
    if timeframe_count <= 1:
        return 0.0
    return min(
        (timeframe_count - 1) * config.confluence_points_per_extra_timeframe,
        config.confluence_score_cap,
    )


def compute_interaction_score(interactions: list[ZoneInteraction], config: SupportResistanceConfig) -> float:
    """Diminishing returns via a fixed points schedule (see config): the
    Nth independent rejection/touch contributes schedule[N-1] points, and
    anything beyond the schedule's length contributes nothing further --
    15 touches can never produce an unbounded score.
    """
    independent = [i for i in interactions if i.is_independent]
    rejections = [i for i in independent if i.interaction_type == InteractionType.REJECTION]
    touches = [i for i in independent if i.interaction_type != InteractionType.REJECTION]

    rejection_points = sum(config.rejection_points_schedule[: len(rejections)])
    touch_points = sum(config.touch_points_schedule[: len(touches)])

    return min(rejection_points + touch_points, config.interaction_score_cap)


def compute_recency_score(
    bars_since_last_interaction: Optional[int], config: SupportResistanceConfig
) -> float:
    if bars_since_last_interaction is None:
        return 0.0
    for max_bars, points in config.recency_buckets:
        if bars_since_last_interaction <= max_bars:
            return points
    return 0.0


def compute_strength(
    evidence: list[ZoneEvidenceEntry],
    timeframe_count: int,
    interactions: list[ZoneInteraction],
    bars_since_last_interaction: Optional[int],
    is_broken: bool,
    config: SupportResistanceConfig,
) -> StrengthBreakdown:
    source_score = compute_source_score(evidence, config)
    confluence_score = compute_confluence_score(timeframe_count, config)
    interaction_score = compute_interaction_score(interactions, config)
    recency_score = compute_recency_score(bars_since_last_interaction, config)

    total = source_score + confluence_score + interaction_score + recency_score
    if is_broken:
        total *= BROKEN_ZONE_PENALTY_MULTIPLIER
    total = min(total, 100.0)

    return StrengthBreakdown(
        source_score=source_score,
        confluence_score=confluence_score,
        interaction_score=interaction_score,
        recency_score=recency_score,
        total=total,
    )
