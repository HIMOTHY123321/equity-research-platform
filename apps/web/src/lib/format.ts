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
