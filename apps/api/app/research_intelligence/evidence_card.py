"""Research Evidence Cards (#29): the one standardized assembly point that
pulls together everything else in this package -- distribution, baseline,
observed excess, bootstrap interval, partition medians, cross-symbol
counts, and evidence-quality flags -- into a single deterministic record.
Never a score: every field is its own labeled statistic or an explicit
"not available."

Phase 9 #22 adds independence-adjusted fields to the same card (raw sample
count above stays unchanged and is never replaced): independent episode
count, a purged sample count at one caller-chosen horizon, the raw overlap
rate, the naive bootstrap's method label, and walk-forward window counts
with their stability label. All of it is optional -- `build_evidence_card`
still works exactly as it did in Phase 8 when `purged_horizon_bars` and
`conclusion_stability_report` are left at their defaults.
"""

from __future__ import annotations

from typing import Optional

from app.research.schemas import GroupOutcomeStats, SetupLedgerEntry
from app.research.summary import group_outcome_stats, horizon_values
from app.research_intelligence.baselines import horizon_stat_at, observed_excess_outcome
from app.research_intelligence.bootstrap import bootstrap_confidence_interval
from app.research_intelligence.concentration import detect_concentration
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.dependence import block_bootstrap_confidence_interval, detect_overlap
from app.research_intelligence.episodes import build_episodes
from app.research_intelligence.evidence_flags import compute_evidence_flags, compute_independence_flags
from app.research_intelligence.independence import purged_sample
from app.research_intelligence.schemas import ConclusionStabilityReport, Partition, ResearchEvidenceCard
from app.research_intelligence.stability import cross_symbol_stability, temporal_stability
from app.research_intelligence.statistics import sample_size_label, summarize_distribution
from app.research_intelligence.walk_forward import anchored_walk_forward
from app.schemas.market_data import Timeframe


def _partition_medians(
    entries: list[SetupLedgerEntry], horizon_bars: int, partition_by_setup_id: dict[str, Partition]
) -> dict[str, Optional[float]]:
    medians: dict[str, Optional[float]] = {}
    for partition in Partition:
        subset = [e for e in entries if partition_by_setup_id.get(e.setup_id) == partition]
        if not subset:
            medians[partition.value] = None
            continue
        medians[partition.value] = summarize_distribution(horizon_values(subset, horizon_bars)).median
    return medians


def build_evidence_card(
    setup_type: str,
    entries: list[SetupLedgerEntry],
    horizon_bars: int,
    timeframe: Timeframe,
    direction: Optional[str] = None,
    baseline_stats: Optional[GroupOutcomeStats] = None,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    seed: int = 0,
    comparisons_displayed_count: Optional[int] = None,
    data_limitation_notes: Optional[list[str]] = None,
    purged_horizon_bars: Optional[int] = None,
    conclusion_stability_report: Optional[ConclusionStabilityReport] = None,
    walk_forward_fold_count: int = 5,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> ResearchEvidenceCard:
    values = horizon_values(entries, horizon_bars)
    distribution = summarize_distribution(values)
    size_label = sample_size_label(distribution.n, config)
    bootstrap = bootstrap_confidence_interval(values, "median", seed, config)

    matched_baseline_median = None
    observed_excess = None
    if baseline_stats is not None:
        setup_stats = group_outcome_stats(entries, (horizon_bars,))
        baseline_horizon = horizon_stat_at(baseline_stats, horizon_bars)
        matched_baseline_median = baseline_horizon.median if baseline_horizon else None
        observed_excess = observed_excess_outcome(setup_stats, baseline_stats, horizon_bars)

    partition_medians = _partition_medians(entries, horizon_bars, partition_by_setup_id or {})

    cross_symbol = cross_symbol_stability(entries, horizon_bars)
    overlap_report = detect_overlap(entries, horizon_bars, timeframe)
    concentration_report = detect_concentration(entries, config)
    temporal_report = temporal_stability(entries, horizon_bars)

    # Phase 9 #22: independence-adjusted composition, computed from the same
    # `entries` this card already has -- episodes and walk-forward folds
    # need nothing else; a purged count needs one extra horizon choice
    # (defaults to this card's own `horizon_bars` when not overridden).
    episodes = build_episodes(entries)
    purged_count = len(purged_sample(entries, purged_horizon_bars or horizon_bars, timeframe))
    walk_forward_report = anchored_walk_forward(
        entries,
        horizon_bars,
        finding_label=f"{setup_type} {direction or ''}".strip(),
        fold_count=walk_forward_fold_count,
    )

    def _value_at_horizon(entry: SetupLedgerEntry) -> Optional[float]:
        if entry.outcome is None:
            return None
        match = next(
            (h for h in entry.outcome.horizons if h.horizon_bars == horizon_bars and h.available), None
        )
        return match.directional_return_percent if match else None

    block_bootstrap = block_bootstrap_confidence_interval(entries, _value_at_horizon, "median", seed, config)

    flags = compute_evidence_flags(
        size_label,
        overlap_report=overlap_report,
        concentration_report=concentration_report,
        temporal_report=temporal_report,
        partition_medians=partition_medians if partition_by_setup_id else None,
        data_limitation_notes=data_limitation_notes,
        comparisons_displayed_count=comparisons_displayed_count,
        config=config,
    )
    flags += compute_independence_flags(
        distribution.n,
        overlap_rate=overlap_report.overlap_fraction,
        purged_sample_count=purged_count,
        episodes=episodes,
        walk_forward_report=walk_forward_report,
        conclusion_stability_report=conclusion_stability_report,
        block_bootstrap_interval=block_bootstrap,
        cross_symbol_report=cross_symbol,
        temporal_report=temporal_report,
        config=config,
    )

    return ResearchEvidenceCard(
        setup_type=setup_type,
        direction=direction,
        horizon_bars=horizon_bars,
        sample_count=distribution.n,
        sample_size_label=size_label.value,
        median_directional_return=distribution.median,
        matched_baseline_median=matched_baseline_median,
        observed_excess=observed_excess,
        bootstrap_interval=bootstrap,
        partition_medians=partition_medians,
        symbols_positive=cross_symbol.symbols_positive_median,
        symbols_total=cross_symbol.symbols_with_data,
        independent_episode_count=len(episodes),
        purged_sample_count=purged_count,
        overlap_rate=overlap_report.overlap_fraction,
        bootstrap_method=block_bootstrap.method,
        block_bootstrap_interval=block_bootstrap,
        walk_forward_stability=walk_forward_report.stability.value,
        walk_forward_positive_windows=walk_forward_report.positive_median_window_count,
        walk_forward_negative_windows=walk_forward_report.negative_median_window_count,
        symbol_coverage_count=cross_symbol.symbols_with_data,
        temporal_coverage_buckets=len(temporal_report.buckets),
        flags=flags,
    )
