import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentPath = "/";
let currentSearch = "";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

import { TopNav } from "./TopNav";
import * as api from "@/lib/api";

describe("TopNav (regression: Forecast Lab disappeared)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Phase 14: the unread-alert-count badge fetches on mount -- mocked so
    // this suite never makes a real network call.
    vi.spyOn(api, "getUnreadAlertCount").mockResolvedValue({ count: 0 });
  });

  it("renders all nine nav items in order, including Forecast Lab, Scanner, Alerts, and Validation Lab", () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    const links = screen.getAllByRole("link").map((el) => el.textContent);
    expect(links).toEqual([
      "Overview",
      "Research Lab",
      "Forecast Lab",
      "Reports",
      "Watchlist",
      "Scanner",
      "Alerts",
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
});
