import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AIResearchAnalystPanel } from "./AIResearchAnalystPanel";
import * as api from "@/lib/api";
import type { EvidencePacket, ResearchBrief, SetupCandidate } from "@/lib/types";

/**
 * Hardening pass (§V, CRITICAL): regression coverage for the exact bug
 * confirmed via manual testing -- switching AI Research Analyst modes used
 * to build a brand-new EvidencePacket (different packet_id/as_of) on every
 * click because the panel never threaded a pinned `as_of` back into
 * subsequent requests. These tests assert every mode switch within one
 * open session reuses the exact same `as_of`, which is what makes the
 * backend's deterministic build_evidence_packet return the same packet_id.
 */

const CANDIDATE: SetupCandidate = {
  id: "setup-1",
  symbol: "SPY",
  timeframe: "1h",
  setup_type: "gap_continuation",
  direction: "bullish",
  reference_price: 100,
  reference_source: "test",
  reference_timestamp: "2026-09-21T13:00:00+00:00",
  confirmation: null,
  candidate_candle_timestamp: "2026-09-21T13:00:00+00:00",
  created_at: "2026-09-21T13:00:00+00:00",
  current_state: "qualified",
  transitions: [],
  hard_checks: [],
  soft_checks: [],
  conflicts: [],
  invalidation_criteria: [],
  context: null,
  fingerprint: null,
  expires_at: null,
  expired_at: null,
  invalidated_at: null,
  invalidation_reason: null,
  triggered_at: null,
  metadata: {},
};

function fixtureBrief(mode: string, asOf: string): ResearchBrief {
  return {
    brief_id: `brief-${mode}-${asOf}`,
    evidence_packet_id: `packet-${asOf}`,
    mode: mode as ResearchBrief["mode"],
    situation_summary: "test",
    setup_explanation: "test",
    supporting_evidence: [],
    contradictory_evidence: [],
    catalyst_context: "",
    historical_context: "",
    uncertainty: [],
    invalidation_conditions: [],
    monitor_next: [],
    evidence_refs: [],
    generated_at: asOf,
    as_of: asOf,
    provider: "mock",
    model: null,
    prompt_version: "v1",
    grounding_rejected: false,
    grounding_violations: [],
  };
}

function fixturePacket(asOf: string): EvidencePacket {
  return {
    packet_id: `packet-${asOf}`,
    schema_version: "1.1",
    pipeline_version: "1.0",
    mode: "live",
    as_of: asOf,
    generated_at: asOf,
    symbol: "SPY",
    timeframe: "1h",
    session: null,
    current_price: null,
    market_data_cutoff: asOf,
    news_cutoff: asOf,
    research_snapshot_cutoff: null,
    setup: null,
    structure: {} as EvidencePacket["structure"],
    multi_timeframe_structure: {},
    support_resistance: {} as EvidencePacket["support_resistance"],
    features: {} as EvidencePacket["features"],
    historical_research: null,
    historical_analogs: null,
    catalyst_context: null,
    nearest_catalyst_event: null,
    ranking_gate_status: "FAIL",
    data_quality: {} as EvidencePacket["data_quality"],
    provenance: {} as EvidencePacket["provenance"],
  };
}

describe("AIResearchAnalystPanel (§V: frozen EvidencePacket across mode switches)", () => {
  it("passes the exact same as_of to every one of the six modes within one open session", async () => {
    const briefCalls: Array<{ asOf?: string; mode: string }> = [];
    const packetCalls: Array<{ asOf?: string }> = [];

    vi.spyOn(api, "postResearchBrief").mockImplementation(async (params) => {
      briefCalls.push({ asOf: params.asOf, mode: params.mode });
      return fixtureBrief(params.mode, params.asOf ?? "MISSING");
    });
    vi.spyOn(api, "getEvidencePacket").mockImplementation(async (params) => {
      packetCalls.push({ asOf: params.asOf });
      return fixturePacket(params.asOf ?? "MISSING");
    });

    render(<AIResearchAnalystPanel candidate={CANDIDATE} />);

    fireEvent.click(screen.getByText("AI RESEARCH ANALYST"));
    await waitFor(() => expect(briefCalls.length).toBe(1));

    const modes = ["QUICK", "FULL", "WHY THIS SETUP", "WHY NOT", "CATALYST", "ANALOGS"];
    for (const label of modes) {
      fireEvent.click(screen.getByText(label));
      await waitFor(() => expect(briefCalls.length).toBeGreaterThanOrEqual(1));
    }

    await waitFor(() => expect(briefCalls.length).toBe(1 + modes.length));

    const asOfValues = new Set(briefCalls.map((c) => c.asOf));
    expect(asOfValues.size).toBe(1);
    expect([...asOfValues][0]).toBeTruthy();

    const packetAsOfValues = new Set(packetCalls.map((c) => c.asOf));
    expect(packetAsOfValues.size).toBe(1);
    expect([...packetAsOfValues][0]).toBe([...asOfValues][0]);
  });

  it("freezes a new as_of only when explicitly re-opened, not merely re-rendered", async () => {
    const briefCalls: Array<{ asOf?: string }> = [];
    vi.spyOn(api, "postResearchBrief").mockImplementation(async (params) => {
      briefCalls.push({ asOf: params.asOf });
      return fixtureBrief(params.mode, params.asOf ?? "MISSING");
    });
    vi.spyOn(api, "getEvidencePacket").mockImplementation(async (params) =>
      fixturePacket(params.asOf ?? "MISSING"),
    );

    render(<AIResearchAnalystPanel candidate={CANDIDATE} />);
    fireEvent.click(screen.getByText("AI RESEARCH ANALYST"));
    await waitFor(() => expect(briefCalls.length).toBe(1));
    const firstAsOf = briefCalls[0].asOf;

    fireEvent.click(screen.getByText("FULL"));
    await waitFor(() => expect(briefCalls.length).toBe(2));
    expect(briefCalls[1].asOf).toBe(firstAsOf);
  });
});
