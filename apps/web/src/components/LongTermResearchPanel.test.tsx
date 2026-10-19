import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LongTermResearchPanel } from "./LongTermResearchPanel";
import * as api from "@/lib/api";
import type { LongTermResearchResult } from "@/lib/types";

function makeResult(overrides: Partial<LongTermResearchResult> = {}): LongTermResearchResult {
  return {
    symbol: "AAPL",
    as_of: "2026-10-19T20:15:00Z",
    price: 150.25,
    research_state: "ACCUMULATION_CANDIDATE",
    factors: {
      business_quality: "STRONG",
      business_quality_evidence: { positive: [], negative: [], missing: [] },
      earnings_trend: "IMPROVING",
      earnings_trend_evidence: { positive: [], negative: [], missing: [] },
      valuation: "CHEAP",
      valuation_evidence: { positive: [], negative: [], missing: [] },
      growth: "STRONG",
      growth_evidence: { positive: [], negative: [], missing: [] },
      long_term_trend: "CONSTRUCTIVE",
      long_term_trend_evidence: { positive: [], negative: [], missing: [] },
      history_days: 500,
      limited_history: false,
      accumulation_area_low: 142.95,
      accumulation_area_high: 146.03,
      invalidation_level: 135.8,
    },
    evidence_quality: "STRONG",
    positive_evidence: ["Strong business quality."],
    negative_evidence: [],
    contradictions: [],
    missing_evidence: [],
    reason: "A majority of long-term factors are favorable.",
    what_would_change_state: "Valuation becoming expensive.",
    market_data_provider: "fixture",
    fundamentals_provider: "fixture",
    pipeline_version: "ltr-v1",
    ai_summary: null,
    ...overrides,
  };
}

describe("LongTermResearchPanel", () => {
  it("renders a research card for each watchlist symbol with a snapshot", async () => {
    vi.spyOn(api, "listLongTermResearch").mockResolvedValue([makeResult()]);

    render(<LongTermResearchPanel />);

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/ACCUMULATION CANDIDATE/i)).toBeInTheDocument();
    expect(screen.getByText("$150.25")).toBeInTheDocument();
  });

  it("shows an empty-state message when there is no research yet", async () => {
    vi.spyOn(api, "listLongTermResearch").mockResolvedValue([]);

    render(<LongTermResearchPanel />);

    expect(await screen.findByText(/No long-term research yet/i)).toBeInTheDocument();
  });

  it("labels limited-history symbols explicitly", async () => {
    vi.spyOn(api, "listLongTermResearch").mockResolvedValue([
      makeResult({ symbol: "SPCX", factors: { ...makeResult().factors, limited_history: true } }),
    ]);

    render(<LongTermResearchPanel />);

    expect(await screen.findByText("Limited History")).toBeInTheDocument();
  });

  it("RUN LONG-TERM SCAN button triggers a scan and refreshes the list", async () => {
    const listSpy = vi.spyOn(api, "listLongTermResearch").mockResolvedValue([]);
    const scanSpy = vi.spyOn(api, "runLongTermScan").mockResolvedValue({ as_of: "2026-10-19T20:15:00Z", results: [] });

    render(<LongTermResearchPanel />);
    await screen.findByText(/No long-term research yet/i);

    fireEvent.click(screen.getByText("RUN LONG-TERM SCAN"));

    await waitFor(() => expect(scanSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2)); // initial load + post-scan refresh
  });

  it("shows an error message when the scan fails, without crashing", async () => {
    vi.spyOn(api, "listLongTermResearch").mockResolvedValue([]);
    vi.spyOn(api, "runLongTermScan").mockRejectedValue(new Error("boom"));

    render(<LongTermResearchPanel />);
    await screen.findByText(/No long-term research yet/i);

    fireEvent.click(screen.getByText("RUN LONG-TERM SCAN"));

    expect(await screen.findByText(/Scan failed/i)).toBeInTheDocument();
  });

  it("never renders the literal words BUY or SELL anywhere", async () => {
    vi.spyOn(api, "listLongTermResearch").mockResolvedValue([makeResult()]);

    const { container } = render(<LongTermResearchPanel />);
    await screen.findByText("AAPL");

    expect(container.textContent?.toUpperCase()).not.toMatch(/\bBUY\b|\bSELL\b/);
  });
});
