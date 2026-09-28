import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAsyncResource } from "./useAsyncResource";

/** Phase 18 (Priority 10): every panel-level data hook (useCandles,
 * useDecisionPlans, useSymbolCatalysts, ...) is built on this one
 * primitive -- proving the race guard here covers every consumer at once,
 * rather than re-testing it per hook. Simulates "SPY request starts, user
 * immediately switches to NVDA, SPY resolves last": the late SPY response
 * must never overwrite the NVDA data already committed to state. */
describe("Phase 18 (Priority 10): useAsyncResource symbol-switch race safety", () => {
  it("discards a stale response that resolves after a newer request has already started", async () => {
    let resolveSpy: (value: string) => void = () => {};
    const spyPromise = new Promise<string>((resolve) => {
      resolveSpy = resolve;
    });

    const { result, rerender } = renderHook(
      ({ symbol }: { symbol: string }) =>
        useAsyncResource(() => (symbol === "SPY" ? spyPromise : Promise.resolve("NVDA-data")), [symbol]),
      { initialProps: { symbol: "SPY" } },
    );

    // User immediately switches away before the SPY fetch resolves.
    rerender({ symbol: "NVDA" });
    await waitFor(() => expect(result.current.data).toBe("NVDA-data"));

    // The stale SPY request finally resolves AFTER NVDA's data is showing.
    resolveSpy("SPY-data");
    await new Promise((r) => setTimeout(r, 10));

    // NVDA's data must still be displayed -- the late SPY response was discarded.
    expect(result.current.data).toBe("NVDA-data");
    expect(result.current.state).toBe("ready");
  });
});
