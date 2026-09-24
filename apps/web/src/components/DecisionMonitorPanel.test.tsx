import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionMonitorPanel } from "./DecisionMonitorPanel";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import * as api from "@/lib/api";
import type { DecisionPlan } from "@/lib/types";

function condition(overrides: Partial<DecisionPlan["entry_conditions"][number]> = {}) {
  return {
    id: "cond-1",
    role: "entry" as const,
    type: "close_above" as const,
    description: "1h close above 100.00",
    timeframe: "1h",
    bar_semantics: "completed_bar" as const,
    operator: ">=",
    required_value: 100,
    actual_value: null,
    status: "pending" as const,
    evaluated_at: null,
    source_evidence_ref: null,
    ...overrides,
  };
}

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
    entry_conditions: [condition()],
    invalidation_conditions: [],
    exit_conditions: [],
    monitoring_conditions: [],
    transitions: [
      {
        transition_id: "t-1",
        decision_plan_id: "plan-1",
        from_state: null,
        to_state: "evaluating",
        occurred_at: "2026-09-21T13:00:00+00:00",
        as_of: "2026-09-21T13:00:00+00:00",
        reason: "Setup qualified",
        trigger_condition_ids: [],
        evidence_refs: [],
        pipeline_version: "1.0",
      },
    ],
    activation_snapshot: null,
    research_status: ["research_monitoring_only"],
    evidence_quality: null,
    ranking_gate_status: "fail",
    abstention_reason: null,
    source_setup_snapshot_id: "setup-1",
    source_evidence_packet_id: null,
    pipeline_version: "1.0",
    schema_version: "1.0",
    ...overrides,
  };
}

function useQuery(plans: DecisionPlan[] | null, loadState: "loading" | "ready" | "error" = "ready") {
  return { data: plans, state: loadState, error: null } as ReturnType<typeof useAsyncResource<DecisionPlan[]>>;
}

describe("DecisionMonitorPanel", () => {
  it("prompts for a symbol when none is selected", () => {
    render(<DecisionMonitorPanel symbol={null} query={useQuery(null, "loading")} />);
    expect(screen.getByText(/select a symbol/i)).toBeInTheDocument();
  });

  it("shows an empty state when no plans exist for the symbol", () => {
    render(<DecisionMonitorPanel symbol="SPY" query={useQuery([])} />);
    expect(screen.getByText(/no decision plans for spy/i)).toBeInTheDocument();
  });

  it("renders an open plan under the active section, not resolved/abstained", () => {
    render(<DecisionMonitorPanel symbol="SPY" query={useQuery([plan({ state: "watching" })])} />);
    expect(screen.getByText("Watching")).toBeInTheDocument();
    expect(screen.queryByText("RESOLVED / ABSTAINED")).not.toBeInTheDocument();
  });

  it("splits terminal-state plans into the resolved/abstained section", () => {
    render(
      <DecisionMonitorPanel
        symbol="SPY"
        query={useQuery([plan({ decision_plan_id: "plan-2", state: "invalidated" })])}
      />,
    );
    expect(screen.getByText("RESOLVED / ABSTAINED")).toBeInTheDocument();
    expect(screen.getByText("Invalidated")).toBeInTheDocument();
  });

  it("never renders an affirmative BUY/SELL recommendation or a confidence percentage", () => {
    // The panel's own disclaimer legitimately says "never a BUY/SELL
    // recommendation" -- what must never appear is an AFFIRMATIVE
    // recommendation or confidence-percentage claim, not the bare words.
    render(<DecisionMonitorPanel symbol="SPY" query={useQuery([plan()])} />);
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toMatch(/\bstrong buy\b/);
    expect(text).not.toMatch(/\bis a buy\b|\bis a sell\b/);
    expect(text).not.toMatch(/\d+%\s*confiden/);
    expect(text).not.toMatch(/guaranteed/);
  });

  it("expanding a plan card shows its missing entry conditions", async () => {
    vi.spyOn(api, "getDecisionExplanations").mockResolvedValue({
      why_now: "not reached",
      why_not_yet: "Entry conditions are not yet satisfied.\n- MISSING: 1h close above 100.00 (actual: unavailable, required: 100.00, status: pending)",
      what_would_change_state: ["ENTRY CONDITIONS MET if: 1h close above 100.00"],
      is_terminal: false,
    });
    vi.spyOn(api, "getDecisionTransitions").mockResolvedValue([]);

    render(<DecisionMonitorPanel symbol="SPY" query={useQuery([plan()])} />);
    fireEvent.click(screen.getByText("Breakout + Retest"));

    await waitFor(() => expect(screen.getByText(/1h close above 100.00/)).toBeInTheDocument());
  });
});
