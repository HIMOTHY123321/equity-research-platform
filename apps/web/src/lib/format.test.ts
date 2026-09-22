import { describe, expect, it } from "vitest";

import { formatAgeSeconds, formatFreshnessLabel } from "./format";

describe("formatFreshnessLabel (§5: STREAMING LIVE vs LATEST AVAILABLE)", () => {
  it("never claims STREAMING LIVE for fresh data from a non-streaming (polled) provider", () => {
    expect(formatFreshnessLabel("live", false)).toBe("LATEST AVAILABLE");
  });

  it("says STREAMING LIVE only when the active provider genuinely streams", () => {
    expect(formatFreshnessLabel("live", true)).toBe("STREAMING LIVE");
  });

  it("defaults to non-streaming when no argument is given (never assume streaming)", () => {
    expect(formatFreshnessLabel("live")).toBe("LATEST AVAILABLE");
  });

  it("leaves every other freshness state unaffected by streamingActive", () => {
    expect(formatFreshnessLabel("recent", true)).toBe("RECENT");
    expect(formatFreshnessLabel("delayed", true)).toBe("DELAYED");
    expect(formatFreshnessLabel("stale", true)).toBe("STALE");
    expect(formatFreshnessLabel("disconnected", true)).toBe("DISCONNECTED");
    expect(formatFreshnessLabel("market_closed", true)).toBe("MARKET CLOSED");
  });
});

describe("formatAgeSeconds (#7: precise, non-jittery elapsed-time display)", () => {
  it("shows sub-second precision below 1s", () => {
    expect(formatAgeSeconds(0.2)).toBe("0.2s");
  });

  it("shows whole seconds without decimals once >= 1s", () => {
    expect(formatAgeSeconds(1)).toBe("1s");
    expect(formatAgeSeconds(14)).toBe("14s");
  });

  it("shows minutes with zero-padded seconds", () => {
    expect(formatAgeSeconds(63)).toBe("1m 03s");
    expect(formatAgeSeconds(767)).toBe("12m 47s");
  });

  it("shows hours with zero-padded minutes and seconds", () => {
    expect(formatAgeSeconds(7392)).toBe("2h 03m 12s");
  });

  it("returns an em dash placeholder for null (never a fake age)", () => {
    expect(formatAgeSeconds(null)).toBe("—");
  });
});
