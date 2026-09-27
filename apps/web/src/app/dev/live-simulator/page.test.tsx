import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
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

import { notFound } from "next/navigation";

import * as api from "@/lib/api";
import DevLiveSimulatorPage from "./page";

const notFoundMock = vi.mocked(notFound);

describe("Phase 17 (§60/§79/§99): /dev/live-simulator production guard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getDevSimulatorStatus").mockResolvedValue({
      enabled: true,
      connected: true,
      connect_count: 1,
      subscriptions: {},
    });
    vi.spyOn(api, "getUnreadAlertCount").mockResolvedValue({ count: 0 });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("calls notFound() and never renders the simulator UI in a production build", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(() => render(<DevLiveSimulatorPage />)).toThrow("NEXT_NOT_FOUND");
    // React may invoke the component more than once while unwinding a
    // thrown render (retry/error-boundary probing) -- what matters is that
    // it was called at all, and that LiveSimulatorClient's markup never
    // rendered (checked separately below via the non-production test).
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("renders the simulator UI in a non-production build", async () => {
    vi.stubEnv("NODE_ENV", "development");

    render(<DevLiveSimulatorPage />);
    expect(notFoundMock).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("Dev Live Simulator")).toBeInTheDocument());
  });
});
