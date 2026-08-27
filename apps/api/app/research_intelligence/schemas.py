"""Typed research-intelligence outputs (Phase 8). Everything here is a
descriptive statistic, a sample-size disclosure, or a piece of dataset
provenance -- never a score, a probability of success, or a prediction.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Partition(str, Enum):
    """Chronological research partitions (#5). Never randomly shuffled --
    a timestamp belongs to exactly one partition, and partitions are always
    contiguous and time-ordered: development < validation < test."""

    DEVELOPMENT = "development"
    VALIDATION = "validation"
    TEST = "test"


class ResearchUniverse(BaseModel):
    """The fixed, configurable symbol set a research run covers (#3). Never
    hardcoded inside a detector or engine -- always passed in explicitly."""

    model_config = ConfigDict(frozen=True)

    symbols: tuple[str, ...] = ()
    timeframe: str = "1h"
    date_selection_rule: str = ""


class ProviderTimeframeCapability(BaseModel):
    """What the provider can actually deliver for one timeframe (#2) --
    inspected, never assumed. `source` distinguishes a live-measured value
    from a documented/known provider limit used when live inspection
    wasn't possible, so the two are never silently blurred together."""

    model_config = ConfigDict(frozen=True)

    timeframe: str
    max_reliable_lookback_days: Optional[int]
    interval_limitations: str
    extended_hours_supported: bool
    extended_hours_notes: str
    source: str  # "live_inspection" | "documented_provider_limit"
    inspected_at: Optional[datetime] = None


class ProviderCapabilityReport(BaseModel):
    """The full per-timeframe capability picture for one provider (#2)."""

    model_config = ConfigDict(frozen=True)

    provider: str
    timeframes: dict[str, ProviderTimeframeCapability]


class DatasetManifest(BaseModel):
    """Full reproducibility record for one research dataset pull (#4):
    everything needed to know exactly what data a research run's
    conclusions are based on, and to re-fetch (as closely as the provider
    allows) the same thing later."""

    model_config = ConfigDict(frozen=True)

    manifest_id: str
    provider: str
    symbols: tuple[str, ...]
    timeframe: str
    requested_start: datetime
    requested_end: datetime
    date_selection_rule: str
    per_symbol_bar_counts: dict[str, int]
    per_symbol_actual_start: dict[str, Optional[datetime]]
    per_symbol_actual_end: dict[str, Optional[datetime]]
    per_symbol_data_hash: dict[str, str]
    config_hash: str
    app_version: str
    adjustment_mode: str
    session_settings: str
    created_at: datetime


class DistributionSummary(BaseModel):
    """Descriptive statistics for one numeric sample (#9). Deliberately no
    "probability of success" or single-score field anywhere on this model --
    a distribution is reported as a distribution."""

    model_config = ConfigDict(frozen=True)

    n: int
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    p10: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None


class BootstrapInterval(BaseModel):
    """A bootstrap confidence interval for a statistic (#10). `available`
    is False (and the bounds are None) when the sample was too small to
    resample meaningfully -- never a fabricated narrow interval."""

    model_config = ConfigDict(frozen=True)

    available: bool
    statistic: str
    point_estimate: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    confidence_level: Optional[float] = None
    iterations: Optional[int] = None
    seed: Optional[int] = None
    method: str = "percentile_bootstrap"
    unavailable_reason: Optional[str] = None


class PartitionComparisonSummary(BaseModel):
    """One partition's slice of a two-group comparison (#6, #15, #16) --
    shown so instability across dev/validation/test is visible, never
    hidden behind a single pooled number."""

    model_config = ConfigDict(frozen=True)

    group_a_n: int
    group_b_n: int
    group_a_median: Optional[float] = None
    group_b_median: Optional[float] = None
    median_difference: Optional[float] = None


class GroupComparisonResult(BaseModel):
    """Two groups of the same setup family compared at one horizon (#15
    qualified-vs-rejected, #16 one rejection code vs. qualified). Never
    reduced to a single score -- every number here is a specific, labeled
    descriptive statistic or an explicit "not available"."""

    model_config = ConfigDict(frozen=True)

    group_a_label: str
    group_b_label: str
    horizon_bars: int
    group_a_distribution: DistributionSummary
    group_b_distribution: DistributionSummary
    median_difference: Optional[float] = None
    mean_difference: Optional[float] = None
    standardized_effect_size: Optional[float] = None
    cliffs_delta: Optional[float] = None
    mfe_atr_median_difference: Optional[float] = None
    mae_atr_median_difference: Optional[float] = None
    median_difference_bootstrap: BootstrapInterval
    group_a_baseline_adjusted_excess: Optional[float] = None
    group_b_baseline_adjusted_excess: Optional[float] = None
    partition_breakdown: dict[str, PartitionComparisonSummary] = {}


class ExcursionProfile(BaseModel):
    """(#19) Cohort-level MFE/MAE distributions, expanding Phase 7's
    single-value-per-entry excursion metrics into full distributions."""

    model_config = ConfigDict(frozen=True)

    mfe_percent: DistributionSummary
    mfe_atr: DistributionSummary
    mae_percent: DistributionSummary
    mae_atr: DistributionSummary
    bars_to_mfe: DistributionSummary
    bars_to_mae: DistributionSummary
    sample_count: int


class FirstHitOutcome(str, Enum):
    FAVORABLE_FIRST = "favorable_first"
    ADVERSE_FIRST = "adverse_first"
    NEITHER = "neither"


class FirstHitResult(BaseModel):
    """(#19/#20) Given a favorable and an adverse ATR threshold, which was
    reached first within the evaluation window -- a descriptive historical
    path statistic, explicitly NOT a trading stop or target."""

    model_config = ConfigDict(frozen=True)

    favorable_atr_threshold: float
    adverse_atr_threshold: float
    sample_count: int
    favorable_first_count: int
    adverse_first_count: int
    neither_count: int
    excluded_no_atr_count: int


class DecayPattern(str, Enum):
    """A simple, deterministic, descriptive label for how a cohort's
    directional-return magnitude changes across horizons (#18) -- never a
    forecast or "predictive confidence." See app/research_intelligence/decay.py
    for the exact, documented threshold rule that produces each label."""

    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    PERSISTENT = "persistent"
    DECAYING = "decaying"
    INCONCLUSIVE = "inconclusive"


class DecayHorizonStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    distribution: DistributionSummary
    bootstrap_interval: BootstrapInterval
    warnings: list[str] = []


class SignalDecayProfile(BaseModel):
    """(#18) The full multi-horizon decay picture for one cohort."""

    model_config = ConfigDict(frozen=True)

    horizons: list[DecayHorizonStat]
    pattern: DecayPattern
    pattern_basis: str


class StabilityLabel(str, Enum):
    STABLE = "stable"
    UNSTABLE = "unstable"
    INSUFFICIENT_DATA = "insufficient_data"


class TemporalBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    bucket_label: str
    start: datetime
    end: datetime
    distribution: DistributionSummary


class TemporalStabilityReport(BaseModel):
    """(#21) Chronological buckets, never hidden behind a single pooled
    number -- a setup that looks good pooled but flips sign quarter to
    quarter must show that flip here."""

    model_config = ConfigDict(frozen=True)

    granularity: str
    horizon_bars: int
    buckets: list[TemporalBucket]
    stability: StabilityLabel
    stability_basis: str


class SymbolBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    distribution: DistributionSummary
    mfe_atr: DistributionSummary
    mae_atr: DistributionSummary


class CrossSymbolStabilityReport(BaseModel):
    """(#22/#23) Pooled AND per-symbol, always together -- never only the
    pooled view. `dispersion` is the stdev of each symbol's own median
    across symbols, a plain descriptive spread measure, not a test."""

    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    pooled: DistributionSummary
    per_symbol: list[SymbolBucket]
    symbols_positive_median: int
    symbols_negative_median: int
    symbols_with_data: int
    dispersion_of_symbol_medians: Optional[float] = None


class ConcentrationWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str  # "symbol" | "month" | "episode" | "volatility_regime"
    dominant_value: str
    share: float
    warning: str


class SampleConcentrationReport(BaseModel):
    """(#24) Never silently pooled -- if one symbol/month/episode dominates
    a cohort, that must be visible, not buried."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    warnings: list[ConcentrationWarning] = []


class AnalogFeatures(BaseModel):
    """(#25) Every dimension the analog engine can compare on, computed
    from detection-time-only information: `SetupFingerprint`'s categorical
    buckets plus a handful of numeric features derived from `SetupContext`
    and the detection candle's own close. Never touched by anything that
    happens after `candidate_candle_timestamp`."""

    model_config = ConfigDict(frozen=True)

    setup_type: str
    direction: str
    daily_structure: Optional[str] = None
    four_hour_structure: Optional[str] = None
    one_hour_structure: Optional[str] = None
    rvol_bucket: Optional[str] = None
    gap_state: Optional[str] = None
    resistance_confluence: Optional[float] = None
    support_confluence: Optional[float] = None
    distance_to_support_percent: Optional[float] = None
    distance_to_resistance_percent: Optional[float] = None
    ma20_relative_percent: Optional[float] = None
    range_position: Optional[float] = None


class DimensionDistanceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    kind: str  # "categorical" | "numeric"
    case_value: Optional[str] = None
    candidate_value: Optional[str] = None
    matched: bool
    contribution: float


class AnalogDistance(BaseModel):
    """(#26) A transparent, itemized similarity distance -- never an
    unexplained percentage. Lower is more similar; 0.0 is an identical
    fingerprint on every compared dimension."""

    model_config = ConfigDict(frozen=True)

    distance: float
    matched_dimensions: list[str]
    differing_dimensions: list[str]
    missing_dimensions: list[str]
    breakdown: list[DimensionDistanceEntry]


class AnalogOutcomeSummary(BaseModel):
    """(#27) Attached to a ranked analog strictly AFTER ranking -- never
    consulted by the distance function itself."""

    model_config = ConfigDict(frozen=True)

    one_bar_directional_return_percent: Optional[float] = None
    five_bar_directional_return_percent: Optional[float] = None
    ten_bar_directional_return_percent: Optional[float] = None
    mfe_atr: Optional[float] = None
    mae_atr: Optional[float] = None


class AnalogResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    setup_id: str
    symbol: str
    timestamp: datetime
    setup_type: str
    direction: str
    distance: AnalogDistance
    outcome: Optional[AnalogOutcomeSummary] = None


class AnalogDiversityReport(BaseModel):
    """(Phase 9 #20/#21) Computed strictly after `rank_analogs` -- never
    changes which analogs were selected, their order, or their distances,
    only reports how much of the evidence behind an already-ranked list is
    duplicated. Phase 8's `concentration.py` explicitly deferred an
    "episode concentration" dimension because no episode concept existed
    yet; this is that dimension, now that `episodes.py` provides one."""

    model_config = ConfigDict(frozen=True)

    total_analogs: int
    distinct_episode_count: int
    analogs_without_episode_data: int
    max_same_episode_count: int
    distinct_symbol_count: int
    dominant_symbol: Optional[str] = None
    dominant_symbol_share: Optional[float] = None
    warning: Optional[str] = None


class EvidenceQualityFlag(str, Enum):
    """(#30) Deterministic, never subjective -- weak research must look
    weak. Each flag is computed from an explicit, inspectable condition,
    never a judgment call."""

    INSUFFICIENT_SAMPLE = "insufficient_sample"
    SMALL_SAMPLE = "small_sample"
    OVERLAPPING_OBSERVATIONS = "overlapping_observations"
    SYMBOL_CONCENTRATION = "symbol_concentration"
    TEMPORAL_CONCENTRATION = "temporal_concentration"
    OUT_OF_SAMPLE_REVERSAL = "out_of_sample_reversal"
    DATA_LIMITATION = "data_limitation"
    RESULT_UNSTABLE = "result_unstable"
    MULTIPLE_COMPARISON_WARNING = "multiple_comparison_warning"

    # Phase 9 #23 -- independence-adjustment-specific flags, each computed
    # from an explicit Phase 9 report, same "never a judgment call"
    # convention as the flags above.
    HIGH_OVERLAP = "high_overlap"
    LOW_INDEPENDENT_SAMPLE = "low_independent_sample"
    EPISODE_CONCENTRATION = "episode_concentration"
    WALK_FORWARD_INSTABILITY = "walk_forward_instability"
    PURGED_RESULT_REVERSAL = "purged_result_reversal"
    BLOCK_BOOTSTRAP_INCLUDES_ZERO = "block_bootstrap_includes_zero"
    SINGLE_SYMBOL_DEPENDENCE = "single_symbol_dependence"
    TEMPORAL_INSTABILITY = "temporal_instability"


class ResearchEvidenceCard(BaseModel):
    """(#29) The one standardized representation of "what does the
    evidence for this cohort look like" -- every field is a specific,
    labeled descriptive statistic or an explicit "not available." Never
    collapsed into a single arbitrary score."""

    model_config = ConfigDict(frozen=True)

    setup_type: str
    direction: Optional[str] = None
    horizon_bars: int
    sample_count: int
    sample_size_label: str
    median_directional_return: Optional[float] = None
    matched_baseline_median: Optional[float] = None
    observed_excess: Optional[float] = None
    bootstrap_interval: BootstrapInterval
    partition_medians: dict[str, Optional[float]] = {}
    symbols_positive: int = 0
    symbols_total: int = 0

    # Phase 9 #22 -- independence-adjusted evidence composition, alongside
    # (never replacing) `sample_count` above, which stays the raw count.
    independent_episode_count: Optional[int] = None
    purged_sample_count: Optional[int] = None
    overlap_rate: Optional[float] = None
    bootstrap_method: Optional[str] = None
    block_bootstrap_interval: Optional[BootstrapInterval] = None
    walk_forward_stability: Optional[str] = None
    walk_forward_positive_windows: Optional[int] = None
    walk_forward_negative_windows: Optional[int] = None
    symbol_coverage_count: int = 0
    temporal_coverage_buckets: int = 0

    flags: list[EvidenceQualityFlag] = []


class ResearchSnapshot(BaseModel):
    """(#34) An immutable record of one research conclusion: exactly which
    runs, rules, dataset, and query produced it. If detector logic changes
    later, the snapshot's own `config_hash`/`dataset_manifest` mean the old
    conclusion stays inspectable and distinguishable from a new one -- it
    is never silently superseded or recomputed in place."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    label: str
    research_run_ids: list[str]
    config_hash: str
    dataset_manifest: dict
    cohort_definition: dict
    filters: dict
    statistical_output: dict
    warning_flags: list[str]
    created_at: datetime


class SnapshotFieldDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    snapshot_a_value: Optional[str] = None
    snapshot_b_value: Optional[str] = None
    changed: bool


class SnapshotComparison(BaseModel):
    """(#35) Two snapshots compared explicitly -- config/dataset
    differences are always surfaced, never silently merged away, so a
    "same setup, different period" comparison can never be mistaken for
    "same setup, different rules" or vice versa."""

    model_config = ConfigDict(frozen=True)

    snapshot_a_id: str
    snapshot_b_id: str
    same_config_hash: bool
    same_dataset: bool
    field_diffs: list[SnapshotFieldDiff]


class ContradictionStatus(str, Enum):
    SUPPORTED = "assumption_supported"
    NOT_SUPPORTED = "assumption_not_supported_in_this_sample"
    INSUFFICIENT_DATA = "insufficient_data"


class ContradictionResult(BaseModel):
    """(#17) A predefined product assumption checked against observed data
    -- never changes detector rules automatically, only surfaces whether
    this sample supports it."""

    model_config = ConfigDict(frozen=True)

    assumption_code: str
    description: str
    group_a_label: str
    group_b_label: str
    comparison: GroupComparisonResult
    status: ContradictionStatus


class SetupEpisode(BaseModel):
    """(Phase 9 #3) A deterministic grouping of ledger entries that likely
    depend on substantially the same underlying market event -- e.g. a
    trend_pullback candidate re-detected every bar while a retracement
    holds, or several liquidity-sweep candidates minted off the same
    swing. Raw `SetupLedgerEntry` rows are never modified or deleted;
    episodes are a research-time grouping on top of them (see
    `episodes.py` for the exact deterministic rule)."""

    model_config = ConfigDict(frozen=True)

    episode_id: str
    setup_type: str
    direction: str
    symbol: str
    timeframe: str
    member_setup_ids: list[str]
    first_detected_at: datetime
    last_member_at: datetime
    reference_source: Optional[str] = None
    reference_timestamp: Optional[datetime] = None
    qualification_states_represented: list[str]
    raw_observation_count: int
    representative_setup_id: str


class EpisodeMembership(BaseModel):
    """(Phase 9 #4) One `SetupLedgerEntry` -> `SetupEpisode` link, with the
    specific reason it joined. `join_basis` is "anchor" for the first
    (earliest) member of an episode, otherwise "structural_reference" (same
    reference_source + reference_timestamp as the immediately preceding
    member) or "temporal_proximity" (detected within that setup type's own
    detection-lookback/expiration window of the immediately preceding
    member) -- never an unexplained arbitrary bar count."""

    model_config = ConfigDict(frozen=True)

    setup_id: str
    episode_id: str
    join_basis: str


class ObservationOverlapDetail(BaseModel):
    """(Phase 9 #5) Per-observation overlap detail at one horizon -- never
    hidden inside a single aggregate warning."""

    model_config = ConfigDict(frozen=True)

    setup_id: str
    horizon_bars: int
    overlapping_setup_ids: list[str]
    overlap_count: int
    same_symbol_overlap_count: int
    same_episode_overlap_count: int
    max_shared_bars: int


class SampleComposition(BaseModel):
    """(Phase 9 #6/#9) How many observations went into a sample set, at
    each level of dependence adjustment -- shown side by side rather than
    collapsed into one invented "effective N"."""

    model_config = ConfigDict(frozen=True)

    raw_count: int
    episode_count: int
    purged_counts_by_horizon: dict[int, int]


class ConclusionLabel(str, Enum):
    """(Phase 9 #12) Always computed from an explicit ratio threshold, never
    manually chosen -- see `conclusion_stability.py`."""

    SURVIVES = "survives"
    WEAKENS = "weakens"
    DISAPPEARS = "disappears"
    REVERSES = "reverses"
    INSUFFICIENT_INDEPENDENT_SAMPLE = "insufficient_independent_sample"


class ConclusionStabilityReport(BaseModel):
    """(Phase 9 #11/#12/#27) A single finding (e.g. "qualified vs rejected"
    or "aligned vs opposed") re-evaluated at three levels of dependence
    adjustment -- each level is a full `GroupComparisonResult` so sample
    size, distributions, and bootstrap intervals stay visible at every
    level, not just the headline difference -- with a deterministic label
    for whether the raw conclusion survives."""

    model_config = ConfigDict(frozen=True)

    finding_label: str
    horizon_bars: int
    raw: GroupComparisonResult
    episode: GroupComparisonResult
    purged: GroupComparisonResult
    label: ConclusionLabel
    label_basis: str


class WalkForwardWindow(BaseModel):
    """(Phase 9 #13-15) One anchored fold: `test_start`/`test_end` bound a
    chronological slice of entries never used by any earlier fold, and
    `train_start`/`train_end` bound the expanding history that precedes it
    -- recorded for transparency, since this codebase currently fits
    nothing on the training slice (#16: no parameter tuning), but the
    boundary still proves no later data leaked into an earlier fold."""

    model_config = ConfigDict(frozen=True)

    window_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    test_distribution: DistributionSummary


class WalkForwardReport(BaseModel):
    """(Phase 9 #13-15/#28) A finding re-checked fold by fold, in
    chronological order, on an ever-expanding history -- never shuffled,
    never re-fit per fold. `stability` is a deterministic function of
    whether the median directional return keeps the same sign across
    every usable fold, the same convention `stability.py` already uses for
    temporal buckets."""

    model_config = ConfigDict(frozen=True)

    finding_label: str
    horizon_bars: int
    windows: list[WalkForwardWindow]
    positive_median_window_count: int
    negative_median_window_count: int
    stability: StabilityLabel
    stability_basis: str


class EvidenceMaturity(str, Enum):
    """(Phase 9 #24) A categorical summary of `classify_evidence_maturity`'s
    explicit, documented checklist -- never a fitted or subjective call,
    and deliberately not a 0-100 score. See `evidence_maturity.py` for the
    exact per-category requirements."""

    INSUFFICIENT = "insufficient"
    PRELIMINARY = "preliminary"
    MIXED = "mixed"
    REPLICATED = "replicated"


class OverlapReport(BaseModel):
    """Time-series dependence diagnostic (#11). Overlapping forward-outcome
    windows are not independent samples -- a naive i.i.d. bootstrap on them
    understates true uncertainty. This never silently applies naive
    statistics; it always reports what it found."""

    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    sample_count: int
    overlapping_pair_count: int
    overlapping_entry_count: int
    overlap_fraction: float
    warning: Optional[str] = None


class PartitionBounds(BaseModel):
    """One partition's time bounds for one symbol/timeframe pull (#5).
    Bounds are half-open [start, end) so adjacent partitions never overlap
    and every timestamp in the source series falls in exactly one."""

    model_config = ConfigDict(frozen=True)

    partition: Partition
    start: datetime
    end: datetime
    bar_count: int


class DatasetPartitionPlan(BaseModel):
    """The full chronological split for one symbol/timeframe pull (#5) --
    architecture only, no optimization performed using this split yet."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    development_ratio: float
    validation_ratio: float
    test_ratio: float
    bounds: list[PartitionBounds]
