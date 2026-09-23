import { describe, expect, it } from "vitest";

import { countPrependedCandles, mergeOlderCandles, shiftLogicalRange } from "./chartHistoryMerge";
import type { Candle } from "@/lib/types";

function candle(timestamp: string, close = 100): Candle {
  return {
    symbol: "SPY",
    timeframe: "1d",
    timestamp,
    session: "regular",
    open: close,
    high: close,
    low: close,
    close,
    volume: 1000,
  };
}

describe("mergeOlderCandles", () => {
  it("returns existing unchanged when incoming is empty", () => {
    const existing = [candle("2026-01-05T00:00:00Z")];
    expect(mergeOlderCandles(existing, [])).toBe(existing);
  });

  it("prepends a fully non-overlapping older page in ascending order", () => {
    const existing = [candle("2026-01-05T00:00:00Z"), candle("2026-01-06T00:00:00Z")];
    const incoming = [candle("2026-01-03T00:00:00Z"), candle("2026-01-04T00:00:00Z")];

    const merged = mergeOlderCandles(existing, incoming);
    expect(merged.map((c) => c.timestamp)).toEqual([
      "2026-01-03T00:00:00Z",
      "2026-01-04T00:00:00Z",
      "2026-01-05T00:00:00Z",
      "2026-01-06T00:00:00Z",
    ]);
  });

  it("dedupes on full overlap, keeping the existing candle's values", () => {
    const existing = [candle("2026-01-05T00:00:00Z", 111)];
    const incoming = [candle("2026-01-05T00:00:00Z", 222)];

    const merged = mergeOlderCandles(existing, incoming);
    expect(merged).toHaveLength(1);
    expect(merged[0].close).toBe(111);
  });

  it("dedupes on partial overlap, merging non-overlapping candles from both sides", () => {
    const existing = [candle("2026-01-04T00:00:00Z"), candle("2026-01-05T00:00:00Z", 111)];
    const incoming = [
      candle("2026-01-02T00:00:00Z"),
      candle("2026-01-03T00:00:00Z"),
      candle("2026-01-04T00:00:00Z", 222), // overlaps -- existing wins
    ];

    const merged = mergeOlderCandles(existing, incoming);
    expect(merged.map((c) => c.timestamp)).toEqual([
      "2026-01-02T00:00:00Z",
      "2026-01-03T00:00:00Z",
      "2026-01-04T00:00:00Z",
      "2026-01-05T00:00:00Z",
    ]);
    const overlapping = merged.find((c) => c.timestamp === "2026-01-04T00:00:00Z");
    expect(overlapping?.close).toBe(100); // existing's default close, not 222
  });

  it("sorts an out-of-order provider response into ascending order", () => {
    const existing = [candle("2026-01-05T00:00:00Z")];
    const incoming = [
      candle("2026-01-02T00:00:00Z"),
      candle("2026-01-04T00:00:00Z"),
      candle("2026-01-01T00:00:00Z"),
      candle("2026-01-03T00:00:00Z"),
    ];

    const merged = mergeOlderCandles(existing, incoming);
    const timestamps = merged.map((c) => c.timestamp);
    expect(timestamps).toEqual([...timestamps].sort());
  });
});

describe("shiftLogicalRange", () => {
  it("shifts both from and to by the given amount", () => {
    expect(shiftLogicalRange({ from: 10, to: 50 }, 25)).toEqual({ from: 35, to: 75 });
  });

  it("supports a negative shift", () => {
    expect(shiftLogicalRange({ from: 10, to: 50 }, -5)).toEqual({ from: 5, to: 45 });
  });
});

describe("countPrependedCandles", () => {
  it("returns 0 when previous is empty (initial load, not a prepend)", () => {
    expect(countPrependedCandles([], [candle("2026-01-05T00:00:00Z")])).toBe(0);
  });

  it("returns 0 when next is not longer than previous", () => {
    const previous = [candle("2026-01-05T00:00:00Z")];
    expect(countPrependedCandles(previous, previous)).toBe(0);
    expect(countPrependedCandles(previous, [])).toBe(0);
  });

  it("returns the exact prepend count for a clean older-history prepend", () => {
    const previous = [candle("2026-01-05T00:00:00Z"), candle("2026-01-06T00:00:00Z")];
    const next = [
      candle("2026-01-03T00:00:00Z"),
      candle("2026-01-04T00:00:00Z"),
      candle("2026-01-05T00:00:00Z"),
      candle("2026-01-06T00:00:00Z"),
    ];
    expect(countPrependedCandles(previous, next)).toBe(2);
  });

  it("returns 0 when the tail diverges from previous (a fresh symbol/timeframe load, not a prepend)", () => {
    const previous = [candle("2026-01-05T00:00:00Z"), candle("2026-01-06T00:00:00Z")];
    // Same length relationship as a real prepend, but the tail doesn't
    // match -- e.g. the user switched symbols mid-fetch.
    const next = [
      candle("2026-02-01T00:00:00Z"),
      candle("2026-02-02T00:00:00Z"),
      candle("2026-02-03T00:00:00Z"),
      candle("2026-02-04T00:00:00Z"),
    ];
    expect(countPrependedCandles(previous, next)).toBe(0);
  });
});
