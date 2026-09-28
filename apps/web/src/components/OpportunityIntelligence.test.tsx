import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpportunityIntelligence } from "./OpportunityIntelligence";
import * as api from "@/lib/api";
import type { OpportunityCandidate, OpportunityListResponse } from "@/lib/types";

function candidate(overrides: Partial<OpportunityCandidate> = {}): OpportunityCandidate {
  return {
    symbol: "SPY",
    as_of: "2026-01-05T15:00:00Z",
    timeframe: "1h",
    category: "watching",
    decision_state: "watching",
    why: "WATCHING: no qualified or near-miss setup detected yet.",
    setup_type: null,
    direction: null,
    structure_trend: "bullish",
    contradictions_present: false,
    signal_validation_decision: "not_enough_data",
    ranking_gate_status: "fail",
    market_data_provider: "yfinance",
    history_sufficiency: "full",
    monitored: true,
    decision_plan_id: null,
    ...overrides,
  };
}

function listResponse(candidates: OpportunityCandidate[]): OpportunityListResponse {
  return {
    as_of: "2026-01-05T15:00:00Z",
    timeframe: "1h",
    candidates,
    ranking_validation_message: "VALIDATED RELATIVE RANKING: UNAVAILABLE",
  };
}

describe("Phase 19: OpportunityIntelligence", () => {
  it("renders candidates with category and why, and the ranking-unavailable message", async () => {
    vi.spyOn(api, "getOpportunities").mockResolvedValue(listResponse([candidate()]));
    render(<OpportunityIntelligence />);

    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());
    expect(screen.getByText("VALIDATED RELATIVE RANKING: UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText(/WATCHING: no qualified/)).toBeInTheDocument();
  });

  it("deep-links to the Market Terminal with symbol and timeframe", async () => {
    vi.spyOn(api, "getOpportunities").mockResolvedValue(listResponse([candidate()]));
    render(<OpportunityIntelligence />);

    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());
    const link = screen.getByRole("link", { name: /open/i });
    expect(link).toHaveAttribute("href", "/?symbol=SPY&timeframe=1h");
  });

  it("shows an honest empty state when nothing matches", async () => {
    vi.spyOn(api, "getOpportunities").mockResolvedValue(listResponse([]));
    render(<OpportunityIntelligence />);

    await waitFor(() =>
      expect(screen.getByText(/no symbols in the monitoring universe match/i)).toBeInTheDocument(),
    );
  });

  it("never renders BUY/SELL/STRONG BUY/STRONG SELL language", async () => {
    vi.spyOn(api, "getOpportunities").mockResolvedValue(listResponse([candidate()]));
    render(<OpportunityIntelligence />);
    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());

    const text = document.body.textContent?.toUpperCase() ?? "";
    for (const term of ["BUY", "SELL", "STRONG BUY", "STRONG SELL"]) {
      expect(text).not.toContain(term);
    }
  });
});
