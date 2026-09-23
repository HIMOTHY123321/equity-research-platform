/**
 * FINAL TERMINAL POLISH PASS (#1): pure helpers for lazy pan-left historical
 * loading. Deliberately kept separate from chartLiveMerge.ts -- merging
 * older REST history and overlaying a live/forming candle are two unrelated
 * concerns (one is "prepend older bars behind what's shown", the other is
 * "touch only the newest bar"), and mixing them risks a live tick being
 * treated as a history page or vice versa.
 */

import type { Candle } from "@/lib/types";

/**
 * Merge an older-history page into the currently-loaded candle series.
 * Ascending order, deduplicated by timestamp. On a timestamp collision the
 * already-displayed `existing` candle wins -- a deterministic rule that
 * never lets a re-fetched/overlapping page silently rewrite a candle the
 * user is already looking at. Handles empty `incoming`, full overlap,
 * partial overlap, and an out-of-order provider response (sorted at the
 * end regardless of input order).
 */
export function mergeOlderCandles(existing: Candle[], incoming: Candle[]): Candle[] {
  if (incoming.length === 0) return existing;

  const byTimestamp = new Map<string, Candle>();
  for (const candle of incoming) {
    byTimestamp.set(candle.timestamp, candle);
  }
  for (const candle of existing) {
    byTimestamp.set(candle.timestamp, candle);
  }

  return Array.from(byTimestamp.values()).sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
}

export interface LogicalRangeLike {
  from: number;
  to: number;
}

/** Shift a visible logical range by `shiftBy` bars -- the math that keeps
 * the same candles on screen after older bars are prepended (every existing
 * bar's logical index increases by the number of bars inserted before it). */
export function shiftLogicalRange(range: LogicalRangeLike, shiftBy: number): LogicalRangeLike {
  return { from: range.from + shiftBy, to: range.to + shiftBy };
}

/**
 * How many candles were prepended to `previous` to produce `next`, or 0 if
 * this isn't a pure older-history prepend (e.g. a fresh symbol/timeframe
 * load, where `next` shares no guaranteed relationship with `previous`).
 * Confirmed by checking that `next`'s tail lines up exactly, timestamp for
 * timestamp, with all of `previous` -- the already-displayed candles must
 * be completely unchanged for this to count as a prepend.
 */
export function countPrependedCandles(previous: Candle[], next: Candle[]): number {
  if (previous.length === 0 || next.length <= previous.length) return 0;

  const prependCount = next.length - previous.length;
  const tail = next.slice(prependCount);
  for (let i = 0; i < previous.length; i++) {
    if (tail[i].timestamp !== previous[i].timestamp) return 0;
  }
  return prependCount;
}
