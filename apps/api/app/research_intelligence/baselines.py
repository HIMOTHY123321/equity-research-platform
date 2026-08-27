"""Strengthened baseline engine (#13, #14). Phase 7's
`app/research/baseline.py` already provides (A) the unconditional baseline
and the regime-matched primitive this module builds (B) and (C) on top of
-- this file adds no new candle-scanning logic, it composes what already
exists with the right matching keys.

(A) Unconditional: `app.research.baseline.compute_unconditional_baseline`,
    unchanged, reused directly.
(B) Direction-matched: bars where the *primary-timeframe* trend equals the
    setup's own direction. `TrendClass` and `Direction` share the same
    string values ("bullish"/"bearish") by construction, so this is exactly
    `compute_regime_matched_baseline(regime=direction.value)`.
(C) Structure-matched: bars where daily AND 4h AND the primary-timeframe
    trend all match the setup's own frozen `SetupContext` values -- a
    strictly more specific bucket than (B). Requires
    `BaselineSample.daily_trend`/`four_hour_trend` (added this phase to
    `app/research/replay.py` alongside the existing `regime` field).

All three use the exact same forward-horizon definitions setups themselves
use (`_forward_return` in app/research/baseline.py) -- a baseline computed
on different horizons than the setup it's compared against would be
meaningless (#13).
"""

from __future__ import annotations

from typing import Optional

from app.market_structure.schemas import Direction, TrendClass
from app.research.baseline import stats_over_indices
from app.research.replay import BaselineSample
from app.research.schemas import GroupOutcomeStats, HorizonStat
from app.schemas.market_data import Candle


def compute_direction_matched_baseline(
    candles: list[Candle],
    baseline_samples: list[BaselineSample],
    direction: Direction,
    horizons: tuple,
    min_bucket_size: int,
) -> Optional[GroupOutcomeStats]:
    return _matched_baseline(
        candles,
        baseline_samples,
        horizons,
        min_bucket_size,
        matches=lambda s: s.regime == direction.value,
    )


def compute_structure_matched_baseline(
    candles: list[Candle],
    baseline_samples: list[BaselineSample],
    primary_trend: Optional[TrendClass],
    daily_structure: Optional[TrendClass],
    four_hour_structure: Optional[TrendClass],
    horizons: tuple,
    min_bucket_size: int,
) -> Optional[GroupOutcomeStats]:
    """None for any of the three trend arguments means "don't condition on
    this dimension" -- only the dimensions the caller actually has frozen
    context for are matched on, never a guessed value."""

    def matches(sample: BaselineSample) -> bool:
        if primary_trend is not None and sample.regime != primary_trend.value:
            return False
        if daily_structure is not None and sample.daily_trend != daily_structure.value:
            return False
        if four_hour_structure is not None and sample.four_hour_trend != four_hour_structure.value:
            return False
        return True

    return _matched_baseline(candles, baseline_samples, horizons, min_bucket_size, matches=matches)


def _matched_baseline(
    candles: list[Candle],
    baseline_samples: list[BaselineSample],
    horizons: tuple,
    min_bucket_size: int,
    matches,
) -> Optional[GroupOutcomeStats]:
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in sorted_candles]
    index_by_timestamp = {c.timestamp: i for i, c in enumerate(sorted_candles)}

    matching_indices = [
        index_by_timestamp[sample.timestamp]
        for sample in baseline_samples
        if matches(sample) and sample.timestamp in index_by_timestamp
    ]
    if len(matching_indices) < min_bucket_size:
        return None
    return stats_over_indices(closes, matching_indices, horizons)


def horizon_stat_at(stats: Optional[GroupOutcomeStats], horizon_bars: int) -> Optional[HorizonStat]:
    if stats is None:
        return None
    return next((h for h in stats.directional_return_by_horizon if h.horizon_bars == horizon_bars), None)


def observed_excess_outcome(
    setup_stats: GroupOutcomeStats,
    baseline_stats: Optional[GroupOutcomeStats],
    horizon_bars: int,
) -> Optional[float]:
    """(#14) setup median directional return minus the matched baseline's
    median, at one horizon. Deliberately NOT called alpha, edge, or
    probability of success anywhere -- it is a difference of two medians,
    nothing more. None whenever either side lacks data at this horizon."""
    setup_horizon = horizon_stat_at(setup_stats, horizon_bars)
    baseline_horizon = horizon_stat_at(baseline_stats, horizon_bars)
    if setup_horizon is None or baseline_horizon is None:
        return None
    if setup_horizon.median is None or baseline_horizon.median is None:
        return None
    return setup_horizon.median - baseline_horizon.median
