"""Every threshold and weight this engine depends on, centralized here.
Nothing in sources/clustering/strength/lifecycle should hard-code a number
that belongs in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.schemas.market_data import Timeframe


@dataclass(frozen=True)
class SourceWeight:
    source: str
    # None = applies to this source regardless of which timeframe it came from.
    timeframe: Optional[Timeframe]
    weight: float


# Centralized source importance ranking. Higher-timeframe and longer-lookback
# evidence outweighs shorter-timeframe evidence. Order doesn't matter for
# lookup (see get_source_weight) but is written high-to-low for readability.
DEFAULT_SOURCE_WEIGHTS: tuple[SourceWeight, ...] = (
    SourceWeight("previous_week_high", None, 25),
    SourceWeight("previous_week_low", None, 25),
    SourceWeight("confirmed_swing_high", Timeframe.ONE_DAY, 18),
    SourceWeight("confirmed_swing_low", Timeframe.ONE_DAY, 18),
    SourceWeight("confirmed_swing_high", Timeframe.FOUR_HOUR, 12),
    SourceWeight("confirmed_swing_low", Timeframe.FOUR_HOUR, 12),
    SourceWeight("previous_day_high", None, 10),
    SourceWeight("previous_day_low", None, 10),
    SourceWeight("confirmed_swing_high", Timeframe.ONE_HOUR, 6),
    SourceWeight("confirmed_swing_low", Timeframe.ONE_HOUR, 6),
    SourceWeight("confirmed_swing_high", Timeframe.FIFTEEN_MIN, 3),
    SourceWeight("confirmed_swing_low", Timeframe.FIFTEEN_MIN, 3),
    SourceWeight("confirmed_swing_high", Timeframe.FIVE_MIN, 2),
    SourceWeight("confirmed_swing_low", Timeframe.FIVE_MIN, 2),
)

# Sources that are informational only and never enter clustering/strength.
REFERENCE_ONLY_SOURCES = frozenset({"previous_day_close", "previous_week_close", "session_open"})


@dataclass(frozen=True)
class SupportResistanceConfig:
    # Clustering: percentage distance (of the lower-priced member) within
    # which two adjacent (price-sorted) same-polarity levels merge.
    cluster_tolerance_percent: float = 0.25

    # Extra buffer (percentage) around a zone's [lower, upper] bounds within
    # which a candle still counts as "touching" the zone.
    touch_tolerance_percent: float = 0.1

    # A close must clear the zone boundary by more than this percentage to
    # count as a confirmed break. 0.0 = any strictly-beyond close counts.
    break_tolerance_percent: float = 0.0

    source_weights: tuple[SourceWeight, ...] = field(default_factory=lambda: DEFAULT_SOURCE_WEIGHTS)
    default_source_weight: float = 5.0

    # Chronological bar-distance below which a second interaction with the
    # same zone is folded into the prior one rather than counted as
    # independent (still recorded, just flagged is_independent=False).
    minimum_bars_between_independent_touches: int = 3

    # Diminishing-returns point schedules (see strength.py). Index 0 = 1st
    # independent event, index 1 = 2nd, etc. Anything beyond the schedule's
    # length contributes 0 additional points.
    rejection_points_schedule: tuple[float, ...] = (6.0, 4.0, 2.0)
    touch_points_schedule: tuple[float, ...] = (3.0, 2.0, 1.0)

    source_score_cap: float = 60.0
    confluence_score_cap: float = 15.0
    confluence_points_per_extra_timeframe: float = 5.0
    interaction_score_cap: float = 18.0
    recency_score_cap: float = 5.0

    # Recency buckets: (max_bars, points) evaluated in order, first match wins.
    recency_buckets: tuple[tuple[int, float], ...] = ((3, 5.0), (10, 3.0), (30, 1.0))

    # A zone is "weakened" once it has this many independent interactions
    # without breaking (additional tests stop adding strength around here too).
    weakened_after_independent_interactions: int = 4

    # A zone is "stale" once this many bars have passed with no interaction.
    stale_after_bars: int = 100

    # How many zones/reference levels the API snapshot returns per bucket
    # (full history remains available via the lower-level functions).
    max_zones_in_snapshot: int = 8
    max_reference_levels_in_snapshot: int = 5
    max_recent_broken_zones_in_snapshot: int = 5


DEFAULT_SUPPORT_RESISTANCE_CONFIG = SupportResistanceConfig()


def get_source_weight(source: str, timeframe: Optional[Timeframe], config: SupportResistanceConfig) -> float:
    for entry in config.source_weights:
        if entry.source == source and entry.timeframe == timeframe:
            return entry.weight
    for entry in config.source_weights:
        if entry.source == source and entry.timeframe is None:
            return entry.weight
    return config.default_source_weight
