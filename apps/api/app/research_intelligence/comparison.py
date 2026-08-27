"""Generic two-group comparison (#15, #16). `compare_groups` is the one
place this logic lives -- expanded qualification lift (#15: qualified vs.
rejected for the same setup family) and rejection-reason value (#16: one
rejection code's sample vs. the qualified sample) are both just different
choices of which ledger entries go in group A vs. group B, layered on top
of Phase 7's `group_outcome_stats`/`horizon_values`
(`app/research/summary.py`) rather than re-implementing outcome extraction.
"""

from __future__ import annotations

from typing import Optional

from app.research.schemas import GroupOutcomeStats, SetupLedgerEntry
from app.research.summary import group_outcome_stats, horizon_values
from app.research_intelligence.baselines import observed_excess_outcome
from app.research_intelligence.bootstrap import bootstrap_difference_confidence_interval
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.effect_size import (
    cliffs_delta,
    difference_of_means,
    difference_of_medians,
    standardized_effect_size,
)
from app.research_intelligence.schemas import GroupComparisonResult, Partition, PartitionComparisonSummary
from app.research_intelligence.statistics import summarize_distribution


def _mfe_mae_atr_values(entries: list[SetupLedgerEntry], field: str) -> list[float]:
    values = []
    for entry in entries:
        if entry.outcome is None:
            continue
        atr = getattr(getattr(entry.outcome, field), "atr", None)
        if atr is not None:
            values.append(atr)
    return values


def _partition_summary(
    group_a: list[SetupLedgerEntry], group_b: list[SetupLedgerEntry], horizon_bars: int
) -> PartitionComparisonSummary:
    a_values = horizon_values(group_a, horizon_bars)
    b_values = horizon_values(group_b, horizon_bars)
    a_median = summarize_distribution(a_values).median
    b_median = summarize_distribution(b_values).median
    diff = a_median - b_median if a_median is not None and b_median is not None else None
    return PartitionComparisonSummary(
        group_a_n=len(group_a),
        group_b_n=len(group_b),
        group_a_median=a_median,
        group_b_median=b_median,
        median_difference=diff,
    )


def compare_groups(
    group_a: list[SetupLedgerEntry],
    group_b: list[SetupLedgerEntry],
    group_a_label: str,
    group_b_label: str,
    horizon_bars: int,
    seed: int,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    group_a_baseline: Optional[GroupOutcomeStats] = None,
    group_b_baseline: Optional[GroupOutcomeStats] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> GroupComparisonResult:
    a_values = horizon_values(group_a, horizon_bars)
    b_values = horizon_values(group_b, horizon_bars)

    partition_breakdown: dict[str, PartitionComparisonSummary] = {}
    if partition_by_setup_id:
        for partition in Partition:
            a_slice = [e for e in group_a if partition_by_setup_id.get(e.setup_id) == partition]
            b_slice = [e for e in group_b if partition_by_setup_id.get(e.setup_id) == partition]
            if not a_slice and not b_slice:
                continue
            partition_breakdown[partition.value] = _partition_summary(a_slice, b_slice, horizon_bars)

    group_a_stats = summarize_distribution(a_values)
    group_b_stats = summarize_distribution(b_values)

    group_a_excess = (
        observed_excess_outcome(group_outcome_stats(group_a, (horizon_bars,)), group_a_baseline, horizon_bars)
        if group_a_baseline is not None
        else None
    )
    group_b_excess = (
        observed_excess_outcome(group_outcome_stats(group_b, (horizon_bars,)), group_b_baseline, horizon_bars)
        if group_b_baseline is not None
        else None
    )

    return GroupComparisonResult(
        group_a_label=group_a_label,
        group_b_label=group_b_label,
        horizon_bars=horizon_bars,
        group_a_distribution=group_a_stats,
        group_b_distribution=group_b_stats,
        median_difference=difference_of_medians(a_values, b_values),
        mean_difference=difference_of_means(a_values, b_values),
        standardized_effect_size=standardized_effect_size(a_values, b_values),
        cliffs_delta=cliffs_delta(a_values, b_values),
        mfe_atr_median_difference=difference_of_medians(
            _mfe_mae_atr_values(group_a, "mfe"), _mfe_mae_atr_values(group_b, "mfe")
        ),
        mae_atr_median_difference=difference_of_medians(
            _mfe_mae_atr_values(group_a, "mae"), _mfe_mae_atr_values(group_b, "mae")
        ),
        median_difference_bootstrap=bootstrap_difference_confidence_interval(
            a_values, b_values, "median", seed, config
        ),
        group_a_baseline_adjusted_excess=group_a_excess,
        group_b_baseline_adjusted_excess=group_b_excess,
        partition_breakdown=partition_breakdown,
    )
