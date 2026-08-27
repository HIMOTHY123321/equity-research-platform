from datetime import datetime, timezone

from app.research.schemas import SampleSizeLabel
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.evidence_flags import compute_evidence_flags, compute_independence_flags
from app.research_intelligence.schemas import (
    BootstrapInterval,
    ConcentrationWarning,
    ConclusionLabel,
    ConclusionStabilityReport,
    CrossSymbolStabilityReport,
    DistributionSummary,
    EvidenceQualityFlag,
    GroupComparisonResult,
    OverlapReport,
    Partition,
    SampleConcentrationReport,
    SetupEpisode,
    StabilityLabel,
    TemporalStabilityReport,
    WalkForwardReport,
)

_CONFIG = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG


def test_insufficient_sample_flag():
    flags = compute_evidence_flags(SampleSizeLabel.INSUFFICIENT)
    assert flags == [EvidenceQualityFlag.INSUFFICIENT_SAMPLE]


def test_small_sample_flag():
    flags = compute_evidence_flags(SampleSizeLabel.SMALL)
    assert flags == [EvidenceQualityFlag.SMALL_SAMPLE]


def test_larger_sample_produces_no_sample_size_flag():
    flags = compute_evidence_flags(SampleSizeLabel.LARGER)
    assert EvidenceQualityFlag.INSUFFICIENT_SAMPLE not in flags
    assert EvidenceQualityFlag.SMALL_SAMPLE not in flags


def test_overlap_flag_only_when_pairs_overlap():
    no_overlap = OverlapReport(
        horizon_bars=5,
        sample_count=10,
        overlapping_pair_count=0,
        overlapping_entry_count=0,
        overlap_fraction=0.0,
    )
    with_overlap = OverlapReport(
        horizon_bars=5,
        sample_count=10,
        overlapping_pair_count=3,
        overlapping_entry_count=5,
        overlap_fraction=0.5,
    )
    assert EvidenceQualityFlag.OVERLAPPING_OBSERVATIONS not in compute_evidence_flags(
        SampleSizeLabel.LARGER, overlap_report=no_overlap
    )
    assert EvidenceQualityFlag.OVERLAPPING_OBSERVATIONS in compute_evidence_flags(
        SampleSizeLabel.LARGER, overlap_report=with_overlap
    )


def test_symbol_and_temporal_concentration_flags():
    report = SampleConcentrationReport(
        sample_count=10,
        warnings=[
            ConcentrationWarning(dimension="symbol", dominant_value="NVDA", share=0.72, warning="x"),
            ConcentrationWarning(dimension="month", dominant_value="2026-08", share=0.8, warning="y"),
        ],
    )
    flags = compute_evidence_flags(SampleSizeLabel.LARGER, concentration_report=report)
    assert EvidenceQualityFlag.SYMBOL_CONCENTRATION in flags
    assert EvidenceQualityFlag.TEMPORAL_CONCENTRATION in flags


def test_result_unstable_flag_from_temporal_report():
    unstable = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.UNSTABLE,
        stability_basis="x",
    )
    stable = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.STABLE,
        stability_basis="x",
    )
    assert EvidenceQualityFlag.RESULT_UNSTABLE in compute_evidence_flags(
        SampleSizeLabel.LARGER, temporal_report=unstable
    )
    assert EvidenceQualityFlag.RESULT_UNSTABLE not in compute_evidence_flags(
        SampleSizeLabel.LARGER, temporal_report=stable
    )


def test_out_of_sample_reversal_flag():
    reversing = {
        Partition.DEVELOPMENT.value: 0.4,
        Partition.VALIDATION.value: 0.2,
        Partition.TEST.value: -0.3,
    }
    consistent = {
        Partition.DEVELOPMENT.value: 0.4,
        Partition.VALIDATION.value: 0.3,
        Partition.TEST.value: 0.2,
    }
    assert EvidenceQualityFlag.OUT_OF_SAMPLE_REVERSAL in compute_evidence_flags(
        SampleSizeLabel.LARGER, partition_medians=reversing
    )
    assert EvidenceQualityFlag.OUT_OF_SAMPLE_REVERSAL not in compute_evidence_flags(
        SampleSizeLabel.LARGER, partition_medians=consistent
    )


def test_reversal_flag_not_raised_with_missing_partitions():
    partial = {Partition.DEVELOPMENT.value: 0.4, Partition.VALIDATION.value: None, Partition.TEST.value: None}
    assert EvidenceQualityFlag.OUT_OF_SAMPLE_REVERSAL not in compute_evidence_flags(
        SampleSizeLabel.LARGER, partition_medians=partial
    )


def test_data_limitation_flag():
    assert EvidenceQualityFlag.DATA_LIMITATION in compute_evidence_flags(
        SampleSizeLabel.LARGER, data_limitation_notes=["only 60 days of 5m history available"]
    )
    assert EvidenceQualityFlag.DATA_LIMITATION not in compute_evidence_flags(SampleSizeLabel.LARGER)


def test_multiple_comparison_warning_flag_threshold():
    from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG

    threshold = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.multiple_comparison_warning_threshold
    below = compute_evidence_flags(SampleSizeLabel.LARGER, comparisons_displayed_count=threshold - 1)
    at = compute_evidence_flags(SampleSizeLabel.LARGER, comparisons_displayed_count=threshold)
    assert EvidenceQualityFlag.MULTIPLE_COMPARISON_WARNING not in below
    assert EvidenceQualityFlag.MULTIPLE_COMPARISON_WARNING in at


def test_all_flags_can_combine_on_a_genuinely_weak_cohort():
    overlap = OverlapReport(
        horizon_bars=5,
        sample_count=5,
        overlapping_pair_count=2,
        overlapping_entry_count=4,
        overlap_fraction=0.8,
    )
    concentration = SampleConcentrationReport(
        sample_count=5,
        warnings=[ConcentrationWarning(dimension="symbol", dominant_value="NVDA", share=0.9, warning="x")],
    )
    unstable = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.UNSTABLE,
        stability_basis="x",
    )
    flags = compute_evidence_flags(
        SampleSizeLabel.INSUFFICIENT,
        overlap_report=overlap,
        concentration_report=concentration,
        temporal_report=unstable,
        data_limitation_notes=["thin history"],
        comparisons_displayed_count=50,
    )
    assert set(flags) == {
        EvidenceQualityFlag.INSUFFICIENT_SAMPLE,
        EvidenceQualityFlag.OVERLAPPING_OBSERVATIONS,
        EvidenceQualityFlag.SYMBOL_CONCENTRATION,
        EvidenceQualityFlag.RESULT_UNSTABLE,
        EvidenceQualityFlag.DATA_LIMITATION,
        EvidenceQualityFlag.MULTIPLE_COMPARISON_WARNING,
    }


# ---------------------------------------------------------------------------
# compute_independence_flags (Phase 9 #23)
# ---------------------------------------------------------------------------


def _episode(episode_id: str, raw_observation_count: int) -> SetupEpisode:
    return SetupEpisode(
        episode_id=episode_id,
        setup_type="breakout_retest",
        direction="bullish",
        symbol="SPY",
        timeframe="1h",
        member_setup_ids=[f"{episode_id}-{i}" for i in range(raw_observation_count)],
        first_detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_member_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        qualification_states_represented=["qualified"],
        raw_observation_count=raw_observation_count,
        representative_setup_id=f"{episode_id}-0",
    )


def _comparison(median_difference: float) -> GroupComparisonResult:
    return GroupComparisonResult(
        group_a_label="a",
        group_b_label="b",
        horizon_bars=5,
        group_a_distribution=DistributionSummary(n=50, median=1.0),
        group_b_distribution=DistributionSummary(n=50, median=1.0),
        median_difference=median_difference,
        median_difference_bootstrap=BootstrapInterval(available=False, statistic="median"),
    )


def _conclusion(label: ConclusionLabel) -> ConclusionStabilityReport:
    return ConclusionStabilityReport(
        finding_label="test finding",
        horizon_bars=5,
        raw=_comparison(1.0),
        episode=_comparison(1.0),
        purged=_comparison(1.0),
        label=label,
        label_basis="test",
    )


def _cross_symbol(symbols_with_data: int) -> CrossSymbolStabilityReport:
    return CrossSymbolStabilityReport(
        horizon_bars=5,
        pooled=DistributionSummary(n=10, median=0.1),
        per_symbol=[],
        symbols_positive_median=symbols_with_data,
        symbols_negative_median=0,
        symbols_with_data=symbols_with_data,
    )


def _walk_forward(stability: StabilityLabel) -> WalkForwardReport:
    return WalkForwardReport(
        finding_label="test",
        horizon_bars=5,
        windows=[],
        positive_median_window_count=0,
        negative_median_window_count=0,
        stability=stability,
        stability_basis="test",
    )


def test_high_overlap_flag_uses_the_concentration_share_threshold():
    below = compute_independence_flags(50, overlap_rate=_CONFIG.concentration_warning_share - 0.01)
    at = compute_independence_flags(50, overlap_rate=_CONFIG.concentration_warning_share)
    assert EvidenceQualityFlag.HIGH_OVERLAP not in below
    assert EvidenceQualityFlag.HIGH_OVERLAP in at


def test_low_independent_sample_flag_uses_small_sample_min():
    below = compute_independence_flags(100, purged_sample_count=_CONFIG.small_sample_min - 1)
    at = compute_independence_flags(100, purged_sample_count=_CONFIG.small_sample_min)
    assert EvidenceQualityFlag.LOW_INDEPENDENT_SAMPLE in below
    assert EvidenceQualityFlag.LOW_INDEPENDENT_SAMPLE not in at


def test_episode_concentration_flag_from_dominant_episode_share():
    # One episode of 8 out of 10 raw entries -> 80% share, above the 50% threshold.
    dominated = [_episode("e1", 8), _episode("e2", 2)]
    diverse = [_episode("e1", 2), _episode("e2", 2), _episode("e3", 2), _episode("e4", 2), _episode("e5", 2)]
    assert EvidenceQualityFlag.EPISODE_CONCENTRATION in compute_independence_flags(10, episodes=dominated)
    assert EvidenceQualityFlag.EPISODE_CONCENTRATION not in compute_independence_flags(10, episodes=diverse)


def test_walk_forward_instability_flag():
    assert EvidenceQualityFlag.WALK_FORWARD_INSTABILITY in compute_independence_flags(
        50, walk_forward_report=_walk_forward(StabilityLabel.UNSTABLE)
    )
    assert EvidenceQualityFlag.WALK_FORWARD_INSTABILITY not in compute_independence_flags(
        50, walk_forward_report=_walk_forward(StabilityLabel.STABLE)
    )


def test_purged_result_reversal_flag_only_on_reverses_label():
    assert EvidenceQualityFlag.PURGED_RESULT_REVERSAL in compute_independence_flags(
        50, conclusion_stability_report=_conclusion(ConclusionLabel.REVERSES)
    )
    for other in (ConclusionLabel.SURVIVES, ConclusionLabel.WEAKENS, ConclusionLabel.DISAPPEARS):
        assert EvidenceQualityFlag.PURGED_RESULT_REVERSAL not in compute_independence_flags(
            50, conclusion_stability_report=_conclusion(other)
        )


def test_block_bootstrap_includes_zero_flag():
    spans_zero = BootstrapInterval(available=True, statistic="block_median", lower=-0.5, upper=0.5)
    excludes_zero = BootstrapInterval(available=True, statistic="block_median", lower=0.2, upper=0.5)
    unavailable = BootstrapInterval(available=False, statistic="block_median")
    assert EvidenceQualityFlag.BLOCK_BOOTSTRAP_INCLUDES_ZERO in compute_independence_flags(
        50, block_bootstrap_interval=spans_zero
    )
    assert EvidenceQualityFlag.BLOCK_BOOTSTRAP_INCLUDES_ZERO not in compute_independence_flags(
        50, block_bootstrap_interval=excludes_zero
    )
    assert EvidenceQualityFlag.BLOCK_BOOTSTRAP_INCLUDES_ZERO not in compute_independence_flags(
        50, block_bootstrap_interval=unavailable
    )


def test_single_symbol_dependence_flag():
    assert EvidenceQualityFlag.SINGLE_SYMBOL_DEPENDENCE in compute_independence_flags(
        50, cross_symbol_report=_cross_symbol(1)
    )
    assert EvidenceQualityFlag.SINGLE_SYMBOL_DEPENDENCE not in compute_independence_flags(
        50, cross_symbol_report=_cross_symbol(2)
    )


def test_temporal_instability_flag_covers_unstable_and_insufficient():
    unstable = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.UNSTABLE,
        stability_basis="x",
    )
    insufficient = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.INSUFFICIENT_DATA,
        stability_basis="x",
    )
    stable = TemporalStabilityReport(
        granularity="monthly",
        horizon_bars=5,
        buckets=[],
        stability=StabilityLabel.STABLE,
        stability_basis="x",
    )
    assert EvidenceQualityFlag.TEMPORAL_INSTABILITY in compute_independence_flags(
        50, temporal_report=unstable
    )
    assert EvidenceQualityFlag.TEMPORAL_INSTABILITY in compute_independence_flags(
        50, temporal_report=insufficient
    )
    assert EvidenceQualityFlag.TEMPORAL_INSTABILITY not in compute_independence_flags(
        50, temporal_report=stable
    )


def test_missing_reports_produce_no_independence_flags_and_no_crash():
    assert compute_independence_flags(50) == []
