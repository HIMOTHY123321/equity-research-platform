import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecentAlertsPanel } from "./RecentAlertsPanel";
import * as api from "@/lib/api";
import type { AlertEvent } from "@/lib/types";

function alert(overrides: Partial<AlertEvent> = {}): AlertEvent {
  return {
    alert_id: "a1",
    symbol: "SPY",
    decision_plan_id: "plan-1",
    setup_id: "setup-1",
    alert_type: "entry_conditions_met",
    severity: "important",
    title: "Entry conditions met",
    summary: "1h close above 500.00",
    previous_state: "watching",
    current_state: "entry_conditions_met",
    occurred_at: "2026-09-27T14:31:00Z",
    source_timestamp: "2026-09-27T14:31:00Z",
    evaluated_at: "2026-09-27T14:31:00Z",
    trigger_condition_ids: [],
    evidence_refs: [],
    transition_id: "t-1",
    timeframe: "1h",
    setup_type: "breakout_retest",
    direction: "bullish",
    research_status: [],
    ranking_gate_status: "fail",
    forward_validation_gate_status: null,
    provider: "yfinance",
    data_freshness_state: "live",
    dedup_key: "k1",
    ...overrides,
  } as AlertEvent;
}

describe("Phase 18 (§30): RecentAlertsPanel", () => {
  it("shows an honest empty state with no alerts", async () => {
    vi.spyOn(api, "listAlerts").mockResolvedValue([]);
    render(<RecentAlertsPanel symbol="SPY" />);
    await waitFor(() => expect(screen.getByText(/no recent alerts for spy/i)).toBeInTheDocument());
  });

  it("renders alerts with a deep link matching the AlertCard/Scanner shape", async () => {
    vi.spyOn(api, "listAlerts").mockResolvedValue([alert()]);
    render(<RecentAlertsPanel symbol="SPY" />);

    await waitFor(() => expect(screen.getByText("Entry Conditions Met")).toBeInTheDocument());
    const link = screen.getByRole("link", { name: "Open →" });
    expect(link).toHaveAttribute("href", "/?symbol=SPY&decision=plan-1&timeframe=1h");
  });

  it("fetches scoped to the given symbol", async () => {
    const spy = vi.spyOn(api, "listAlerts").mockResolvedValue([]);
    render(<RecentAlertsPanel symbol="NVDA" limit={5} />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ symbol: "NVDA", limit: 5 }));
  });
});
