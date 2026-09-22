import { describe, expect, it } from "vitest";

import { limitForRange, RANGE_OPTIONS, resolveRangeCompatibility } from "./chartRanges";

describe("limitForRange (§7/§8: range vs interval are independent)", () => {
  it("1D on a 5m chart requests roughly one trading day of 5-minute bars", () => {
    const limit = limitForRange("1D", "5m");
    expect(limit).toBeGreaterThanOrEqual(70);
    expect(limit).toBeLessThanOrEqual(90);
  });

  it("MAX on a 1d chart requests a large, still-bounded number of bars", () => {
    const limit = limitForRange("MAX", "1d");
    expect(limit).toBeGreaterThan(1000);
    expect(limit).toBeLessThanOrEqual(15000);
  });

  it("the same range requests fewer bars for a coarser interval", () => {
    const fiveMinute = limitForRange("1Y", "5m");
    const daily = limitForRange("1Y", "1d");
    expect(daily).toBeLessThan(fiveMinute);
  });

  it("never requests below a sane floor even for a tiny range/coarse interval", () => {
    expect(limitForRange("1D", "1d")).toBeGreaterThanOrEqual(50);
  });

  it("never exceeds the backend's own bounded cap (15000)", () => {
    for (const range of ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"] as const) {
      for (const timeframe of ["1m", "5m", "15m", "1h", "4h", "1d"] as const) {
        expect(limitForRange(range, timeframe)).toBeLessThanOrEqual(15000);
      }
    }
  });
});

describe("resolveRangeCompatibility (#5/#6: truthful MAX/interval compatibility)", () => {
  it("1D + 1m is compatible -- no adjustment", () => {
    const result = resolveRangeCompatibility("1D", "1m");
    expect(result.effectiveTimeframe).toBe("1m");
    expect(result.wasAdjusted).toBe(false);
    expect(result.note).toBeNull();
  });

  it("MAX + 1m falls back to 1d with a visible note, never a silent tiny window", () => {
    const result = resolveRangeCompatibility("MAX", "1m");
    expect(result.effectiveTimeframe).toBe("1d");
    expect(result.wasAdjusted).toBe(true);
    expect(result.note).toBe("1m data is unavailable for MAX. Showing 1d.");
  });

  it("3M + 1m falls back to a coarser but still-intraday interval, not straight to 1d", () => {
    const result = resolveRangeCompatibility("3M", "1m");
    expect(result.effectiveTimeframe).not.toBe("1m");
    expect(result.wasAdjusted).toBe(true);
    expect(result.note).toContain("1m data is unavailable for 3M");
  });

  it("1Y + 1h is compatible (within yfinance's 730-day 1h window)", () => {
    const result = resolveRangeCompatibility("1Y", "1h");
    expect(result.effectiveTimeframe).toBe("1h");
    expect(result.wasAdjusted).toBe(false);
  });

  it("5Y + 1h is NOT compatible and falls back toward daily resolution", () => {
    const result = resolveRangeCompatibility("5Y", "1h");
    expect(result.wasAdjusted).toBe(true);
    expect(result.effectiveTimeframe).toBe("1d");
  });

  it("any range + 1d is always compatible", () => {
    for (const range of RANGE_OPTIONS) {
      const result = resolveRangeCompatibility(range, "1d");
      expect(result.wasAdjusted).toBe(false);
      expect(result.effectiveTimeframe).toBe("1d");
    }
  });
});
