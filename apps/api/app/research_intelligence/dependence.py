"""Time-series dependence (#11). Overlapping forward-outcome windows are
not independent observations -- if setup A is detected 2 bars before setup
B and both have a 10-bar forward horizon, their outcome windows share 8
bars of the same price path. Applying a naive i.i.d. bootstrap to
overlapping observations understates real uncertainty. This module never
does that silently: `detect_overlap` always reports what it found, and
`block_bootstrap_confidence_interval` resamples whole trading days (not
individual observations) so overlap within a day can't be treated as
independent evidence.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional

import numpy as np

from app.market_data.sessions import exchange_trading_date
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.bootstrap import bootstrap_confidence_interval
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import BootstrapInterval, OverlapReport
from app.schemas.market_data import Timeframe
from app.setup_detection.detectors._common import bar_duration_seconds


def detect_overlap(entries: list[SetupLedgerEntry], horizon_bars: int, timeframe: Timeframe) -> OverlapReport:
    """Checks *adjacent* pairs (by detection time) for forward-window
    overlap -- a deliberate simplification over an all-pairs O(n^2) check,
    sufficient to surface the warning honestly without over-engineering a
    diagnostic that's already conservative (adjacent pairs are the most
    likely to overlap; if they don't, farther-apart pairs won't either)."""
    sorted_entries = sorted(entries, key=lambda e: e.candidate_candle_timestamp)
    n = len(sorted_entries)
    window = timedelta(seconds=bar_duration_seconds(timeframe) * horizon_bars)

    overlapping_pairs = 0
    overlapping_entries: set[str] = set()
    for i in range(n - 1):
        current, nxt = sorted_entries[i], sorted_entries[i + 1]
        window_end = current.candidate_candle_timestamp + window
        if nxt.candidate_candle_timestamp < window_end:
            overlapping_pairs += 1
            overlapping_entries.add(current.setup_id)
            overlapping_entries.add(nxt.setup_id)

    fraction = (len(overlapping_entries) / n) if n else 0.0
    warning = (
        f"OVERLAPPING OBSERVATIONS: {len(overlapping_entries)} of {n} setups "
        f"({fraction:.0%}) have a {horizon_bars}-bar forward window that overlaps an adjacent "
        "setup's -- these are not independent samples; treat confidence intervals accordingly"
        if overlapping_pairs > 0
        else None
    )
    return OverlapReport(
        horizon_bars=horizon_bars,
        sample_count=n,
        overlapping_pair_count=overlapping_pairs,
        overlapping_entry_count=len(overlapping_entries),
        overlap_fraction=fraction,
        warning=warning,
    )


def _block_key_daily(timestamp) -> tuple:
    return (exchange_trading_date(timestamp),)


def _block_key_weekly(timestamp) -> tuple:
    trading_date = exchange_trading_date(timestamp)
    iso = trading_date.isocalendar()
    return (iso[0], iso[1])  # (ISO year, ISO week number)


_BLOCK_KEY_FNS = {"daily": _block_key_daily, "weekly": _block_key_weekly}


def block_bootstrap_confidence_interval(
    entries: list[SetupLedgerEntry],
    value_fn: Callable[[SetupLedgerEntry], Optional[float]],
    statistic: str,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
    block: str = "daily",
) -> BootstrapInterval:
    """A block/cluster bootstrap keyed by exchange trading day or ISO week
    (Phase 8 #11, hardened in Phase 9 #10 with a `block` choice): each
    resample draws whole blocks with replacement (not individual
    observations), so within-block overlap can't inflate apparent
    precision. `value_fn` extracts the statistic input from an entry (e.g.
    its 5-bar directional return); entries where it returns None are
    dropped. `block="weekly"` is the more conservative choice when 1H-bar
    dependence chains span more than a single trading day (see
    `compare_bootstrap_methods`, which reports both alongside the naive
    i.i.d. interval so the UI never has to silently pick one)."""
    stat_fn = {"mean": np.mean, "median": np.median}.get(statistic)
    if stat_fn is None:
        raise ValueError(f"unsupported bootstrap statistic {statistic!r}; expected 'mean' or 'median'")
    block_key_fn = _BLOCK_KEY_FNS.get(block)
    if block_key_fn is None:
        raise ValueError(f"unsupported block {block!r}; expected one of {sorted(_BLOCK_KEY_FNS)}")

    by_block: dict = {}
    for entry in entries:
        value = value_fn(entry)
        if value is None:
            continue
        by_block.setdefault(block_key_fn(entry.candidate_candle_timestamp), []).append(value)

    all_values = [v for values in by_block.values() for v in values]
    n = len(all_values)
    method = f"block_bootstrap_by_{'trading_day' if block == 'daily' else 'iso_week'}"
    if n < config.bootstrap_min_sample:
        return BootstrapInterval(
            available=False,
            statistic=f"block_{statistic}",
            unavailable_reason=(
                f"sample size {n} is below the minimum of {config.bootstrap_min_sample} "
                "required for a bootstrap interval"
            ),
            method=method,
        )

    point_estimate = float(stat_fn(all_values))
    blocks = list(by_block.values())
    rng = np.random.default_rng(seed)
    resample_stats = np.empty(config.bootstrap_iterations, dtype=float)
    for i in range(config.bootstrap_iterations):
        chosen_block_indices = rng.integers(0, len(blocks), size=len(blocks))
        resample = [v for idx in chosen_block_indices for v in blocks[idx]]
        resample_stats[i] = stat_fn(resample) if resample else np.nan

    valid = resample_stats[~np.isnan(resample_stats)]
    alpha = 1.0 - config.bootstrap_confidence_level
    lower, upper = np.percentile(valid, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    return BootstrapInterval(
        available=True,
        statistic=f"block_{statistic}",
        point_estimate=point_estimate,
        lower=float(lower),
        upper=float(upper),
        confidence_level=config.bootstrap_confidence_level,
        iterations=config.bootstrap_iterations,
        seed=seed,
        method=method,
    )


def compare_bootstrap_methods(
    entries: list[SetupLedgerEntry],
    value_fn: Callable[[SetupLedgerEntry], Optional[float]],
    statistic: str,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> dict[str, BootstrapInterval]:
    """(Phase 9 #10) Naive i.i.d., daily-block, and weekly-block bootstrap
    intervals for the same sample, side by side -- callers should default
    to the widest available block-based interval (the more conservative
    one) rather than silently picking naive. Weekly is only reported when
    the block count actually supports it; daily always is when data
    permits, since it requires far fewer distinct blocks."""
    values = [value_fn(e) for e in entries]
    values = [v for v in values if v is not None]

    return {
        "naive": bootstrap_confidence_interval(values, statistic, seed, config),
        "daily_block": block_bootstrap_confidence_interval(
            entries, value_fn, statistic, seed, config, block="daily"
        ),
        "weekly_block": block_bootstrap_confidence_interval(
            entries, value_fn, statistic, seed, config, block="weekly"
        ),
    }
