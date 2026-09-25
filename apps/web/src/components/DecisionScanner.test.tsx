import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveGlobalEvent: () => {},
}));

import { DecisionScanner } from "./DecisionScanner";
import * as api from "@/lib/api";
import type { ScannerRow } from "@/lib/types";

const ROWS: ScannerRow[] = [
  {
    symbol: "SPY",
    decision_plan_id: "plan-spy",
    state: "invalidated",
    setup_type: "range_breakout",
    timeframe: "1h",
    direction: "bullish",
    research_status: [],
    ranking_gate_status: "fail",
    last_change_at: "2026-01-01T15:00:00Z",
    other_monitored_plan_count: 0,
  },
  {
    symbol: "NVDA",
    decision_plan_id: "plan-nvda",
    state: "watching",
    setup_type: "range_breakout",
    timeframe: "1h",
    direction: "bullish",
    research_status: [],
    ranking_gate_status: "fail",
    last_change_at: "2026-01-01T14:00:00Z",
    other_monitored_plan_count: 0,
  },
  {
    symbol: "AAPL",
    decision_plan_id: null,
    state: null,
    setup_type: null,
    timeframe: null,
    direction: null,
    research_status: [],
    ranking_gate_status: "fail",
    last_change_at: null,
    other_monitored_plan_count: 0,
  },
];

describe("DecisionScanner", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a row for every monitored symbol, including one with no plan", async () => {
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue(ROWS);

    render(<DecisionScanner />);

    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("No plan")).toBeInTheDocument();
  });

  it("never renders a score/rank/expected-return column", async () => {
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue(ROWS);

    render(<DecisionScanner />);
    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());

    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/expected return/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/best trade/i)).not.toBeInTheDocument();
  });

  it("the Invalidated filter shows only invalidated-state rows", async () => {
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue(ROWS);

    render(<DecisionScanner />);
    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Invalidated" }));

    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
  });

  it("the symbol filter narrows rows by substring match", async () => {
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue(ROWS);

    render(<DecisionScanner />);
    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("Filter symbol…"), { target: { value: "NV" } });

    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.queryByText("SPY")).not.toBeInTheDocument();
  });

  it("shows an empty state message when the universe is empty", async () => {
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue([]);

    render(<DecisionScanner />);

    await waitFor(() => expect(screen.getByText(/no monitored symbols/i)).toBeInTheDocument());
  });
});
