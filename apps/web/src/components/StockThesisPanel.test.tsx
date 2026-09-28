import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StockThesisPanel } from "./StockThesisPanel";
import * as api from "@/lib/api";
import type { StockThesis } from "@/lib/types";

function thesis(overrides: Partial<StockThesis> = {}): StockThesis {
  return {
    symbol: "SPY",
    timeframe: "1h",
    as_of: "2026-01-05T15:00:00Z",
    generated_at: "2026-01-05T15:00:01Z",
    market_data_provider: "yfinance",
    market_data_cutoff: "2026-01-05T15:00:00Z",
    current_price: 500.12,
    session: "regular",
    multi_timeframe_trend: [
      { timeframe: "1d", trend: "bullish", strength: "established", explanation: ["Higher high confirmed"], candle_count: 200 },
    ],
    key_levels: [],
    decision_plan: null,
    evidence_diffs: [],
    active_setups: [],
    near_misses: [],
    evidence_for: ["Bullish structure on: 1d"],
    evidence_against: [],
    contradictions: [],
    catalyst_context: null,
    nearest_catalyst_event: null,
    historical_analogs: null,
    signal_validation: { gate_version: "1.0", decision: "not_enough_data", reasons: ["No evaluation yet"], evaluated_at: null },
    ranking_gate_status: "fail",
    ranking_validation_message: "VALIDATED RELATIVE RANKING: UNAVAILABLE",
    history_sufficiency: "full",
    history_sufficiency_reason: "200 candles of history are available.",
    research_lean: "bullish_lean",
    research_lean_reasons: ["Bullish structure on: 1d"],
    strengthens_if: [],
    weakens_if: [],
    invalidation: [],
    fundamentals_status: "FUNDAMENTAL ANALYSIS -- data source not configured",
    data_limitations: [],
    ...overrides,
  };
}

describe("Phase 19: StockThesisPanel", () => {
  it("does not fetch until the user clicks Analyze This Stock", () => {
    const spy = vi.spyOn(api, "getStockThesis").mockResolvedValue(thesis());
    render(<StockThesisPanel symbol="SPY" timeframe="1h" />);
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /analyze this stock/i })).toBeInTheDocument();
  });

  it("composes the thesis on click and renders bull case, lean, and ranking-unavailable message", async () => {
    vi.spyOn(api, "getStockThesis").mockResolvedValue(thesis());
    render(<StockThesisPanel symbol="SPY" timeframe="1h" />);

    fireEvent.click(screen.getByRole("button", { name: /analyze this stock/i }));

    await waitFor(() => expect(screen.getByText("BULLISH LEAN")).toBeInTheDocument());
    expect(screen.getByText("VALIDATED RELATIVE RANKING: UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getAllByText("Bullish structure on: 1d").length).toBeGreaterThan(0);
  });

  it("never renders BUY/SELL/STRONG BUY/STRONG SELL language", async () => {
    vi.spyOn(api, "getStockThesis").mockResolvedValue(thesis());
    render(<StockThesisPanel symbol="SPY" timeframe="1h" />);
    fireEvent.click(screen.getByRole("button", { name: /analyze this stock/i }));
    await waitFor(() => expect(screen.getByText("BULLISH LEAN")).toBeInTheDocument());

    const text = document.body.textContent?.toUpperCase() ?? "";
    for (const term of ["BUY", "SELL", "STRONG BUY", "STRONG SELL"]) {
      expect(text).not.toContain(term);
    }
  });

  it("resets state when the symbol changes", async () => {
    vi.spyOn(api, "getStockThesis").mockResolvedValue(thesis());
    const { rerender } = render(<StockThesisPanel symbol="SPY" timeframe="1h" />);
    fireEvent.click(screen.getByRole("button", { name: /analyze this stock/i }));
    await waitFor(() => expect(screen.getByText("BULLISH LEAN")).toBeInTheDocument());

    rerender(<StockThesisPanel symbol="AAPL" timeframe="1h" />);
    expect(screen.queryByText("BULLISH LEAN")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyze this stock/i })).toBeInTheDocument();
  });
});
