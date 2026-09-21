import { describe, expect, it } from "vitest";

import { liveCandleMatchesSelection, resolveLiveCandleAction, toUtcSeconds } from "./chartLiveMerge";

describe("resolveLiveCandleAction", () => {
  it("appends when the series is empty", () => {
    expect(resolveLiveCandleAction(1000, null)).toBe("append");
  });

  it("ignores a stale (older) live candle -- this is the exact crash regression", () => {
    // Previously: calling lightweight-charts' series.update() with a time
    // older than the series' newest bar threw "Cannot update oldest data".
    expect(resolveLiveCandleAction(900, 1000)).toBe("ignore");
  });

  it("ignores a duplicate event with the exact same time as a just-processed stale event", () => {
    expect(resolveLiveCandleAction(900, 1000)).toBe("ignore");
    // A second, identical stale event must also be ignored, not crash.
    expect(resolveLiveCandleAction(900, 1000)).toBe("ignore");
  });

  it("updates the current newest bar in place when the time is exactly equal", () => {
    expect(resolveLiveCandleAction(1000, 1000)).toBe("update");
  });

  it("treats a duplicate event at the current newest bar's time as an update, not a crash", () => {
    expect(resolveLiveCandleAction(1000, 1000)).toBe("update");
    expect(resolveLiveCandleAction(1000, 1000)).toBe("update");
  });

  it("appends when the time is strictly newer", () => {
    expect(resolveLiveCandleAction(1300, 1000)).toBe("append");
  });

  it("treats an out-of-order sequence (newer arrives, then an older one) correctly", () => {
    // A genuinely newer bucket arrives first...
    expect(resolveLiveCandleAction(1300, 1000)).toBe("append");
    // ...then a late-arriving, now out-of-order older event must be ignored
    // against the *new* newest time (1300), not the original 1000.
    expect(resolveLiveCandleAction(1000, 1300)).toBe("ignore");
  });
});

describe("liveCandleMatchesSelection", () => {
  it("matches when symbol and timeframe both agree", () => {
    expect(liveCandleMatchesSelection({ symbol: "SPY", timeframe: "5m" }, "SPY", "5m")).toBe(true);
  });

  it("rejects a live candle left over from a previous symbol (symbol switch)", () => {
    // e.g. the user switched SPY -> NVDA -> SPY quickly; a stale NVDA
    // liveCandle object must never be applied to the SPY chart.
    expect(liveCandleMatchesSelection({ symbol: "NVDA", timeframe: "5m" }, "SPY", "5m")).toBe(false);
  });

  it("rejects a live candle left over from a previous timeframe (timeframe switch)", () => {
    expect(liveCandleMatchesSelection({ symbol: "SPY", timeframe: "15m" }, "SPY", "5m")).toBe(false);
  });
});

describe("toUtcSeconds -- canonical timestamp representation, EST/EDT conversion", () => {
  it("produces the same absolute instant regardless of which US Eastern offset the ISO string carries", () => {
    // 2026-06-15 09:30:00 EDT (-04:00) and its equivalent UTC instant.
    const edt = toUtcSeconds("2026-06-15T09:30:00-04:00");
    const utcEquivalent = toUtcSeconds("2026-06-15T13:30:00Z");
    expect(edt).toBe(utcEquivalent);
  });

  it("produces a different instant for the same wall-clock time under EST vs EDT", () => {
    // The same local "09:30:00" wall-clock reading is a genuinely different
    // instant under EST (-05:00, winter) vs EDT (-04:00, summer) -- DST
    // must never be silently ignored when computing a candle's time.
    const edt = toUtcSeconds("2026-06-15T09:30:00-04:00");
    const est = toUtcSeconds("2026-01-15T09:30:00-05:00");
    expect(edt).not.toBe(est);
  });

  it("truncates sub-second precision to whole seconds (UTCTimestamp's contract)", () => {
    expect(toUtcSeconds("2026-06-15T09:30:00.750-04:00")).toBe(toUtcSeconds("2026-06-15T09:30:00-04:00"));
  });
});
