import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AlertCard } from "./AlertCard";
import type { AlertEvent } from "@/lib/types";

function makeAlert(overrides: Partial<AlertEvent> = {}): AlertEvent {
  return {
    alert_id: "alert-1",
    symbol: "QQQ",
    decision_plan_id: "plan-qqq",
    setup_id: "setup-1",
    alert_type: "invalidated",
    severity: "critical",
    title: "Invalidated",
    summary: "Invalidation condition met before entry",
    previous_state: "watching",
    current_state: "invalidated",
    occurred_at: "2026-09-25T21:16:24Z",
    source_timestamp: null,
    evaluated_at: "2026-09-25T21:16:24Z",
    trigger_condition_ids: [],
    evidence_refs: [],
    transition_id: "transition-1",
    timeframe: "1h",
    setup_type: "resistance_rejection",
    direction: "bearish",
    research_status: ["research monitoring only"],
    ranking_gate_status: "fail",
    forward_validation_gate_status: null,
    provider: "yfinance",
    data_freshness_state: null,
    dedup_key: "dedup-1",
    origin: "live_prospective",
    schema_version: "1",
    pipeline_version: "test",
    created_at: "2026-09-25T21:16:24Z",
    ...overrides,
  };
}

describe("AlertCard deep link (regression)", () => {
  // Phase 14.1: without `&timeframe=`, the linked plan's own timeframe
  // almost never matches whatever Overview happens to have selected, so
  // MarketWorkspace never even fetches it and the highlight silently
  // never renders (see MarketWorkspace.tsx).
  it("the Open plan link carries the alert's own timeframe alongside symbol and decision", () => {
    render(<AlertCard alert={makeAlert()} read={false} onAcknowledge={vi.fn()} />);

    const link = screen.getByRole("link", { name: "Open plan →" });
    expect(link).toHaveAttribute("href", "/?symbol=QQQ&decision=plan-qqq&timeframe=1h");
  });

  it("omits the timeframe param when the alert has none", () => {
    render(<AlertCard alert={makeAlert({ timeframe: null })} read={false} onAcknowledge={vi.fn()} />);

    const link = screen.getByRole("link", { name: "Open plan →" });
    expect(link).toHaveAttribute("href", "/?symbol=QQQ&decision=plan-qqq");
  });

  it("renders no deep link at all when there is no decision plan", () => {
    render(<AlertCard alert={makeAlert({ decision_plan_id: null })} read={false} onAcknowledge={vi.fn()} />);

    expect(screen.queryByRole("link", { name: /open plan/i })).not.toBeInTheDocument();
  });
});
