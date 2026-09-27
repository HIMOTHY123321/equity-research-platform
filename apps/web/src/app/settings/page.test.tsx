import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/settings",
  useSearchParams: () => new URLSearchParams(),
}));

let authState: "loading" | "signed-in" | "signed-out" = "signed-in";
const logoutMock = vi.fn().mockResolvedValue(undefined);
const USER = {
  id: "u1",
  email: "trader@example.com",
  status: "active",
  role: "user",
  plan: "free",
  timezone: "America/New_York",
  created_at: "2026-01-01T00:00:00Z",
};
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    state: authState,
    user: authState === "signed-in" ? USER : null,
    login: vi.fn(),
    signup: vi.fn(),
    logout: logoutMock,
    refresh: vi.fn(),
  }),
}));

import SettingsPage from "./page";
import * as api from "@/lib/api";

describe("SettingsPage (Phase 16.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockClear();
    logoutMock.mockClear();
    authState = "signed-in";
    vi.spyOn(api, "getMyPlan").mockResolvedValue({ plan: "free", entitlements: [] });
    vi.spyOn(api, "getSystemStatus").mockResolvedValue({
      environment: "development",
      worker_mode: "combined",
      market_data: { provider: "yfinance", is_licensed_commercial_feed: false, development_only_fallback_in_use: true },
      news: { provider: "yfinance", development_only_fallback_in_use: true },
      ai_analysis: { provider: "mock" },
    });
    vi.spyOn(api, "getAlertPreferences").mockResolvedValue([
      { alert_type: "invalidated", enabled: true },
    ]);
    vi.spyOn(api, "listMonitoring").mockResolvedValue([{ symbol: "NVDA", enabled: true, preferred_timeframes: [], decision_monitoring_enabled: true, added_at: "2026-01-01T00:00:00Z" }]);
    vi.spyOn(api, "getLiveStatus").mockResolvedValue({
      capabilities: {
        real_time_quotes: false,
        streaming_quotes: false,
        streaming_trades: false,
        streaming_bars: false,
        streaming_news: false,
        historical_intraday: false,
        quote_delay_seconds: null,
        news_delay_seconds: null,
        min_poll_interval_seconds: 5,
      },
      streaming_active: false,
      real_time_available: false,
      entitlement: { provider: "yfinance", status: "not_entitled", reason: "No streaming implementation." },
      connection_status: { state: "disconnected", last_message_at: null, reconnect_attempts: 0, subscribed_symbols: [] },
      latency: [],
    });
  });

  it("renders the signed-in user's account details", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getAllByText("trader@example.com").length).toBeGreaterThan(0));
  });

  it("clicking Sign out calls logout and redirects to /login", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getAllByText("trader@example.com").length).toBeGreaterThan(0));

    // TopNav also renders a "Sign out" control -- click the Settings
    // page's own Session-section button specifically.
    const signOutButtons = screen.getAllByRole("button", { name: "Sign out" });
    fireEvent.click(signOutButtons[signOutButtons.length - 1]);

    await waitFor(() => expect(logoutMock).toHaveBeenCalled());
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/login"));
  });

  it("shows the current plan and provider status", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText("free")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("yfinance").length).toBeGreaterThan(0));
    expect(screen.getAllByText("development-only fallback").length).toBeGreaterThan(0);
  });

  it("toggling an alert preference calls setAlertPreference with the flipped value", async () => {
    const setPref = vi.spyOn(api, "setAlertPreference").mockResolvedValue({ alert_type: "invalidated", enabled: false } as never);
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("switch", { name: /Invalidated/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("switch", { name: /Invalidated/ }));

    await waitFor(() => expect(setPref).toHaveBeenCalledWith("invalidated", false));
  });

  it("lists monitoring subscriptions independently of Watchlist", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
  });
});
