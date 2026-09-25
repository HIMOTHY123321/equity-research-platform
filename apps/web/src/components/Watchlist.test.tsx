import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Watchlist rows subscribe to live quotes via useLiveSymbol, which opens a
// real WebSocket through the liveClient singleton -- irrelevant to what
// this test verifies (row click -> onSelect, remove button isolation,
// selected-row styling) and a source of test flakiness/hangs if left
// real, so it's mocked to a stable "no live data yet" shape.
vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveSymbol: () => ({ quote: null, candles: {}, connectionState: "connected" }),
  // Phase 14: useDecisionScanner/useMonitoringSubscriptions (Decision-state
  // dot + monitoring toggle) subscribe to this -- a no-op is all this
  // click/remove-isolation suite needs.
  useLiveGlobalEvent: () => {},
}));

import { Watchlist } from "./Watchlist";
import * as api from "@/lib/api";
import type { WatchlistSymbol } from "@/lib/types";

const SYMBOLS: WatchlistSymbol[] = [
  { ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" },
  { ticker: "NVDA", added_at: "2026-01-02T00:00:00Z" },
  { ticker: "SPY", added_at: "2026-01-03T00:00:00Z" },
];

describe("Watchlist (sidebar)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getWatchlist").mockResolvedValue(SYMBOLS);
    // Phase 14: each row now also reads Decision Scanner state and
    // monitoring-toggle state -- mocked so this suite never makes a real
    // network call (both hooks are exercised on their own elsewhere).
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue([]);
    vi.spyOn(api, "listMonitoring").mockResolvedValue([]);
  });

  it("renders every ticker as an entire clickable row", async () => {
    render(<Watchlist selected="SPY" onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    // The whole row is a single <button> -- native pointer cursor, native
    // keyboard activation (Enter/Space), no extra wiring needed.
    const row = screen.getByText("NVDA").closest("button");
    expect(row).not.toBeNull();
    expect(row?.tagName).toBe("BUTTON");
  });

  it("clicking a ticker row calls onSelect with that exact ticker (regression: rows must stay clickable)", async () => {
    const onSelect = vi.fn();
    render(<Watchlist selected="SPY" onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByText("NVDA").closest("button")!);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("clicking the remove (X) button does NOT call onSelect / navigate", async () => {
    const onSelect = vi.fn();
    vi.spyOn(api, "removeWatchlistSymbol").mockResolvedValue(undefined);
    render(<Watchlist selected="SPY" onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Remove NVDA" }));

    expect(onSelect).not.toHaveBeenCalled();
    await waitFor(() => expect(api.removeWatchlistSymbol).toHaveBeenCalledWith("NVDA"));
  });

  it("visibly highlights the selected symbol's row and not the others", async () => {
    render(<Watchlist selected="NVDA" onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    const nvdaRow = screen.getByText("NVDA").closest("button")!;
    const aaplRow = screen.getByText("AAPL").closest("button")!;
    expect(nvdaRow.className).toMatch(/bg-surface-raised/);
    expect(aaplRow.className).not.toMatch(/bg-surface-raised/);
  });

  it("clicking the monitoring toggle does NOT call onSelect or remove the symbol (Phase 14 §39)", async () => {
    const onSelect = vi.fn();
    vi.spyOn(api, "removeWatchlistSymbol").mockResolvedValue(undefined);
    vi.spyOn(api, "enableMonitoring").mockResolvedValue({
      symbol: "NVDA",
      enabled: true,
      preferred_timeframes: [],
      decision_monitoring_enabled: true,
      added_at: "2026-01-01T00:00:00Z",
    });
    render(<Watchlist selected="SPY" onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Monitor NVDA for alerts" }));

    expect(onSelect).not.toHaveBeenCalled();
    expect(api.removeWatchlistSymbol).not.toHaveBeenCalled();
    await waitFor(() => expect(api.enableMonitoring).toHaveBeenCalledWith("NVDA"));
  });

  it("row is keyboard accessible (native <button> semantics -- focusable, Enter/Space-activatable)", async () => {
    const onSelect = vi.fn();
    render(<Watchlist selected="SPY" onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    const row = screen.getByText("NVDA").closest("button")!;
    expect(row.tagName).toBe("BUTTON");
    expect(row).not.toHaveAttribute("tabindex", "-1");

    // Native <button> converts Enter/Space key presses into a click event
    // automatically in a real browser -- exercised directly here since
    // jsdom doesn't synthesize that translation itself.
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });
});
