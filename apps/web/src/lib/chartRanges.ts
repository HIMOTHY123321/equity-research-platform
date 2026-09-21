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
  MAX: 5000, // provider truncates to whatever its own real history cap allows
};

// Approximate regular-session bars per trading day, per candle interval.
const BARS_PER_TRADING_DAY: Record<Timeframe, number> = {
  "5m": 78,
  "15m": 26,
  "1h": 7,
  "4h": 2,
  "1d": 1,
};

const MIN_LIMIT = 50;
const MAX_LIMIT = 5000; // matches the backend's own bounded cap (app/api/routes/market.py)

/** How many bars to request for a given (range, interval) combination --
 * the single place range-vs-interval is reconciled into one `limit` value
 * for the existing `GET /api/market/{symbol}/candles?limit=` contract. */
export function limitForRange(range: ChartRange, timeframe: Timeframe): number {
  const tradingDays = RANGE_TRADING_DAYS[range];
  const barsPerDay = BARS_PER_TRADING_DAY[timeframe];
  const estimated = Math.ceil(tradingDays * barsPerDay);
  return Math.min(Math.max(estimated, MIN_LIMIT), MAX_LIMIT);
}
