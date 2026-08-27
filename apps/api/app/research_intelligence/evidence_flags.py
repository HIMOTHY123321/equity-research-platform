"""Evidence quality flags (#30). Each flag is a deterministic function of
an explicit, already-computed report -- never a subjective call. Weak
research must look weak: a cohort with a tiny, concentrated, unstable
sample gets every flag that applies, not a softened summary.

`compute_independence_flags` (Phase 9 #23) is a separate function, not an
extension of `compute_evidence_flags`'s signature -- Phase 8 callers keep
working unchanged, and Phase 9 independence data (episodes, purged samples,
walk-forward, block bootstrap) is genuinely optional per call site.
"""

from __future__ import annotations

from typing import Optional

from app.research.schemas import SampleSizeLabel
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import (
    BootstrapInterval,
    ConclusionLabel,
    ConclusionStabilityReport,
    CrossSymbolStabilityReport,
    EvidenceQualityFlag,
    OverlapReport,
    SampleConcentrationReport,
    SetupEpisode,
    StabilityLabel,
    TemporalStabilityReport,
    WalkForwardReport,
)


def compute_evidence_flags(
    sample_size_label: SampleSizeLabel,
    overlap_report: Optional[OverlapReport] = None,
    concentration_report: Optional[SampleConcentrationReport] = None,
    temporal_report: Optional[TemporalStabilityReport] = None,
    partition_medians: Optional[dict[str, Optional[float]]] = None,
    data_limitation_notes: Optional[list[str]] = None,
    comparisons_displayed_count: Optional[int] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[EvidenceQualityFlag]:
    flags: list[EvidenceQualityFlag] = []

    if sample_size_label == SampleSizeLabel.INSUFFICIENT:
        flags.append(EvidenceQualityFlag.INSUFFICIENT_SAMPLE)
    elif sample_size_label == SampleSizeLabel.SMALL:
        flags.append(EvidenceQualityFlag.SMALL_SAMPLE)

    if overlap_report is not None and overlap_report.overlapping_pair_count > 0:
        flags.append(EvidenceQualityFlag.OVERLAPPING_OBSERVATIONS)

    if concentration_report is not None:
        dimensions = {w.dimension for w in concentration_report.warnings}
        if "symbol" in dimensions:
            flags.append(EvidenceQualityFlag.SYMBOL_CONCENTRATION)
        if "month" in dimensions:
            flags.append(EvidenceQualityFlag.TEMPORAL_CONCENTRATION)

    if temporal_report is not None and temporal_report.stability == StabilityLabel.UNSTABLE:
        flags.append(EvidenceQualityFlag.RESULT_UNSTABLE)

    if partition_medians:
        signs = {(v > 0) for v in partition_medians.values() if v is not None and v != 0}
        development = partition_medians.get("development")
        test = partition_medians.get("test")
        both_present = development is not None and test is not None
        opposite_signs = both_present and (development > 0) != (test > 0)
        if opposite_signs and len(signs) > 1:
            flags.append(EvidenceQualityFlag.OUT_OF_SAMPLE_REVERSAL)

    if data_limitation_notes:
        flags.append(EvidenceQualityFlag.DATA_LIMITATION)

    comparison_threshold = config.multiple_comparison_warning_threshold
    if comparisons_displayed_count is not None and comparisons_displayed_count >= comparison_threshold:
        flags.append(EvidenceQualityFlag.MULTIPLE_COMPARISON_WARNING)

    return flags


def compute_independence_flags(
    raw_sample_count: int,
    overlap_rate: Optional[float] = None,
    purged_sample_count: Optional[int] = None,
    episodes: Optional[list[SetupEpisode]] = None,
    walk_forward_report: Optional[WalkForwardReport] = None,
    conclusion_stability_report: Optional[ConclusionStabilityReport] = None,
    block_bootstrap_interval: Optional[BootstrapInterval] = None,
    cross_symbol_report: Optional[CrossSymbolStabilityReport] = None,
    temporal_report: Optional[TemporalStabilityReport] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[EvidenceQualityFlag]:
    """(Phase 9 #23) Every argument is optional and independently checked --
    a caller with only some Phase 9 reports available still gets whichever
    flags it can support, never a crash on a missing one."""
    flags: list[EvidenceQualityFlag] = []

    if overlap_rate is not None and overlap_rate >= config.concentration_warning_share:
        flags.append(EvidenceQualityFlag.HIGH_OVERLAP)

    if purged_sample_count is not None and purged_sample_count < config.small_sample_min:
        flags.append(EvidenceQualityFlag.LOW_INDEPENDENT_SAMPLE)

    if episodes and raw_sample_count > 0:
        largest = max(ep.raw_observation_count for ep in episodes)
        if (largest / raw_sample_count) >= config.concentration_warning_share:
            flags.append(EvidenceQualityFlag.EPISODE_CONCENTRATION)

    if walk_forward_report is not None and walk_forward_report.stability == StabilityLabel.UNSTABLE:
        flags.append(EvidenceQualityFlag.WALK_FORWARD_INSTABILITY)

    if (
        conclusion_stability_report is not None
        and conclusion_stability_report.label == ConclusionLabel.REVERSES
    ):
        flags.append(EvidenceQualityFlag.PURGED_RESULT_REVERSAL)

    if (
        block_bootstrap_interval is not None
        and block_bootstrap_interval.available
        and block_bootstrap_interval.lower is not None
        and block_bootstrap_interval.upper is not None
        and block_bootstrap_interval.lower <= 0.0 <= block_bootstrap_interval.upper
    ):
        flags.append(EvidenceQualityFlag.BLOCK_BOOTSTRAP_INCLUDES_ZERO)

    if cross_symbol_report is not None and cross_symbol_report.symbols_with_data <= 1:
        flags.append(EvidenceQualityFlag.SINGLE_SYMBOL_DEPENDENCE)

    if temporal_report is not None and temporal_report.stability in (
        StabilityLabel.UNSTABLE,
        StabilityLabel.INSUFFICIENT_DATA,
    ):
        flags.append(EvidenceQualityFlag.TEMPORAL_INSTABILITY)

    return flags
