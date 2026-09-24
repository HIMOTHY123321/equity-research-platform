import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DecisionPlan } from "@/lib/types";

const { scanDecisionsMock } = vi.hoisted(() => ({ scanDecisionsMock: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, scanDecisions: scanDecisionsMock };
});

import { useDecisionPlans } from "./useDecisionPlans";

function plan(overrides: Partial<DecisionPlan> = {}): DecisionPlan {
  return {
    decision_plan_id: "plan-1",
    symbol: "SPY",
    timeframe: "1h",
    setup_id: "setup-1",
    setup_type: "breakout_retest",
    direction: "bullish",
    created_at: "2026-09-21T13:00:00+00:00",
    as_of: "2026-09-21T13:00:00+00:00",
    state: "watching",
    entry_conditions: [],
    invalidation_conditions: [],
    exit_conditions: [],
    monitoring_conditions: [],
    transitions: [],
    activation_snapshot: null,
    research_status: [],
    evidence_quality: null,
    ranking_gate_status: "fail",
    abstention_reason: null,
    source_setup_snapshot_id: null,
    source_evidence_packet_id: null,
    pipeline_version: "1.0",
    schema_version: "1.0",
    ...overrides,
  };
}

describe("useDecisionPlans", () => {
  it("never fetches when no symbol is selected", async () => {
    scanDecisionsMock.mockResolvedValue([plan()]);
    const { result } = renderHook(() => useDecisionPlans(null, "1h"));

    await waitFor(() => expect(result.current.state).toBe("ready"));

    expect(scanDecisionsMock).not.toHaveBeenCalled();
    expect(result.current.data).toEqual([]);
  });

  it("scans with the given symbol/timeframe and returns the resulting plans", async () => {
    scanDecisionsMock.mockResolvedValue([plan()]);
    const { result } = renderHook(() => useDecisionPlans("SPY", "1h"));

    await waitFor(() => expect(result.current.state).toBe("ready"));

    expect(scanDecisionsMock).toHaveBeenCalledWith("SPY", "1h");
    expect(result.current.data).toEqual([plan()]);
  });

  it("re-scans when the symbol changes", async () => {
    scanDecisionsMock.mockResolvedValue([]);
    const { rerender } = renderHook(({ symbol }) => useDecisionPlans(symbol, "1h"), {
      initialProps: { symbol: "SPY" },
    });
    await waitFor(() => expect(scanDecisionsMock).toHaveBeenCalledWith("SPY", "1h"));

    rerender({ symbol: "NVDA" });
    await waitFor(() => expect(scanDecisionsMock).toHaveBeenCalledWith("NVDA", "1h"));
  });
});
