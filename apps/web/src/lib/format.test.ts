import { describe, expect, it } from "vitest";

import { formatFreshnessLabel } from "./format";

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
