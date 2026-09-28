import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ValidationStatusWidget } from "./ValidationStatusWidget";
import * as api from "@/lib/api";
import type { SignalGateEvaluation } from "@/lib/types";

function evaluation(overrides: Partial<SignalGateEvaluation> = {}): SignalGateEvaluation {
  return {
    gate_version: "1.0",
    decision: "not_enough_data",
    reasons: ["Not enough independent episodes"],
    raw_n: 3,
    independent_episode_count: 3,
    purged_n: 0,
    symbol_count: 2,
    observation_days: 10,
    max_symbol_share: 0.5,
    median_effect: null,
    cost_adjusted_effect_at_max_bps: null,
    criteria: {
      min_independent_episodes: 20,
      min_symbols: 5,
      max_single_symbol_share: 0.4,
      min_observation_days: 30,
    },
    ...overrides,
  } as SignalGateEvaluation;
}

describe("Phase 18 (§21/§22/§77): ValidationStatusWidget", () => {
  it("shows NOT ENOUGH DATA honestly and links to the Validation Lab", async () => {
    vi.spyOn(api, "getSignalGate").mockResolvedValue(evaluation());
    render(<ValidationStatusWidget />);

    await waitFor(() => expect(screen.getByText("NOT ENOUGH DATA")).toBeInTheDocument());
    expect(screen.getByText("Signal Validation Gate")).toBeInTheDocument();
    expect(screen.getByText(/never scoped to a single ticker/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open validation lab/i })).toHaveAttribute("href", "/validation");
  });

  it("never claims the currently-viewed symbol passed the gate", async () => {
    vi.spyOn(api, "getSignalGate").mockResolvedValue(evaluation({ decision: "fail" }));
    render(<ValidationStatusWidget />);

    await waitFor(() => expect(screen.getByText("FAIL")).toBeInTheDocument());
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toMatch(/\bpassed\b/);
  });
});
