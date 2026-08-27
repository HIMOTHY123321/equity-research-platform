"""Baseline / control group (#20). A setup performing positively doesn't
prove it's useful -- almost any bullish timestamp looks good in a strong
uptrend. This computes plain forward returns for *every* eligible
historical bar (not just setup bars), so research can ask "did this setup
outperform just being randomly in this symbol/regime at any time?"
Deliberately simple: no statistical matching beyond a basic trend-regime
bucket, per the explicit "do not over-engineer" instruction.
"""

from __future__ import annotations

from app.research.replay import BaselineSample
from app.research.schemas import GroupOutcomeStats, HorizonStat
from app.research.summary import sample_size_label, summarize_values
from app.schemas.market_data import Candle


def _forward_return(base_index: int, sorted_closes: list[float], horizon_bars: int) -> float | None:
    target_index = base_index + horizon_bars
    if target_index >= len(sorted_closes):
        return None
    base_price = sorted_closes[base_index]
    if base_price == 0:
        return None
    return (sorted_closes[target_index] - base_price) / base_price * 100


def compute_unconditional_baseline(
    candles: list[Candle], horizons: tuple, min_bucket_size: int
) -> GroupOutcomeStats:
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in sorted_candles]
    return _stats_over_all_bars(closes, horizons, min_bucket_size)


def compute_regime_matched_baseline(
    candles: list[Candle],
    baseline_samples: list[BaselineSample],
    regime: str,
    horizons: tuple,
    min_bucket_size: int,
) -> GroupOutcomeStats | None:
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in sorted_candles]
    timestamps = [c.timestamp for c in sorted_candles]
    index_by_timestamp = {ts: idx for idx, ts in enumerate(timestamps)}

    matching_indices = [
        index_by_timestamp[sample.timestamp]
        for sample in baseline_samples
        if sample.regime == regime and sample.timestamp in index_by_timestamp
    ]
    if len(matching_indices) < min_bucket_size:
        return None

    return stats_over_indices(closes, matching_indices, horizons)


def _stats_over_all_bars(closes: list[float], horizons: tuple, min_bucket_size: int) -> GroupOutcomeStats:
    return stats_over_indices(closes, list(range(len(closes))), horizons)


def stats_over_indices(closes: list[float], indices: list[int], horizons: tuple) -> GroupOutcomeStats:
    horizon_stats = []
    for horizon_bars in horizons:
        values = [r for i in indices if (r := _forward_return(i, closes, horizon_bars)) is not None]
        stats = summarize_values(values)
        horizon_stats.append(
            HorizonStat(
                horizon_bars=horizon_bars,
                n=len(values),
                mean=stats.get("mean"),
                median=stats.get("median"),
                p25=stats.get("p25"),
                p75=stats.get("p75"),
            )
        )

    n = horizon_stats[0].n if horizon_stats else 0
    return GroupOutcomeStats(
        sample_count=n,
        sample_size_label=sample_size_label(n),
        directional_return_by_horizon=horizon_stats,
        mfe_atr=None,
        mae_atr=None,
    )
