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
