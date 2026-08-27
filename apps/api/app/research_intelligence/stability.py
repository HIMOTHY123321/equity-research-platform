"""Temporal stability (#21) and cross-symbol stability (#22/#23). Both
answer the same underlying question -- "does this cohort's result hold up
when you slice it a different way, or does it depend on which slice you
look at" -- for two different slicing dimensions: chronological buckets and
symbols. Neither ever collapses to a single pooled number; a setup that
looks good pooled but flips sign quarter to quarter, or is carried entirely
by one symbol, must show that here.
"""

from __future__ import annotations

import numpy as np

from app.market_data.sessions import exchange_trading_date
from app.research.schemas import SetupLedgerEntry
from app.research.summary import horizon_values
from app.research_intelligence.excursions import excursion_profile
from app.research_intelligence.schemas import (
    CrossSymbolStabilityReport,
    StabilityLabel,
    SymbolBucket,
    TemporalBucket,
    TemporalStabilityReport,
)
from app.research_intelligence.statistics import summarize_distribution


def bucket_label(entry: SetupLedgerEntry, granularity: str) -> str:
    trading_date = exchange_trading_date(entry.candidate_candle_timestamp)
    if granularity == "monthly":
        return f"{trading_date.year:04d}-{trading_date.month:02d}"
    if granularity == "quarterly":
        quarter = (trading_date.month - 1) // 3 + 1
        return f"{trading_date.year:04d}-Q{quarter}"
    raise ValueError(f"unsupported granularity {granularity!r}; expected 'monthly' or 'quarterly'")


def temporal_stability(
    entries: list[SetupLedgerEntry], horizon_bars: int, granularity: str = "monthly"
) -> TemporalStabilityReport:
    by_bucket: dict[str, list[SetupLedgerEntry]] = {}
    for entry in entries:
        by_bucket.setdefault(bucket_label(entry, granularity), []).append(entry)

    buckets = []
    for label in sorted(by_bucket):
        bucket_entries = by_bucket[label]
        timestamps = sorted(e.candidate_candle_timestamp for e in bucket_entries)
        distribution = summarize_distribution(horizon_values(bucket_entries, horizon_bars))
        buckets.append(
            TemporalBucket(
                bucket_label=label,
                start=timestamps[0],
                end=timestamps[-1],
                distribution=distribution,
            )
        )

    stability, basis = _classify_temporal_stability(buckets)
    return TemporalStabilityReport(
        granularity=granularity,
        horizon_bars=horizon_bars,
        buckets=buckets,
        stability=stability,
        stability_basis=basis,
    )


def _classify_temporal_stability(buckets: list[TemporalBucket]) -> tuple:
    usable = [b for b in buckets if b.distribution.median is not None]
    if len(usable) < 2:
        return StabilityLabel.INSUFFICIENT_DATA, "fewer than 2 buckets had a usable median"

    signs = {(b.distribution.median > 0) for b in usable if b.distribution.median != 0}
    labels_and_medians = {b.bucket_label: b.distribution.median for b in usable}
    if len(signs) > 1:
        return (
            StabilityLabel.UNSTABLE,
            f"median directional return changes sign across buckets: {labels_and_medians}",
        )
    return (
        StabilityLabel.STABLE,
        f"median directional return keeps the same sign across buckets: {labels_and_medians}",
    )


def cross_symbol_stability(entries: list[SetupLedgerEntry], horizon_bars: int) -> CrossSymbolStabilityReport:
    pooled = summarize_distribution(horizon_values(entries, horizon_bars))

    by_symbol: dict[str, list[SetupLedgerEntry]] = {}
    for entry in entries:
        by_symbol.setdefault(entry.symbol, []).append(entry)

    per_symbol = []
    positive, negative = 0, 0
    symbol_medians = []
    for symbol in sorted(by_symbol):
        symbol_entries = by_symbol[symbol]
        distribution = summarize_distribution(horizon_values(symbol_entries, horizon_bars))
        excursions = excursion_profile(symbol_entries)
        per_symbol.append(
            SymbolBucket(
                symbol=symbol,
                distribution=distribution,
                mfe_atr=excursions.mfe_atr,
                mae_atr=excursions.mae_atr,
            )
        )
        if distribution.median is not None:
            symbol_medians.append(distribution.median)
            if distribution.median > 0:
                positive += 1
            elif distribution.median < 0:
                negative += 1

    dispersion = float(np.std(symbol_medians, ddof=1)) if len(symbol_medians) >= 2 else None

    return CrossSymbolStabilityReport(
        horizon_bars=horizon_bars,
        pooled=pooled,
        per_symbol=per_symbol,
        symbols_positive_median=positive,
        symbols_negative_median=negative,
        symbols_with_data=len(symbol_medians),
        dispersion_of_symbol_medians=dispersion,
    )
