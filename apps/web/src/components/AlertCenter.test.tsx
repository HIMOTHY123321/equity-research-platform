import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveGlobalEvent: () => {},
}));

import { AlertCenter } from "./AlertCenter";
import * as api from "@/lib/api";
import type { AlertEvent } from "@/lib/types";

const NOW = "2026-01-01T15:00:00Z";

function makeAlert(overrides: Partial<AlertEvent> = {}): AlertEvent {
  return {
    alert_id: "alert-1",
    symbol: "SPY",
    decision_plan_id: "plan-1",
    setup_id: "setup-1",
    alert_type: "thesis_weakening",
    severity: "important",
    title: "Thesis weakening",
    summary: "A tracked condition flipped to FAILED.",
    previous_state: "active_thesis",
    current_state: "thesis_weakening",
    occurred_at: NOW,
    source_timestamp: null,
    evaluated_at: NOW,
    trigger_condition_ids: [],
    evidence_refs: [],
    transition_id: "transition-1",
    timeframe: "1h",
    setup_type: "range_breakout",
    direction: "bullish",
    research_status: [],
    ranking_gate_status: "fail",
    forward_validation_gate_status: null,
    provider: null,
    data_freshness_state: null,
    dedup_key: "dedup-1",
    origin: "live_prospective",
    schema_version: "1.0",
    pipeline_version: "1.0",
    created_at: NOW,
    ...overrides,
  };
}

describe("AlertCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders every alert from the initial fetch", async () => {
    vi.spyOn(api, "listAlerts").mockResolvedValue([makeAlert()]);

    render(<AlertCenter />);

    await waitFor(() => expect(screen.getByText("Thesis weakening")).toBeInTheDocument());
    expect(screen.getByText("SPY")).toBeInTheDocument();
  });

  it("shows an empty state when there are no alerts", async () => {
    vi.spyOn(api, "listAlerts").mockResolvedValue([]);

    render(<AlertCenter />);

    await waitFor(() => expect(screen.getByText(/no alerts/i)).toBeInTheDocument());
  });

  it("never exposes BUY/SELL language in an alert card", async () => {
    vi.spyOn(api, "listAlerts").mockResolvedValue([makeAlert({ summary: "Invalidation condition triggered." })]);

    render(<AlertCenter />);

    await waitFor(() => expect(screen.getByText("Invalidation condition triggered.")).toBeInTheDocument());
    expect(screen.queryByText(/\bbuy\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bsell\b/i)).not.toBeInTheDocument();
  });

  it("clicking 'Mark as read' acknowledges the alert and removes the unread indicator", async () => {
    vi.spyOn(api, "listAlerts").mockImplementation((params) =>
      Promise.resolve(params?.unreadOnly ? [makeAlert()] : [makeAlert()]),
    );
    vi.spyOn(api, "acknowledgeAlert").mockResolvedValue(undefined);

    render(<AlertCenter />);
    await waitFor(() => expect(screen.getByText("Mark as read")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Mark as read"));

    await waitFor(() => expect(api.acknowledgeAlert).toHaveBeenCalledWith("alert-1"));
    await waitFor(() => expect(screen.queryByText("Mark as read")).not.toBeInTheDocument());
  });

  it("clicking 'Mark all as read' calls acknowledgeAllAlerts and clears unread state", async () => {
    vi.spyOn(api, "listAlerts").mockImplementation((params) =>
      Promise.resolve(params?.unreadOnly ? [makeAlert(), makeAlert({ alert_id: "alert-2", dedup_key: "dedup-2" })] : [
        makeAlert(),
        makeAlert({ alert_id: "alert-2", dedup_key: "dedup-2" }),
      ]),
    );
    vi.spyOn(api, "acknowledgeAllAlerts").mockResolvedValue({ acknowledged: 2 });

    render(<AlertCenter />);
    await waitFor(() => expect(screen.getByText("Mark all as read")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Mark all as read"));

    await waitFor(() => expect(api.acknowledgeAllAlerts).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Mark all as read")).not.toBeInTheDocument());
  });

  it("switching to the Unread filter shows only unread alerts", async () => {
    const readAlert = makeAlert({ alert_id: "alert-read", dedup_key: "dedup-read", title: "Already read" });
    const unreadAlert = makeAlert({ alert_id: "alert-unread", dedup_key: "dedup-unread", title: "Still unread" });
    vi.spyOn(api, "listAlerts").mockImplementation((params) =>
      Promise.resolve(params?.unreadOnly ? [unreadAlert] : [readAlert, unreadAlert]),
    );

    render(<AlertCenter />);
    await waitFor(() => expect(screen.getByText("Already read")).toBeInTheDocument());
    expect(screen.getByText("Still unread")).toBeInTheDocument();

    fireEvent.click(screen.getByText(/^Unread/));

    await waitFor(() => expect(screen.queryByText("Already read")).not.toBeInTheDocument());
    expect(screen.getByText("Still unread")).toBeInTheDocument();
  });

  it("filtering by Critical only calls the API with severity=critical", async () => {
    const spy = vi.spyOn(api, "listAlerts").mockResolvedValue([]);

    render(<AlertCenter />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Critical"));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ severity: "critical" })),
    );
  });
});
