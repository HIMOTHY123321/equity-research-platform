import { describe, expect, it } from "vitest";

import { limitForRange } from "./chartRanges";

describe("limitForRange (§7/§8: range vs interval are independent)", () => {
  it("1D on a 5m chart requests roughly one trading day of 5-minute bars", () => {
    const limit = limitForRange("1D", "5m");
    expect(limit).toBeGreaterThanOrEqual(70);
    expect(limit).toBeLessThanOrEqual(90);
  });

  it("MAX on a 1d chart requests a large, still-bounded number of bars", () => {
    const limit = limitForRange("MAX", "1d");
    expect(limit).toBeGreaterThan(1000);
    expect(limit).toBeLessThanOrEqual(5000);
  });

  it("the same range requests fewer bars for a coarser interval", () => {
    const fiveMinute = limitForRange("1Y", "5m");
    const daily = limitForRange("1Y", "1d");
    expect(daily).toBeLessThan(fiveMinute);
  });

  it("never requests below a sane floor even for a tiny range/coarse interval", () => {
    expect(limitForRange("1D", "1d")).toBeGreaterThanOrEqual(50);
  });

  it("never exceeds the backend's own bounded cap (5000)", () => {
    for (const range of ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"] as const) {
      for (const timeframe of ["5m", "15m", "1h", "4h", "1d"] as const) {
        expect(limitForRange(range, timeframe)).toBeLessThanOrEqual(5000);
      }
    }
  });
});
