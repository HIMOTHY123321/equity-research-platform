"""Descriptive statistics for research results (#35, #36, #38, #39). Every
number here is a plain descriptive statistic -- no significance testing, no
p-values, no claim of predictive power (#22, #38, #39 are explicit about
this: "observed historical difference", never "alpha" or "edge").
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from app.research.config import DEFAULT_RESEARCH_CONFIG, ResearchConfig
from app.research.schemas import (
    GroupOutcomeStats,
    HorizonStat,
    QualificationLift,
    RejectionValueEntry,
    SampleSizeLabel,
    SetupLedgerEntry,
)


def sample_size_label(n: int, config: ResearchConfig = DEFAULT_RESEARCH_CONFIG) -> SampleSizeLabel:
    if n >= config.larger_sample_min:
        return SampleSizeLabel.LARGER
    if n >= config.moderate_sample_min:
        return SampleSizeLabel.MODERATE
    if n >= config.small_sample_min:
        return SampleSizeLabel.SMALL
    return SampleSizeLabel.INSUFFICIENT


def summarize_values(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "median": None, "p25": None, "p75": None}
    sorted_values = sorted(values)
    return {
        "mean": statistics.fmean(sorted_values),
        "median": statistics.median(sorted_values),
        "p25": _percentile(sorted_values, 25),
        "p75": _percentile(sorted_values, 75),
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100)
    lower, upper = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    fraction = k - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def group_outcome_stats(entries: list[SetupLedgerEntry], horizons: tuple) -> GroupOutcomeStats:
    horizon_stats = []
    for horizon_bars in horizons:
        values = []
        for entry in entries:
            if entry.outcome is None:
                continue
            matching = next(
                (h for h in entry.outcome.horizons if h.horizon_bars == horizon_bars and h.available), None
            )
            if matching is not None:
                values.append(matching.directional_return_percent)
        stats = summarize_values(values)
        horizon_stats.append(
            HorizonStat(
                horizon_bars=horizon_bars,
                n=len(values),
                mean=stats["mean"],
                median=stats["median"],
                p25=stats["p25"],
                p75=stats["p75"],
            )
        )

    mfe_values = [e.outcome.mfe.atr for e in entries if e.outcome and e.outcome.mfe.atr is not None]
    mae_values = [e.outcome.mae.atr for e in entries if e.outcome and e.outcome.mae.atr is not None]
    mfe_stats = summarize_values(mfe_values)
    mae_stats = summarize_values(mae_values)

    n = len(entries)
    return GroupOutcomeStats(
        sample_count=n,
        sample_size_label=sample_size_label(n),
        directional_return_by_horizon=horizon_stats,
        mfe_atr=HorizonStat(horizon_bars=0, n=len(mfe_values), **mfe_stats),
        mae_atr=HorizonStat(horizon_bars=0, n=len(mae_values), **mae_stats),
    )


def qualification_lift(
    qualified: list[SetupLedgerEntry], rejected: list[SetupLedgerEntry], horizons: tuple
) -> list[QualificationLift]:
    results = []
    for horizon_bars in horizons:
        qualified_values = horizon_values(qualified, horizon_bars)
        rejected_values = horizon_values(rejected, horizon_bars)
        qualified_median = statistics.median(qualified_values) if qualified_values else None
        rejected_median = statistics.median(rejected_values) if rejected_values else None
        observed_difference = (
            (qualified_median - rejected_median)
            if qualified_median is not None and rejected_median is not None
            else None
        )
        results.append(
            QualificationLift(
                horizon_bars=horizon_bars,
                qualified_median=qualified_median,
                rejected_median=rejected_median,
                observed_difference=observed_difference,
            )
        )
    return results


def rejection_value(
    rejected: list[SetupLedgerEntry],
    qualified: list[SetupLedgerEntry],
    config: ResearchConfig = DEFAULT_RESEARCH_CONFIG,
) -> list[RejectionValueEntry]:
    """For each rejection reason code, compares that code's rejected-sample
    5-bar outcome against the same setup type's qualified outcome (#39) --
    a purely descriptive comparison, never a causal claim."""
    by_code: dict[str, list[SetupLedgerEntry]] = defaultdict(list)
    for entry in rejected:
        for check in entry.detection.hard_checks:
            if not check.passed:
                by_code[check.code].append(entry)

    qualified_5bar = horizon_values(qualified, 5)
    qualified_median_5bar = statistics.median(qualified_5bar) if qualified_5bar else None

    results = []
    for code, entries in sorted(by_code.items()):
        values = horizon_values(entries, 5)
        n = len(entries)
        results.append(
            RejectionValueEntry(
                rejection_code=code,
                sample_count=n,
                sample_size_label=sample_size_label(n, config),
                median_5bar_directional_return=statistics.median(values) if values else None,
                comparable_qualified_median_5bar_directional_return=qualified_median_5bar,
            )
        )
    return results


def horizon_values(entries: list[SetupLedgerEntry], horizon_bars: int) -> list[float]:
    values = []
    for entry in entries:
        if entry.outcome is None:
            continue
        matching = next(
            (h for h in entry.outcome.horizons if h.horizon_bars == horizon_bars and h.available), None
        )
        if matching is not None:
            values.append(matching.directional_return_percent)
    return values
