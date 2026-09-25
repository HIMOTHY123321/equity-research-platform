import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/watchlist",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveSymbol: () => ({ quote: null, candles: {}, connectionState: "connected" }),
  useLiveConnectionState: () => "connected",
  // Phase 14: the TopNav unread-alert badge (useUnreadAlertCount) this page
  // renders, plus the Watchlist sidebar decision-status/monitoring-toggle
  // hooks, all subscribe to this -- a no-op is all this navigation-regression
  // suite needs.
  useLiveGlobalEvent: () => {},
}));
vi.mock("@/hooks/useStreamingActive", () => ({
  useStreamingActive: () => false,
}));

import WatchlistPage from "./page";
import * as api from "@/lib/api";
import type { WatchlistSymbol } from "@/lib/types";

const SYMBOLS: WatchlistSymbol[] = [
  { ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" },
  { ticker: "NVDA", added_at: "2026-01-02T00:00:00Z" },
];

describe("dedicated Watchlist page rows (regression)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockClear();
    vi.spyOn(api, "getWatchlist").mockResolvedValue(SYMBOLS);
    vi.spyOn(api, "getUnreadAlertCount").mockResolvedValue({ count: 0 });
  });

  it("clicking a row navigates to /?symbol=<ticker> via router.push", async () => {
    render(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("link", { name: "Open NVDA on Overview" }));

    expect(pushMock).toHaveBeenCalledWith("/?symbol=NVDA");
  });

  it("Enter/Space on a focused row navigates (keyboard accessible)", async () => {
    render(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    const row = screen.getByRole("link", { name: "Open NVDA on Overview" });
    expect(row).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(row, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/?symbol=NVDA");
  });

  it("clicking the remove button does not navigate", async () => {
    vi.spyOn(api, "removeWatchlistSymbol").mockResolvedValue(undefined);
    render(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Remove NVDA" }));

    expect(pushMock).not.toHaveBeenCalled();
    await waitFor(() => expect(api.removeWatchlistSymbol).toHaveBeenCalledWith("NVDA"));
  });
});
