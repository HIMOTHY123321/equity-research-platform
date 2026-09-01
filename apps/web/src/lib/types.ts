export type Timeframe = "5m" | "15m" | "1h" | "4h" | "1d";

export const TIMEFRAMES: Timeframe[] = ["5m", "15m", "1h", "4h", "1d"];

export type MarketSession = "pre_market" | "regular" | "after_hours";

export interface Candle {
  symbol: string;
  timeframe: string;
  timestamp: string;
  session: MarketSession;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  candles: Candle[];
}

export interface Quote {
  symbol: string;
  timestamp: string;
  session: MarketSession;
  bid_price: number;
  bid_size: number;
  ask_price: number;
  ask_size: number;
}

export interface PreviousClose {
  symbol: string;
  trading_date: string;
  close: number;
  volume: number;
}

export interface SymbolQuoteResponse {
  symbol: string;
  quote: Quote;
  previous_close: PreviousClose;
  today: Candle | null;
}

export interface WatchlistSymbol {
  ticker: string;
  added_at: string;
}

// ---- Feature engine (Phase 3) ------------------------------------------

export type FeatureStatus = "ok" | "insufficient_history" | "unavailable" | "not_applicable";

export interface PreviousDayLevels {
  status: FeatureStatus;
  trading_date: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  range: number | null;
  percent_change: number | null;
}

export interface PreviousWeekLevels {
  status: FeatureStatus;
  week_start_date: string | null;
  week_end_date: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  range: number | null;
  percent_change: number | null;
  trading_days_counted: number;
}

export interface GapFeature {
  status: FeatureStatus;
  previous_close: number | null;
  session_open: number | null;
  gap_absolute: number | null;
  gap_percent: number | null;
  direction: "up" | "down" | "flat" | null;
}

export interface ATRFeature {
  status: FeatureStatus;
  period: number;
  method: string;
  value: number | null;
}

export interface MovingAverageFeature {
  status: FeatureStatus;
  type: "ema" | "sma";
  period: number;
  value: number | null;
  distance_absolute: number | null;
  distance_percent: number | null;
  position: "above" | "below" | "equal" | null;
}

export interface MovingAveragesBundle {
  ema20: MovingAverageFeature;
  sma50: MovingAverageFeature;
  sma200: MovingAverageFeature;
}

export interface RollingLevel {
  status: FeatureStatus;
  period: number;
  include_current: boolean;
  high: number | null;
  low: number | null;
}

export interface RollingLevels {
  including_current: RollingLevel[];
  excluding_current: RollingLevel[];
}

export interface VolumeFeatures {
  status: FeatureStatus;
  average_volume_period: number;
  current_volume: number | null;
  current_bar_is_partial: boolean;
  average_volume: number | null;
  relative_volume: number | null;
}

export interface IntradayRelativeVolumeFeature {
  status: FeatureStatus;
  lookback_days_requested: number;
  lookback_days_used: number;
  as_of_time_of_day: string | null;
  cumulative_volume_today: number | null;
  cumulative_volume_reference_average: number | null;
  intraday_relative_volume: number | null;
}

export interface CandleFeatures {
  status: FeatureStatus;
  timestamp: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  body_size: number | null;
  full_range: number | null;
  upper_wick: number | null;
  lower_wick: number | null;
  body_percent_of_range: number | null;
  classification: "bullish" | "bearish" | "doji" | null;
}

export interface SessionFeatures {
  status: FeatureStatus;
  session_open: number | null;
  session_high_so_far: number | null;
  session_low_so_far: number | null;
  session_range: number | null;
  latest_price: number | null;
  distance_from_high_absolute: number | null;
  distance_from_high_percent: number | null;
  distance_from_low_absolute: number | null;
  distance_from_low_percent: number | null;
}

export interface DataQuality {
  source_timeframe: string;
  candle_count: number;
  earliest_candle_timestamp: string | null;
  latest_candle_timestamp: string | null;
  latest_candle_is_complete: boolean;
  latest_candle_session: MarketSession | null;
  future_candles_dropped: number;
  warnings: string[];
}

export interface FeatureSnapshot {
  symbol: string;
  as_of: string;
  timeframe: string;
  previous_day: PreviousDayLevels;
  previous_week: PreviousWeekLevels;
  gap: GapFeature;
  atr: ATRFeature;
  moving_averages: MovingAveragesBundle;
  rolling_levels: RollingLevels;
  volume: VolumeFeatures;
  intraday_relative_volume: IntradayRelativeVolumeFeature;
  latest_candle: CandleFeatures;
  session: SessionFeatures;
  data_quality: DataQuality;
}

// ---- Market structure engine (Phase 4) -----------------------------------

export type SwingPointType = "high" | "low";

export type SwingClassificationType =
  | "higher_high"
  | "lower_high"
  | "equal_high"
  | "higher_low"
  | "lower_low"
  | "equal_low";

export type StructureDirection = "bullish" | "bearish";

export type TrendClassType = "bullish" | "bearish" | "ranging" | "insufficient_data";

export type TrendStrengthType = "weak" | "developing" | "established";

export type StructureStatus = "ok" | "insufficient_data";

export interface SwingPoint {
  type: SwingPointType;
  price: number;
  pivot_timestamp: string;
  confirmed_at: string;
  left_bars: number;
  right_bars: number;
  classification: SwingClassificationType | null;
  previous_comparable_price: number | null;
  is_broken: boolean;
  first_broken_at: string | null;
  break_direction: StructureDirection | null;
}

export interface CandidatePivot {
  type: SwingPointType;
  price: number;
  pivot_timestamp: string;
  left_bars: number;
  right_bars_required: number;
  right_bars_available: number;
}

export interface TrendClassification {
  trend: TrendClassType;
  strength: TrendStrengthType | null;
  evidence: string[];
}

export interface BreakOfStructureEvent {
  direction: StructureDirection;
  broken_level: number;
  broken_swing_timestamp: string;
  break_timestamp: string;
  confirmation: string;
  distance_beyond_level: number;
}

export interface ChangeOfCharacterEvent {
  direction: StructureDirection;
  prior_structure: StructureDirection;
  broken_level: number;
  break_timestamp: string;
  reference_swing_timestamp: string;
}

export interface ActiveRange {
  status: StructureStatus;
  high: number | null;
  low: number | null;
  midpoint: number | null;
  width: number | null;
  width_percent: number | null;
  position_percent: number | null;
}

export interface StructureFreshness {
  bars_since_last_swing_high: number | null;
  bars_since_last_swing_low: number | null;
  bars_since_last_bullish_bos: number | null;
  bars_since_last_bearish_bos: number | null;
  bars_since_last_choch: number | null;
}

export interface StructureDataQuality {
  source_timeframe: string;
  candle_count: number;
  completed_candle_count: number;
  earliest_candle_timestamp: string | null;
  latest_candle_timestamp: string | null;
  confirmed_swing_count: number;
  candidate_swing_count: number;
  future_candles_dropped: number;
  warnings: string[];
}

export interface MarketStructureSnapshot {
  symbol: string;
  timeframe: string;
  as_of: string;
  trend: TrendClassification;
  swings: SwingPoint[];
  candidate_swings: CandidatePivot[];
  latest_swing_high: SwingPoint | null;
  latest_swing_low: SwingPoint | null;
  latest_higher_high: SwingPoint | null;
  latest_higher_low: SwingPoint | null;
  latest_lower_high: SwingPoint | null;
  latest_lower_low: SwingPoint | null;
  breaks_of_structure: BreakOfStructureEvent[];
  changes_of_character: ChangeOfCharacterEvent[];
  active_range: ActiveRange;
  freshness: StructureFreshness;
  data_quality: StructureDataQuality;
}

// ---- Support/resistance engine (Phase 5) -----------------------------------

export type LevelKind = "support" | "resistance" | "reference";

export type InteractionKind = "touch" | "rejection" | "wick_breach" | "close_break";

export type ZoneLifecycleState = "active" | "tested" | "weakened" | "broken" | "stale";

export type ZonePosition = "above_price" | "below_price" | "contains_price";

export interface RawLevel {
  id: string;
  price: number;
  kind: LevelKind;
  source: string;
  source_timeframe: string;
  origin_timestamp: string;
  known_at: string;
  metadata: Record<string, unknown>;
}

export interface ZoneEvidenceEntry {
  source: string;
  source_timeframe: string;
  price: number;
  origin_timestamp: string;
  known_at: string;
  weight: number;
}

export interface ZoneInteractionEvent {
  timestamp: string;
  interaction_type: InteractionKind;
  high: number;
  low: number;
  close: number;
  distance: number;
  is_independent: boolean;
}

export interface ZoneBreakEvent {
  direction: LevelKind;
  break_price: number;
  first_broken_at: string;
  zone_lower_bound: number;
  zone_upper_bound: number;
}

export interface ZoneStrengthBreakdown {
  source_score: number;
  confluence_score: number;
  interaction_score: number;
  recency_score: number;
  total: number;
}

export interface ZoneConfluence {
  source_count: number;
  timeframe_count: number;
  source_types: string[];
  timeframes: string[];
}

export interface ZoneInteractionSummary {
  independent_touches: number;
  rejections: number;
  wick_breaches: number;
}

export interface ZonePriceRelationship {
  distance_absolute: number;
  distance_percent: number;
  position: ZonePosition;
}

export interface ZoneFreshnessInfo {
  bars_since_created: number | null;
  bars_since_last_touch: number | null;
  bars_since_last_rejection: number | null;
  bars_since_break: number | null;
}

export interface Zone {
  id: string;
  kind: LevelKind;
  lower_bound: number;
  upper_bound: number;
  representative_price: number;
  member_levels: RawLevel[];
  evidence: ZoneEvidenceEntry[];
  confluence: ZoneConfluence;
  known_at: string;
  interactions: ZoneInteractionEvent[];
  interaction_summary: ZoneInteractionSummary;
  break_event: ZoneBreakEvent | null;
  lifecycle: ZoneLifecycleState;
  strength: ZoneStrengthBreakdown;
  freshness: ZoneFreshnessInfo;
  price_relationship: ZonePriceRelationship | null;
}

export interface SupportResistanceDataQuality {
  source_timeframe: string;
  candles_consumed: number;
  raw_levels_generated: number;
  zones_created: number;
  confirmed_swings_used: number;
  warnings: string[];
}

export interface SupportResistanceSnapshot {
  symbol: string;
  timeframe: string;
  as_of: string;
  nearest_support: Zone | null;
  nearest_resistance: Zone | null;
  active_support_zones: Zone[];
  active_resistance_zones: Zone[];
  reference_levels: RawLevel[];
  recent_broken_zones: Zone[];
  data_quality: SupportResistanceDataQuality;
}

// ---- Setup detection engine (Phase 6) --------------------------------------

export type SetupType =
  | "previous_day_high_breakout"
  | "previous_day_low_breakdown"
  | "previous_week_high_breakout"
  | "previous_week_low_breakdown"
  | "breakout_retest"
  | "wick_failed_breakout"
  | "confirmed_breakout_failure"
  | "support_reclaim"
  | "resistance_rejection"
  | "gap_continuation"
  | "gap_fill"
  | "bullish_liquidity_sweep"
  | "bearish_liquidity_sweep"
  | "moving_average_reclaim"
  | "trend_pullback"
  | "range_breakout";

export type SetupLifecycleStateType =
  | "candidate"
  | "qualified"
  | "triggered"
  | "invalidated"
  | "expired"
  | "rejected";

export type RuleTypeKind = "hard" | "soft";

export type ConflictSeverityKind = "major" | "minor";

export type BreakoutConfirmationKind = "wick_breach" | "close_break";

export type SetupDetectionStatusKind = "ok" | "unavailable";

export interface EvidenceCheck {
  code: string;
  label: string;
  rule_type: RuleTypeKind;
  passed: boolean;
  actual: number | null;
  required: number | null;
  source: string;
}

export interface ConflictCheck {
  code: string;
  label: string;
  severity: ConflictSeverityKind;
  actual: number | null;
  reference: number | null;
  source: string;
}

export interface LifecycleTransition {
  state: SetupLifecycleStateType;
  timestamp: string;
  reason_code: string;
  reason_label: string;
}

export interface MarketContext {
  benchmark_symbol: string;
  trend: TrendClassType | null;
  as_of: string;
}

export interface SetupContext {
  as_of: string;
  daily_structure: TrendClassType | null;
  four_hour_structure: TrendClassType | null;
  one_hour_structure: TrendClassType | null;
  atr: number | null;
  rvol: number | null;
  ema20: number | null;
  sma50: number | null;
  sma200: number | null;
  active_range_high: number | null;
  active_range_low: number | null;
  gap_percent: number | null;
  gap_direction: string | null;
  nearest_support_price: number | null;
  nearest_resistance_price: number | null;
  market_context: MarketContext | null;
}

export interface SetupFingerprint {
  setup_type: SetupType;
  direction: StructureDirection;
  daily_structure: TrendClassType | null;
  four_hour_structure: TrendClassType | null;
  one_hour_structure: TrendClassType | null;
  rvol_bucket: string | null;
  gap_state: string;
  distance_to_weekly_resistance_bucket: string | null;
  distance_to_weekly_support_bucket: string | null;
  support_confluence: number;
  resistance_confluence: number;
}

export interface SetupCandidate {
  id: string;
  symbol: string;
  timeframe: string;
  setup_type: SetupType;
  direction: StructureDirection;
  reference_price: number | null;
  reference_source: string | null;
  reference_timestamp: string | null;
  confirmation: BreakoutConfirmationKind | null;
  candidate_candle_timestamp: string;
  created_at: string;
  current_state: SetupLifecycleStateType;
  transitions: LifecycleTransition[];
  hard_checks: EvidenceCheck[];
  soft_checks: EvidenceCheck[];
  conflicts: ConflictCheck[];
  invalidation_criteria: string[];
  context: SetupContext | null;
  fingerprint: SetupFingerprint | null;
  expires_at: string | null;
  expired_at: string | null;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  triggered_at: string | null;
  metadata: Record<string, unknown>;
}

export interface SetupDetectionDataQuality {
  status: SetupDetectionStatusKind;
  source_timeframe: string;
  candles_consumed: number;
  detectors_run: number;
  detectors_skipped: string[];
  warnings: string[];
}

export interface SetupDetectionSnapshot {
  symbol: string;
  timeframe: string;
  as_of: string;
  qualified_setups: SetupCandidate[];
  candidates: SetupCandidate[];
  rejected_candidates: SetupCandidate[];
  recently_invalidated: SetupCandidate[];
  recently_expired: SetupCandidate[];
  data_quality: SetupDetectionDataQuality;
}

// ---- Research engine (Phase 7) ---------------------------------------------

export type ResearchRunStatusKind = "running" | "completed" | "failed";

export type SampleSizeLabelKind = "insufficient_sample" | "small_sample" | "moderate_sample" | "larger_sample";

export interface ResearchRun {
  id: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  status: ResearchRunStatusKind;
  config_hash: string;
  bars_processed: number | null;
  qualified_count: number | null;
  rejected_count: number | null;
  runtime_seconds: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface HorizonOutcome {
  horizon_bars: number;
  available: boolean;
  future_close: number | null;
  absolute_change: number | null;
  raw_return_percent: number | null;
  directional_return_percent: number | null;
}

export interface ExcursionMetrics {
  absolute: number | null;
  percent: number | null;
  atr: number | null;
  bars_until: number | null;
  timestamp: string | null;
}

export interface StructuralEventOutcome {
  code: string;
  occurred: boolean;
  timestamp: string | null;
  bars_until: number | null;
}

export interface EvaluationQuality {
  bars_available_after_detection: number;
  fully_evaluated: boolean;
  warnings: string[];
}

export interface SetupOutcome {
  setup_id: string;
  base_price: number;
  detection_atr: number | null;
  evaluation_start: string;
  evaluation_end: string | null;
  horizons: HorizonOutcome[];
  mfe: ExcursionMetrics;
  mae: ExcursionMetrics;
  structural_events: StructuralEventOutcome[];
  evaluation_quality: EvaluationQuality;
}

export interface ResearchSetupLedgerEntry {
  research_run_id: string;
  setup_id: string;
  symbol: string;
  timeframe: string;
  setup_type: string;
  direction: StructureDirection;
  first_seen_at: string;
  candidate_candle_timestamp: string;
  detection: SetupCandidate;
  current_state: SetupLifecycleStateType;
  last_observed_at: string;
  latest: SetupCandidate;
  outcome: SetupOutcome | null;
}

export interface HorizonStat {
  horizon_bars: number;
  n: number;
  mean: number | null;
  median: number | null;
  p25: number | null;
  p75: number | null;
}

export interface GroupOutcomeStats {
  sample_count: number;
  sample_size_label: SampleSizeLabelKind;
  directional_return_by_horizon: HorizonStat[];
  mfe_atr: HorizonStat | null;
  mae_atr: HorizonStat | null;
}

export interface QualificationLift {
  horizon_bars: number;
  qualified_median: number | null;
  rejected_median: number | null;
  observed_difference: number | null;
}

export interface RejectionValueEntry {
  rejection_code: string;
  sample_count: number;
  sample_size_label: SampleSizeLabelKind;
  median_5bar_directional_return: number | null;
  comparable_qualified_median_5bar_directional_return: number | null;
}

export interface BaselineComparison {
  unconditional: GroupOutcomeStats;
  regime_matched: GroupOutcomeStats | null;
  regime_label: string | null;
}

export interface SetupTypeSummary {
  setup_type: string;
  qualified: GroupOutcomeStats;
  rejected: GroupOutcomeStats;
  qualification_lift: QualificationLift[];
  rejection_value: RejectionValueEntry[];
  baseline: BaselineComparison | null;
}

export interface ResearchRunSummary {
  run_id: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  bars_processed: number;
  qualified_count: number;
  rejected_count: number;
  runtime_seconds: number;
  setup_types: SetupTypeSummary[];
}

export interface LedgerEntriesResponse {
  run_id: string;
  count: number;
  entries: ResearchSetupLedgerEntry[];
}

// ---- Research Intelligence (Phase 8) ---------------------------------------

export interface DistributionSummary {
  n: number;
  mean: number | null;
  median: number | null;
  stdev: number | null;
  p10: number | null;
  p25: number | null;
  p75: number | null;
  p90: number | null;
}

export interface BootstrapInterval {
  available: boolean;
  statistic: string;
  point_estimate: number | null;
  lower: number | null;
  upper: number | null;
  confidence_level: number | null;
  iterations: number | null;
  seed: number | null;
  method: string;
  unavailable_reason: string | null;
}

export type EvidenceQualityFlagKind =
  | "insufficient_sample"
  | "small_sample"
  | "overlapping_observations"
  | "symbol_concentration"
  | "temporal_concentration"
  | "out_of_sample_reversal"
  | "data_limitation"
  | "result_unstable"
  | "multiple_comparison_warning"
  // Phase 9 (#23) -- independence-adjustment-specific flags.
  | "high_overlap"
  | "low_independent_sample"
  | "episode_concentration"
  | "walk_forward_instability"
  | "purged_result_reversal"
  | "block_bootstrap_includes_zero"
  | "single_symbol_dependence"
  | "temporal_instability";

export interface ResearchEvidenceCard {
  setup_type: string;
  direction: string | null;
  horizon_bars: number;
  sample_count: number;
  sample_size_label: string;
  median_directional_return: number | null;
  matched_baseline_median: number | null;
  observed_excess: number | null;
  bootstrap_interval: BootstrapInterval;
  partition_medians: Record<string, number | null>;
  symbols_positive: number;
  symbols_total: number;
  // Phase 9 (#22) -- independence-adjusted composition, alongside (never
  // replacing) the raw fields above.
  independent_episode_count: number | null;
  purged_sample_count: number | null;
  overlap_rate: number | null;
  bootstrap_method: string | null;
  block_bootstrap_interval: BootstrapInterval | null;
  walk_forward_stability: StabilityLabelKind | null;
  walk_forward_positive_windows: number | null;
  walk_forward_negative_windows: number | null;
  symbol_coverage_count: number;
  temporal_coverage_buckets: number;
  flags: EvidenceQualityFlagKind[];
}

export type DecayPatternKind = "immediate" | "delayed" | "persistent" | "decaying" | "inconclusive";

export interface DecayHorizonStat {
  horizon_bars: number;
  distribution: DistributionSummary;
  bootstrap_interval: BootstrapInterval;
  warnings: string[];
}

export interface SignalDecayProfile {
  horizons: DecayHorizonStat[];
  pattern: DecayPatternKind;
  pattern_basis: string;
}

export interface ExcursionProfile {
  mfe_percent: DistributionSummary;
  mfe_atr: DistributionSummary;
  mae_percent: DistributionSummary;
  mae_atr: DistributionSummary;
  bars_to_mfe: DistributionSummary;
  bars_to_mae: DistributionSummary;
  sample_count: number;
}

export type FirstHitOutcomeKind = "favorable_first" | "adverse_first" | "neither";

export interface FirstHitResult {
  favorable_atr_threshold: number;
  adverse_atr_threshold: number;
  sample_count: number;
  favorable_first_count: number;
  adverse_first_count: number;
  neither_count: number;
  excluded_no_atr_count: number;
}

export type StabilityLabelKind = "stable" | "unstable" | "insufficient_data";

export interface TemporalBucket {
  bucket_label: string;
  start: string;
  end: string;
  distribution: DistributionSummary;
}

export interface TemporalStabilityReport {
  granularity: string;
  horizon_bars: number;
  buckets: TemporalBucket[];
  stability: StabilityLabelKind;
  stability_basis: string;
}

export interface SymbolBucket {
  symbol: string;
  distribution: DistributionSummary;
  mfe_atr: DistributionSummary;
  mae_atr: DistributionSummary;
}

export interface CrossSymbolStabilityReport {
  horizon_bars: number;
  pooled: DistributionSummary;
  per_symbol: SymbolBucket[];
  symbols_positive_median: number;
  symbols_negative_median: number;
  symbols_with_data: number;
  dispersion_of_symbol_medians: number | null;
}

export interface ConcentrationWarning {
  dimension: string;
  dominant_value: string;
  share: number;
  warning: string;
}

export interface SampleConcentrationReport {
  sample_count: number;
  warnings: ConcentrationWarning[];
}

export interface OverlapReport {
  horizon_bars: number;
  sample_count: number;
  overlapping_pair_count: number;
  overlapping_entry_count: number;
  overlap_fraction: number;
  warning: string | null;
}

export type ContradictionStatusKind =
  | "assumption_supported"
  | "assumption_not_supported_in_this_sample"
  | "insufficient_data";

export interface PartitionComparisonSummary {
  group_a_n: number;
  group_b_n: number;
  group_a_median: number | null;
  group_b_median: number | null;
  median_difference: number | null;
}

export interface GroupComparisonResult {
  group_a_label: string;
  group_b_label: string;
  horizon_bars: number;
  group_a_distribution: DistributionSummary;
  group_b_distribution: DistributionSummary;
  median_difference: number | null;
  mean_difference: number | null;
  standardized_effect_size: number | null;
  cliffs_delta: number | null;
  mfe_atr_median_difference: number | null;
  mae_atr_median_difference: number | null;
  median_difference_bootstrap: BootstrapInterval;
  group_a_baseline_adjusted_excess: number | null;
  group_b_baseline_adjusted_excess: number | null;
  partition_breakdown: Record<string, PartitionComparisonSummary>;
}

export interface ContradictionResult {
  assumption_code: string;
  description: string;
  group_a_label: string;
  group_b_label: string;
  comparison: GroupComparisonResult;
  status: ContradictionStatusKind;
}

export type ConclusionLabelKind = "survives" | "weakens" | "disappears" | "reverses" | "insufficient_independent_sample";

export interface ConclusionStabilityReport {
  finding_label: string;
  horizon_bars: number;
  raw: GroupComparisonResult;
  episode: GroupComparisonResult;
  purged: GroupComparisonResult;
  label: ConclusionLabelKind;
  label_basis: string;
}

export interface SampleComposition {
  raw_count: number;
  episode_count: number;
  purged_counts_by_horizon: Record<string, number>;
}

export interface WalkForwardWindow {
  window_index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  test_distribution: DistributionSummary;
}

export interface WalkForwardReport {
  finding_label: string;
  horizon_bars: number;
  windows: WalkForwardWindow[];
  positive_median_window_count: number;
  negative_median_window_count: number;
  stability: StabilityLabelKind;
  stability_basis: string;
}

export type EvidenceMaturityKind = "insufficient" | "preliminary" | "mixed" | "replicated";

export interface IndependenceSection {
  sample_composition: SampleComposition;
  walk_forward: WalkForwardReport;
  evidence_maturity: EvidenceMaturityKind;
  evidence_maturity_basis: string;
  conclusion_stability: ConclusionStabilityReport | null;
}

export interface ResearchQueryResponse {
  sample_count: number;
  evidence_card: ResearchEvidenceCard;
  signal_decay: SignalDecayProfile;
  excursions: ExcursionProfile;
  first_hit: FirstHitResult | null;
  temporal_stability: TemporalStabilityReport;
  cross_symbol_stability: CrossSymbolStabilityReport;
  concentration: SampleConcentrationReport;
  overlap: OverlapReport;
  contradictions: ContradictionResult[];
  independence: IndependenceSection;
}

export interface UniverseReplayResponse {
  run_ids: Record<string, string>;
  failures: Record<string, string>;
}

export interface DimensionDistanceEntry {
  dimension: string;
  kind: "categorical" | "numeric";
  case_value: string | null;
  candidate_value: string | null;
  matched: boolean;
  contribution: number;
}

export interface AnalogDistance {
  distance: number;
  matched_dimensions: string[];
  differing_dimensions: string[];
  missing_dimensions: string[];
  breakdown: DimensionDistanceEntry[];
}

export interface AnalogOutcomeSummary {
  one_bar_directional_return_percent: number | null;
  five_bar_directional_return_percent: number | null;
  ten_bar_directional_return_percent: number | null;
  mfe_atr: number | null;
  mae_atr: number | null;
}

export interface AnalogResult {
  setup_id: string;
  symbol: string;
  timestamp: string;
  setup_type: string;
  direction: string;
  distance: AnalogDistance;
  outcome: AnalogOutcomeSummary | null;
}

export interface AnalogDiversityReport {
  total_analogs: number;
  distinct_episode_count: number;
  analogs_without_episode_data: number;
  max_same_episode_count: number;
  distinct_symbol_count: number;
  dominant_symbol: string | null;
  dominant_symbol_share: number | null;
  warning: string | null;
}

export interface AnalogQueryResponse {
  analogs: AnalogResult[];
  diversity: AnalogDiversityReport;
  diverse_analogs: AnalogResult[];
  catalyst_context_applied: boolean;
}

export interface ResearchSnapshot {
  snapshot_id: string;
  label: string;
  research_run_ids: string[];
  config_hash: string;
  dataset_manifest: Record<string, unknown>;
  cohort_definition: Record<string, unknown>;
  filters: Record<string, unknown>;
  statistical_output: Record<string, unknown>;
  warning_flags: string[];
  created_at: string;
}

export interface SnapshotFieldDiff {
  field: string;
  snapshot_a_value: string | null;
  snapshot_b_value: string | null;
  changed: boolean;
}

export interface SnapshotComparison {
  snapshot_a_id: string;
  snapshot_b_id: string;
  same_config_hash: boolean;
  same_dataset: boolean;
  field_diffs: SnapshotFieldDiff[];
}

// ---- News / Catalyst Context engine (Phase 10) -----------------------------

export type CatalystCategory =
  | "earnings"
  | "earnings_preannouncement"
  | "guidance"
  | "analyst_rating"
  | "price_target"
  | "product_launch"
  | "product_issue"
  | "regulatory"
  | "legal_lawsuit"
  | "merger_acquisition"
  | "financing_capital_raise"
  | "buyback"
  | "dividend"
  | "management_change"
  | "filing"
  | "macroeconomic"
  | "federal_reserve"
  | "interest_rates"
  | "inflation"
  | "employment"
  | "geopolitical"
  | "supply_chain"
  | "sector_industry"
  | "company_specific_other"
  | "unknown";

export type ClassificationMethodKind = "deterministic_rule" | "ai_assisted";

export type ClassificationBasisKind =
  | "provider_category_direct_map"
  | "strong_keyword_match"
  | "weak_keyword_fallback"
  | "unknown_no_match";

export interface CatalystClassification {
  category: CatalystCategory;
  basis: ClassificationBasisKind;
  matched_rules: string[];
  provider_raw_category: string | null;
  method: ClassificationMethodKind;
}

export interface NormalizedNewsArticle {
  article_id: string;
  provider: string;
  source: string | null;
  headline: string;
  published_at: string;
  received_at: string | null;
  url: string | null;
  symbols: string[];
  raw_category: string | null;
  classification: CatalystClassification;
  provenance: Record<string, unknown>;
  ingested_at: string;
}

export interface CatalystEvent {
  event_id: string;
  primary_timestamp: string;
  category: CatalystCategory;
  affected_symbols: string[];
  contributing_article_ids: string[];
  source_count: number;
  earliest_published_at: string;
  latest_update_at: string;
  title: string;
  provenance: Record<string, unknown>;
}

export type ReactionSessionKind = "pre_market" | "regular" | "after_hours" | "weekend_non_trading";

export interface MarketReaction {
  event_id: string;
  symbol: string;
  timeframe: string;
  session_at_event: ReactionSessionKind;
  base_price: number | null;
  price_horizons: HorizonOutcome[];
  mfe: ExcursionMetrics | null;
  mae: ExcursionMetrics | null;
  rvol_at_event: number | null;
  volume_spike_ratio: number | null;
  atr_normalized_move: number | null;
  nearest_support_price: number | null;
  nearest_resistance_price: number | null;
  structure_state_at_event: string | null;
  bos_after_event: boolean;
  choch_after_event: boolean;
  gap_created: boolean | null;
  evaluation_quality: EvaluationQuality | null;
  computed_at: string;
}

export type SetupCatalystContextLabelKind =
  | "catalyst_supported_context"
  | "catalyst_conflicted_context"
  | "catalyst_reaction_faded"
  | "catalyst_reaction_persisted"
  | "catalyst_timing_ambiguous"
  | "no_recent_catalyst_found";

export interface CatalystReference {
  event_id: string;
  category: CatalystCategory;
  primary_timestamp: string;
  source_count: number;
  hours_before_setup: number | null;
  hours_after_setup: number | null;
}

export interface SetupCatalystContext {
  setup_id: string;
  symbol: string;
  catalysts_before: CatalystReference[];
  catalysts_after: CatalystReference[];
  nearest_catalyst: CatalystReference | null;
  nearest_reaction: MarketReaction | null;
  label: SetupCatalystContextLabelKind;
  label_basis: string;
}

export interface WhatsMovingResponse {
  events: CatalystEvent[];
  symbols_covered: string[];
  symbols_failed: Record<string, string>;
}

export interface CatalystEventDetail {
  event: CatalystEvent;
  articles: NormalizedNewsArticle[];
}

export interface CatalystResearchQueryResponse extends ResearchQueryResponse {
  catalyst_filtered_sample_count: number;
  unfiltered_sample_count: number;
  catalyst_filters_applied: Record<string, unknown>;
}
