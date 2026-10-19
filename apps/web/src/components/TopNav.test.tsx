import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentPath = "/";
let currentSearch = "";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
  useRouter: () => ({ push: vi.fn() }),
}));

// Phase 16.1: TopNav now renders account state via useAuth(). Default to
// signed-in for this suite (most tests care about nav items, not auth UI)
// -- signed-out/loading are covered by their own dedicated tests below.
let authState: "loading" | "signed-in" | "signed-out" = "signed-in";
let authUser: { email: string } | null = { email: "trader@example.com" };
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    state: authState,
    user: authUser,
    login: vi.fn(),
    signup: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    refresh: vi.fn(),
  }),
}));

import { TopNav } from "./TopNav";
import * as api from "@/lib/api";

function navLinks() {
  return within(screen.getByRole("navigation")).getAllByRole("link");
}

describe("TopNav (regression: Forecast Lab disappeared)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    authState = "signed-in";
    authUser = { email: "trader@example.com" };
    // Phase 14: the unread-alert-count badge fetches on mount -- mocked so
    // this suite never makes a real network call.
    vi.spyOn(api, "getUnreadAlertCount").mockResolvedValue({ count: 0 });
  });

  it("renders all eleven nav items in order, including Opportunities, Forecast Lab, Scanner, Alerts, Long-Term Research, and Validation Lab", () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    const links = navLinks().map((el) => el.textContent);
    expect(links).toEqual([
      "Overview",
      "Opportunities",
      "Research Lab",
      "Forecast Lab",
      "Reports",
      "Watchlist",
      "Scanner",
      "Alerts",
      "Long-Term Research",
      "Validation Lab",
      "Glossary",
    ]);
  });

  it("carries the current ?symbol= onto every symbol-aware link", () => {
    currentPath = "/";
    currentSearch = "symbol=NVDA";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/?symbol=NVDA");
    expect(screen.getByRole("link", { name: "Research Lab" })).toHaveAttribute("href", "/research?symbol=NVDA");
    expect(screen.getByRole("link", { name: "Forecast Lab" })).toHaveAttribute("href", "/forecasts?symbol=NVDA");
  });

  it("does not carry ?symbol= onto non-symbol-aware links (Reports, Watchlist, Scanner, Alerts, Glossary)", () => {
    currentPath = "/";
    currentSearch = "symbol=NVDA";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
    expect(screen.getByRole("link", { name: "Watchlist" })).toHaveAttribute("href", "/watchlist");
    expect(screen.getByRole("link", { name: "Scanner" })).toHaveAttribute("href", "/scanner");
    expect(screen.getByRole("link", { name: "Alerts" })).toHaveAttribute("href", "/alerts");
    expect(screen.getByRole("link", { name: "Glossary" })).toHaveAttribute("href", "/glossary");
  });

  it("omits ?symbol= entirely when none is present in the URL", () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Forecast Lab" })).toHaveAttribute("href", "/forecasts");
  });

  it("shows the unread alert count badge on the Alerts link when there are unread alerts", async () => {
    vi.spyOn(api, "getUnreadAlertCount").mockResolvedValue({ count: 3 });
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    await waitFor(() => expect(screen.getByRole("link", { name: "Alerts 3" })).toBeInTheDocument());
  });

  it("shows no badge on the Alerts link when there are zero unread alerts", async () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    await waitFor(() => expect(api.getUnreadAlertCount).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
  });

  it("shows the signed-in user's email and a Sign out control (Phase 16.1)", () => {
    render(<TopNav />);
    expect(screen.getByRole("link", { name: "trader@example.com" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("shows a Sign in link, and never fetches unread count, when signed out (Phase 16.1)", () => {
    authState = "signed-out";
    authUser = null;
    render(<TopNav />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(api.getUnreadAlertCount).not.toHaveBeenCalled();
  });
});
