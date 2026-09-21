export function formatPrice(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

export function formatPercent(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatVolume(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatRatio(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(2)}x`;
}

export function percentColorClass(value: number | null): string {
  if (value === null || value === 0) return "text-muted";
  return value > 0 ? "text-positive" : "text-negative";
}

export function directionColorClass(direction: string | null): string {
  if (direction === "up") return "text-positive";
  if (direction === "down") return "text-negative";
  return "text-muted";
}

export function classificationColorClass(classification: string | null): string {
  if (classification === "bullish") return "text-positive";
  if (classification === "bearish") return "text-negative";
  return "text-muted";
}

const SWING_CLASSIFICATION_LABELS: Record<string, string> = {
  higher_high: "Higher High",
  lower_high: "Lower High",
  equal_high: "Equal High",
  higher_low: "Higher Low",
  lower_low: "Lower Low",
  equal_low: "Equal Low",
};

const SWING_CLASSIFICATION_ABBREV: Record<string, string> = {
  higher_high: "HH",
  lower_high: "LH",
  equal_high: "EH",
  higher_low: "HL",
  lower_low: "LL",
  equal_low: "EL",
};

export function formatSwingClassification(classification: string | null): string {
  if (!classification) return "—";
  return SWING_CLASSIFICATION_LABELS[classification] ?? classification;
}

export function swingClassificationAbbrev(classification: string | null): string {
  if (!classification) return "—";
  return SWING_CLASSIFICATION_ABBREV[classification] ?? classification;
}

export function capitalize(value: string | null): string {
  if (!value) return "—";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** Display-only bucketing of the backend's 0-100 strength score -- never
 * itself a computed value, purely a label for an already-computed number. */
export function strengthLabel(score: number): string {
  if (score >= 70) return "STRONG";
  if (score >= 40) return "MODERATE";
  return "WEAK";
}

export function formatSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    previous_week_high: "Previous Week High",
    previous_week_low: "Previous Week Low",
    previous_week_close: "Previous Week Close",
    previous_day_high: "Previous Day High",
    previous_day_low: "Previous Day Low",
    previous_day_close: "Previous Day Close",
    session_open: "Session Open",
    confirmed_swing_high: "Confirmed Swing High",
    confirmed_swing_low: "Confirmed Swing Low",
  };
  return labels[source] ?? source;
}

export function formatBarsAgo(bars: number | null): string {
  if (bars === null) return "—";
  if (bars === 0) return "this bar";
  return `${bars} bar${bars === 1 ? "" : "s"} ago`;
}

const SETUP_TYPE_LABELS: Record<string, string> = {
  previous_day_high_breakout: "Previous Day High Breakout",
  previous_day_low_breakdown: "Previous Day Low Breakdown",
  previous_week_high_breakout: "Previous Week High Breakout",
  previous_week_low_breakdown: "Previous Week Low Breakdown",
  breakout_retest: "Breakout + Retest",
  wick_failed_breakout: "Wick-Only Failed Breakout",
  confirmed_breakout_failure: "Confirmed Breakout Failure",
  support_reclaim: "Support Reclaim",
  resistance_rejection: "Resistance Rejection",
  gap_continuation: "Gap Continuation",
  gap_fill: "Gap Fill",
  bullish_liquidity_sweep: "Bullish Liquidity Sweep",
  bearish_liquidity_sweep: "Bearish Liquidity Sweep",
  moving_average_reclaim: "Moving Average Reclaim",
  trend_pullback: "Trend Pullback",
  range_breakout: "Range Breakout",
};

export function formatSetupType(type: string): string {
  return SETUP_TYPE_LABELS[type] ?? type;
}

const LIFECYCLE_STATE_LABELS: Record<string, string> = {
  candidate: "Candidate",
  qualified: "Qualified",
  triggered: "Triggered",
  invalidated: "Invalidated",
  expired: "Expired",
  rejected: "Rejected",
};

export function formatLifecycleState(state: string): string {
  return LIFECYCLE_STATE_LABELS[state] ?? state;
}

// ---- Phase 12 (#A/#L): exchange-timezone timestamps, full precision -----
//
// US-equities default: `YYYY-MM-DD HH:mm:ss EST/EDT` in America/New_York,
// always to the second, never a bare relative/current-time label for a
// historical candle or forecast. Used anywhere a forecast's created_at/
// market_as_of/resolution timestamp, or a chart candle's timestamp, is
// shown -- one formatter, so every surface renders identically.
const _EXCHANGE_TZ_PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZoneName: "short",
});

export function formatExchangeTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const parts = _EXCHANGE_TZ_PARTS.formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")} ${get("timeZoneName")}`;
}

export function formatClockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Daily-timeframe candle timestamps sit at midnight -- a clock time is
 * meaningless there, so show the calendar date instead. */
export function formatDetectionTime(iso: string, timeframe: string): string {
  if (timeframe === "1d") {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return formatClockTime(iso);
}

const SAMPLE_SIZE_LABELS: Record<string, string> = {
  insufficient_sample: "INSUFFICIENT SAMPLE",
  small_sample: "SMALL SAMPLE",
  moderate_sample: "MODERATE SAMPLE",
  larger_sample: "LARGER SAMPLE",
};

export function formatSampleSizeLabel(label: string): string {
  return SAMPLE_SIZE_LABELS[label] ?? label;
}

const EVIDENCE_MATURITY_LABELS: Record<string, string> = {
  insufficient: "INSUFFICIENT",
  preliminary: "PRELIMINARY",
  mixed: "MIXED",
  replicated: "REPLICATED",
};

export function formatEvidenceMaturity(label: string): string {
  return EVIDENCE_MATURITY_LABELS[label] ?? label;
}

export function formatSignedPercent(value: number | null, digits = 2): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatAtr(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} ATR`;
}

// ---- News / Catalyst Context engine (Phase 10) -----------------------------

const CATALYST_CATEGORY_LABELS: Record<string, string> = {
  earnings: "Earnings",
  earnings_preannouncement: "Earnings Preannouncement",
  guidance: "Guidance",
  analyst_rating: "Analyst Rating",
  price_target: "Price Target",
  product_launch: "Product Launch",
  product_issue: "Product Issue",
  regulatory: "Regulatory",
  legal_lawsuit: "Legal / Lawsuit",
  merger_acquisition: "M&A",
  financing_capital_raise: "Capital Raise",
  buyback: "Buyback",
  dividend: "Dividend",
  management_change: "Management Change",
  filing: "Filing",
  macroeconomic: "Macro",
  federal_reserve: "Federal Reserve",
  interest_rates: "Interest Rates",
  inflation: "Inflation",
  employment: "Employment",
  geopolitical: "Geopolitical",
  supply_chain: "Supply Chain",
  sector_industry: "Sector / Industry",
  company_specific_other: "Company News",
  unknown: "Uncategorized",
};

export function formatCatalystCategory(category: string): string {
  return CATALYST_CATEGORY_LABELS[category] ?? category;
}

const CATALYST_CONTEXT_LABELS: Record<string, string> = {
  catalyst_supported_context: "Catalyst-Supported",
  catalyst_conflicted_context: "Catalyst-Conflicted",
  catalyst_reaction_faded: "Catalyst Reaction Faded",
  catalyst_reaction_persisted: "Catalyst Reaction Persisted",
  catalyst_timing_ambiguous: "Catalyst Timing Ambiguous",
  no_recent_catalyst_found: "No Recent Catalyst",
};

export function formatCatalystContextLabel(label: string): string {
  return CATALYST_CONTEXT_LABELS[label] ?? label;
}

/** Neutral by design -- never green/red, since a catalyst label is
 * descriptive context, not a bullish/bearish signal. */
export function catalystContextLabelColorClass(label: string): string {
  if (label === "catalyst_supported_context" || label === "catalyst_reaction_persisted") {
    return "text-accent";
  }
  if (label === "catalyst_conflicted_context") return "text-warning";
  return "text-muted";
}

export function formatHoursAgo(hours: number | null): string {
  if (hours === null) return "—";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

export function formatSourceCount(count: number): string {
  return `${count} source${count === 1 ? "" : "s"}`;
}

// ---- Forward Prediction Benchmark & Validation Lab (Phase 12) -------------

/** Generic snake_case -> Title Case for the Phase 12 closed enums -- every
 * forecast_value/category/reason is already a fixed, typed vocabulary, so a
 * single mechanical formatter (no per-value label table) is honest and
 * sufficient; it never has to "interpret" anything. */
export function formatEnumLabel(value: string | null): string {
  if (!value) return "—";
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function forecastStatusColorClass(status: string): string {
  if (status === "active") return "text-accent";
  if (status === "abstained") return "text-muted";
  if (status === "invalidated") return "text-negative";
  return "text-foreground";
}

export function forecastOutcomeColorClass(outcome: string): string {
  if (outcome === "correct") return "text-positive";
  if (outcome === "incorrect") return "text-negative";
  return "text-muted";
}

export function evidenceQualityColorClass(quality: string): string {
  if (quality === "high_evidence_support") return "text-positive";
  if (quality === "mixed_evidence") return "text-amber-600 dark:text-amber-400";
  return "text-muted";
}

// ---- Automatic Live Data & Event-Driven Updates (Phase 12.1) -------------

const FRESHNESS_LABELS: Record<string, string> = {
  live: "LIVE",
  recent: "RECENT",
  delayed: "DELAYED",
  stale: "STALE",
  disconnected: "DISCONNECTED",
  unavailable: "UNAVAILABLE",
  market_closed: "MARKET CLOSED",
};

export function formatFreshnessLabel(state: string): string {
  return FRESHNESS_LABELS[state] ?? state.toUpperCase();
}

export function freshnessColorClass(state: string): string {
  if (state === "live") return "text-positive";
  if (state === "recent") return "text-accent";
  if (state === "delayed") return "text-amber-600 dark:text-amber-400";
  if (state === "stale" || state === "disconnected") return "text-negative";
  return "text-muted";
}

export function freshnessDotClass(state: string): string {
  if (state === "live") return "bg-positive";
  if (state === "recent") return "bg-accent";
  if (state === "delayed") return "bg-amber-500";
  if (state === "stale" || state === "disconnected") return "bg-negative";
  return "bg-muted";
}

/** Never a bare current-time label -- always the elapsed time since the
 * value's own source_timestamp (#F/#U), so a stale value can never look
 * fresher than it actually is. */
export function formatAgeSeconds(age: number | null): string {
  if (age === null) return "—";
  if (age < 1) return "<1s ago";
  if (age < 60) return `${age.toFixed(1)}s ago`;
  if (age < 3600) return `${Math.round(age / 60)}m ago`;
  return `${Math.round(age / 3600)}h ago`;
}

export function gateDecisionColorClass(decision: string): string {
  if (decision === "pass") return "text-positive";
  if (decision === "promising") return "text-amber-600 dark:text-amber-400";
  if (decision === "fail") return "text-negative";
  return "text-muted";
}

// ---- Catalyst Research Lab evidence-state messaging (Phase 10.1 #C) -------
//
// A pure presentation layer over already-typed Phase 8/9 fields -- never a
// new statistic, never BUY/SELL/confidence-score language. Each badge is a
// deterministic function of fields the backend already computed.

export interface EvidenceStateInput {
  evidence_maturity: string;
  flags: string[];
  walk_forward_stability: string;
  temporal_stability: string;
  concentration_warning_count: number;
  overlap_warning: string | null;
  contradiction_statuses: string[];
  conclusion_stability_label: string | null;
}

export function deriveEvidenceStateBadges(input: EvidenceStateInput): string[] {
  const badges: string[] = [];

  if (
    input.evidence_maturity === "insufficient" ||
    input.flags.includes("insufficient_sample") ||
    input.flags.includes("low_independent_sample")
  ) {
    badges.push("INSUFFICIENT SAMPLE");
  }
  if (input.flags.includes("high_overlap") || input.flags.includes("overlapping_observations")) {
    badges.push("HIGH OVERLAP");
  }
  if (
    input.concentration_warning_count > 0 ||
    input.flags.includes("symbol_concentration") ||
    input.flags.includes("episode_concentration") ||
    input.flags.includes("temporal_concentration") ||
    input.flags.includes("single_symbol_dependence")
  ) {
    badges.push("CONCENTRATED");
  }
  if (
    input.walk_forward_stability === "unstable" ||
    input.temporal_stability === "unstable" ||
    input.flags.includes("result_unstable") ||
    input.flags.includes("walk_forward_instability") ||
    input.flags.includes("temporal_instability")
  ) {
    badges.push("UNSTABLE");
  }
  if (
    input.contradiction_statuses.includes("assumption_not_supported_in_this_sample") ||
    input.conclusion_stability_label === "reverses"
  ) {
    badges.push("CONTRADICTORY");
  }
  if (input.conclusion_stability_label === "survives") {
    badges.push("OUT-OF-SAMPLE SUPPORT");
  }
  if (input.evidence_maturity !== "replicated") {
    badges.push("NO REPLICATED EDGE");
  }

  return badges;
}

export function evidenceStateBadgeColorClass(badge: string): string {
  if (badge === "OUT-OF-SAMPLE SUPPORT") return "bg-positive/15 text-positive";
  if (badge === "NO REPLICATED EDGE") return "bg-border text-muted";
  return "bg-amber-500/15 text-amber-600 dark:text-amber-400";
}
