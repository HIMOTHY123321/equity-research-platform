import type { Timeframe } from "@/lib/types";

/**
 * Hardening pass (§7/§8): VISIBLE HISTORY RANGE is a separate concept from
 * CANDLE INTERVAL -- "5m" is how long one bar spans, "1Y" is how much
 * history is currently being requested/displayed. Conflating the two
 * (as the chart previously did, with a single fixed `limit` regardless of
 * how far back the user wanted to look) is exactly what made deep history
 * navigation impossible.
 */
export const RANGE_OPTIONS = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"] as const;
export type ChartRange = (typeof RANGE_OPTIONS)[number];

export const DEFAULT_RANGE: ChartRange = "3M";

// Approximate regular-session trading days each range covers. Approximate
// on purpose -- the backend/provider is the actual source of truth for
// what's available; this only decides how many bars to *request*.
const RANGE_TRADING_DAYS: Record<ChartRange, number> = {
  "1D": 1,
  "5D": 5,
  "1M": 21,
  "3M": 63,
  "6M": 126,
  YTD: 185,
  "1Y": 252,
  "5Y": 1260,
  // (#6) 15000 gives headroom for a long-lived symbol's true full listing
  // history (SPY has traded since 1993, ~8500+ daily bars) -- the provider
  // still truncates to whatever its own real history actually covers.
  MAX: 15000,
};

// Approximate CALENDAR days each range spans (trading days -> calendar days
// via the standard ~1.45x weekend/holiday factor) -- this is what actually
// determines compatibility with a provider's real retention window, since
// yfinance's limits ("7d", "60d") are calendar days, not trading days.
const RANGE_CALENDAR_DAYS: Record<ChartRange, number> = {
  "1D": 1,
  "5D": 7,
  "1M": 31,
  "3M": 92,
  "6M": 183,
  YTD: 270,
  "1Y": 366,
  "5Y": 1827,
  MAX: Number.POSITIVE_INFINITY,
};

// Approximate regular-session bars per trading day, per candle interval.
const BARS_PER_TRADING_DAY: Record<Timeframe, number> = {
  "1m": 390,
  "5m": 78,
  "15m": 26,
  "1h": 7,
  "4h": 2,
  "1d": 1,
};

// (MARKET EXPERIENCE COMPLETION PASS #5/#6) yfinance's real, documented
// history-retention ceiling per interval, in calendar days -- see
// app/market_data/yfinance_provider.py's `_YFINANCE_MAX_PERIOD`, which this
// mirrors so the frontend can warn about an incompatible combination
// BEFORE requesting it, not just show a truncated result silently.
const TIMEFRAME_MAX_CALENDAR_DAYS: Record<Timeframe, number> = {
  "1m": 7,
  "5m": 60,
  "15m": 60,
  "1h": 730,
  "4h": 730,
  "1d": Number.POSITIVE_INFINITY,
};

// Preference order (finest-to-coarsest) used to pick a fallback interval
// for a range the user's requested interval can't actually cover.
const FALLBACK_ORDER: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

const MIN_LIMIT = 50;
const MAX_LIMIT = 15000; // matches the backend's own bounded cap (app/api/routes/market.py)

/** How many bars to request for a given (range, interval) combination --
 * the single place range-vs-interval is reconciled into one `limit` value
 * for the existing `GET /api/market/{symbol}/candles?limit=` contract. */
export function limitForRange(range: ChartRange, timeframe: Timeframe): number {
  const tradingDays = RANGE_TRADING_DAYS[range];
  const barsPerDay = BARS_PER_TRADING_DAY[timeframe];
  const estimated = Math.ceil(tradingDays * barsPerDay);
  return Math.min(Math.max(estimated, MIN_LIMIT), MAX_LIMIT);
}

export interface RangeCompatibility {
  /** The interval actually usable for this range -- may differ from what
   * was requested. */
  effectiveTimeframe: Timeframe;
  /** True when `effectiveTimeframe` differs from what the user selected. */
  wasAdjusted: boolean;
  /** Human-readable explanation shown in the UI whenever `wasAdjusted` is
   * true -- e.g. "1m data is unavailable for MAX. Showing 1D." Never null
   * when an adjustment happened; the UI must always disclose the real
   * resolution in use, never silently substitute one. */
  note: string | null;
}

/** (#5/#6) Resolves a genuinely provider-compatible interval for the
 * requested (range, timeframe) pair -- never silently returns a tiny
 * recent window for an impossible combination like MAX+1m. Falls back to
 * the coarsest compatible interval, preferring 1d, and always reports the
 * substitution so the UI can disclose the real resolution in use. */
export function resolveRangeCompatibility(
  range: ChartRange,
  requestedTimeframe: Timeframe,
): RangeCompatibility {
  const rangeDays = RANGE_CALENDAR_DAYS[range];
  if (rangeDays <= TIMEFRAME_MAX_CALENDAR_DAYS[requestedTimeframe]) {
    return { effectiveTimeframe: requestedTimeframe, wasAdjusted: false, note: null };
  }

  // Walk coarser intervals until one can actually cover this range;
  // 1d always can (its max is infinite), so this always terminates.
  const startIdx = FALLBACK_ORDER.indexOf(requestedTimeframe);
  for (let i = startIdx + 1; i < FALLBACK_ORDER.length; i++) {
    const candidate = FALLBACK_ORDER[i];
    if (rangeDays <= TIMEFRAME_MAX_CALENDAR_DAYS[candidate]) {
      return {
        effectiveTimeframe: candidate,
        wasAdjusted: true,
        note: `${requestedTimeframe} data is unavailable for ${range}. Showing ${candidate}.`,
      };
    }
  }
  return {
    effectiveTimeframe: "1d",
    wasAdjusted: requestedTimeframe !== "1d",
    note: requestedTimeframe !== "1d" ? `${requestedTimeframe} data is unavailable for ${range}. Showing 1d.` : null,
  };
}
