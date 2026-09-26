import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ValidationLab } from "./ValidationLab";
import * as api from "@/lib/api";
import type {
  CohortStatistics,
  HistoricalProspectiveComparison,
  ObservationStatus,
  SignalGateEvaluation,
  ValidationSummary,
} from "@/lib/types";

const NOT_ENOUGH_DATA_GATE: SignalGateEvaluation = {
  gate_version: "v1",
  decision: "not_enough_data",
  reasons: ["0 independent episode(s) (need 20); 0 symbol(s) (need 5); 0.0 observation day(s) (need 20)."],
  raw_n: 0,
  independent_episode_count: 0,
  purged_n: 0,
  symbol_count: 0,
  observation_days: 0,
  max_symbol_share: null,
  median_effect: null,
  cost_adjusted_effect_at_max_bps: null,
  criteria: {
    min_independent_episodes: 20,
    min_symbols: 5,
    max_single_symbol_share: 0.4,
    min_observation_days: 20,
    max_cost_bps_for_survival: 5,
    require_cost_survival: true,
    require_historical_agreement: false,
  },
};

const EMPTY_STATUS: ObservationStatus = { total: 0, resolved: 0, unresolved: 0 };

const EMPTY_COHORT: CohortStatistics = {
  cohort_label: "entry_conditions_met",
  horizon_bars: 5,
  raw_n: 0,
  independent_n: 0,
  purged_n: 0,
  mean: null,
  median: null,
  stdev: null,
  p25: null,
  p75: null,
  positive_rate: null,
  mfe_atr_median: null,
  mae_atr_median: null,
  invalidation_rate: null,
  exit_rate: null,
  bootstrap_available: false,
  bootstrap_point_estimate: null,
  bootstrap_lower: null,
  bootstrap_upper: null,
  bootstrap_method: null,
  baseline_type: null,
  baseline_median: null,
  effect_vs_baseline: null,
  cost_sensitivity: [],
  concentration_warnings: [],
};

const EMPTY_SUMMARY: ValidationSummary = {
  generated_at: "2026-01-01T00:00:00Z",
  gate_version: "v1",
  decision: "not_enough_data",
  text: "Forward Validation Gate: NOT ENOUGH DATA. This is a descriptive research summary of past observations only -- it is not directive trading guidance and contains no probability or confidence estimate of future performance.",
  schema_version: "1.0",
};

const EMPTY_COMPARISON: HistoricalProspectiveComparison = {
  cohort_label: "SPY:breakout_retest:bullish",
  historical_n: 0,
  historical_median_effect: null,
  prospective_n: 0,
  prospective_median_effect: null,
  direction_agreement: null,
  magnitude_agreement: null,
  note: "Comparison unavailable: one or both datasets have no resolved observations.",
};

describe("ValidationLab (Phase 15)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getSignalGate").mockResolvedValue(NOT_ENOUGH_DATA_GATE);
    vi.spyOn(api, "getSignalGateHistory").mockResolvedValue([]);
    vi.spyOn(api, "getValidationStatus").mockResolvedValue(EMPTY_STATUS);
    vi.spyOn(api, "getValidationCohort").mockResolvedValue(EMPTY_COHORT);
    vi.spyOn(api, "getHistoricalComparison").mockResolvedValue(EMPTY_COMPARISON);
    vi.spyOn(api, "getProspectiveObservations").mockResolvedValue([]);
    vi.spyOn(api, "getValidationSummary").mockResolvedValue(EMPTY_SUMMARY);
  });

  it("renders NOT ENOUGH DATA with factual reasons when there is no data", async () => {
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getByText("NOT ENOUGH DATA")).toBeInTheDocument());
    expect(screen.getByText(/0 independent episode/)).toBeInTheDocument();
  });

  it("shows resolved/unresolved observation counts", async () => {
    vi.spyOn(api, "getValidationStatus").mockResolvedValue({ total: 12, resolved: 5, unresolved: 7 });
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getByText("PROSPECTIVE OBSERVATIONS")).toBeInTheDocument());
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("never renders BUY/SELL as an actionable recommendation, or fabricated confidence scores", async () => {
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getByText("NOT ENOUGH DATA")).toBeInTheDocument());
    const text = document.body.textContent ?? "";
    // The UI is explicitly allowed (and expected) to disclaim BUY/SELL --
    // what must never appear is BUY/SELL used as an imperative
    // recommendation, or any fabricated confidence/probability figure.
    expect(text).not.toMatch(/\bbuy (this|now|signal)\b/i);
    expect(text).not.toMatch(/\bsell (this|now|signal)\b/i);
    expect(text).toMatch(/never a BUY\/SELL recommendation/i);
    expect(text).not.toMatch(/confidence score/i);
    expect(text).not.toMatch(/probability of success/i);
  });

  it("labels cost sensitivity as an estimate, never as actual fills", async () => {
    vi.spyOn(api, "getValidationCohort").mockResolvedValue({
      ...EMPTY_COHORT,
      raw_n: 40,
      median: 0.5,
      cost_sensitivity: [
        { cost_bps: 0, median_return_after_cost: 0.5, mean_return_after_cost: 0.5, positive_rate_after_cost: 0.6 },
        { cost_bps: 10, median_return_after_cost: -0.1, mean_return_after_cost: -0.1, positive_rate_after_cost: 0.4 },
      ],
    });
    render(<ValidationLab />);
    // The same mocked cohort now feeds both the ad-hoc CohortExplorer and
    // every panel in Signal Research by Event Type, so multiple instances
    // is expected -- assert at least one, not exactly one.
    await waitFor(() => expect(screen.getAllByText(/ESTIMATED COST SENSITIVITY/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/not actual fills/i).length).toBeGreaterThan(0);
  });

  it("shows concentration warnings when present", async () => {
    vi.spyOn(api, "getValidationCohort").mockResolvedValue({
      ...EMPTY_COHORT,
      raw_n: 20,
      median: 1.0,
      concentration_warnings: [
        {
          dimension: "symbol",
          dominant_value: "NVDA",
          share: 0.72,
          warning: "SYMBOL_CONCENTRATION: 72% of this cohort's 20 samples are NVDA",
        },
      ],
    });
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getAllByText(/SYMBOL_CONCENTRATION/).length).toBeGreaterThan(0));
  });

  it("renders a dedicated panel for each Decision Engine event type", async () => {
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getByText("SIGNAL RESEARCH BY EVENT TYPE")).toBeInTheDocument());
    expect(screen.getByText("ENTRY CONDITIONS")).toBeInTheDocument();
    expect(screen.getByText("STRENGTHENING")).toBeInTheDocument();
    expect(screen.getByText("WEAKENING")).toBeInTheDocument();
    expect(screen.getByText("INVALIDATION")).toBeInTheDocument();
    expect(screen.getByText("EXIT")).toBeInTheDocument();
    expect(screen.getByText("CONCENTRATION & CONTRADICTIONS")).toBeInTheDocument();
  });

  it("renders the AI validation summary text from the deterministic backend endpoint", async () => {
    render(<ValidationLab />);
    await waitFor(() => expect(screen.getByText("AI VALIDATION SUMMARY")).toBeInTheDocument());
    expect(screen.getByText(EMPTY_SUMMARY.text)).toBeInTheDocument();
  });
});
