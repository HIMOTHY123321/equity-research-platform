/**
 * Hardening pass: the pure ordering policy CandlestickChart uses to decide
 * whether an incoming live/forming candle may touch the chart series.
 * Extracted from the component so it's independently testable without a
 * DOM/chart instance -- this is the exact logic that used to crash
 * lightweight-charts with "Cannot update oldest data" when a stale live
 * tick arrived after the series' newest bar had already advanced.
 *
 * `time` here is always a UTCTimestamp (whole seconds since epoch) -- one
 * canonical representation, never a mix of lightweight-charts' BusinessDay
 * objects and UTCTimestamp values.
 */

export type LiveCandleAction = "ignore" | "update" | "append";

/**
 * @param liveTime the incoming live/forming candle's bucket time
 * @param newestSeriesTime the newest time already committed to the series,
 *   or null if the series is empty
 */
export function resolveLiveCandleAction(
  liveTime: number,
  newestSeriesTime: number | null,
): LiveCandleAction {
  if (newestSeriesTime === null) return "append";
  if (liveTime < newestSeriesTime) return "ignore";
  if (liveTime === newestSeriesTime) return "update";
  return "append";
}

/** Whether a live candle belongs to the symbol/timeframe currently being
 * displayed -- guards against a stale overlay from a previous selection
 * leaking onto the chart after a symbol/timeframe switch. */
export function liveCandleMatchesSelection(
  liveCandle: { symbol: string; timeframe: string },
  symbol: string,
  timeframe: string,
): boolean {
  return liveCandle.symbol === symbol && liveCandle.timeframe === timeframe;
}

/** Canonical intraday timestamp conversion: an ISO string (any timezone
 * offset, e.g. the backend's EST/EDT-aware `America/New_York` timestamps)
 * to a UTCTimestamp in whole seconds -- the one representation every chart
 * data point uses, so a candle's DST offset never affects its numeric
 * time value (an EST 07:30 and an EDT 07:30 are different instants and
 * must produce different UTCTimestamps, which `Date` already guarantees
 * since the ISO string itself carries the offset). */
export function toUtcSeconds(isoTimestamp: string): number {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000);
}
