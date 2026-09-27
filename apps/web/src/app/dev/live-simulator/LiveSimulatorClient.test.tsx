import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/dev/live-simulator",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveSymbol: () => ({ quote: null, candles: {}, connectionState: "connected" }),
  useLiveConnectionState: () => "connected",
  useLiveGlobalEvent: () => {},
}));
vi.mock("@/hooks/useStreamingActive", () => ({
  useStreamingActive: () => false,
}));

import { ApiError } from "@/lib/api";
import * as api from "@/lib/api";
import { LiveSimulatorClient } from "./LiveSimulatorClient";

describe("Phase 17 (§60/§79/§99): dev live simulator client UI", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an honest 'not enabled' message when the backend 404s", async () => {
    vi.spyOn(api, "getDevSimulatorStatus").mockRejectedValue(new ApiError(404, "Not Found"));

    render(<LiveSimulatorClient />);

    await waitFor(() =>
      expect(screen.getByText(/not enabled on this backend/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Push a trade")).not.toBeInTheDocument();
  });

  it("renders live status and pushes a trade through the API client", async () => {
    vi.spyOn(api, "getDevSimulatorStatus").mockResolvedValue({
      enabled: true,
      connected: true,
      connect_count: 2,
      subscriptions: { SPY: ["trades"] },
    });
    const pushTrade = vi
      .spyOn(api, "pushDevSimulatorTrade")
      .mockResolvedValue({ pushed: true });

    render(<LiveSimulatorClient />);

    await waitFor(() => expect(screen.getByText("Push a trade")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Push trade" }));

    await waitFor(() => expect(pushTrade).toHaveBeenCalledWith("SPY", 100));
  });
});
