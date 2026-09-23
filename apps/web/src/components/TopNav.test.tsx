import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let currentPath = "/";
let currentSearch = "";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

import { TopNav } from "./TopNav";

describe("TopNav (regression: Forecast Lab disappeared)", () => {
  it("renders all six nav items in order, including Forecast Lab", () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    const links = screen.getAllByRole("link").map((el) => el.textContent);
    expect(links).toEqual(["Overview", "Research Lab", "Forecast Lab", "Reports", "Watchlist", "Glossary"]);
  });

  it("carries the current ?symbol= onto every symbol-aware link", () => {
    currentPath = "/";
    currentSearch = "symbol=NVDA";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/?symbol=NVDA");
    expect(screen.getByRole("link", { name: "Research Lab" })).toHaveAttribute("href", "/research?symbol=NVDA");
    expect(screen.getByRole("link", { name: "Forecast Lab" })).toHaveAttribute("href", "/forecasts?symbol=NVDA");
  });

  it("does not carry ?symbol= onto non-symbol-aware links (Reports, Watchlist, Glossary)", () => {
    currentPath = "/";
    currentSearch = "symbol=NVDA";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
    expect(screen.getByRole("link", { name: "Watchlist" })).toHaveAttribute("href", "/watchlist");
    expect(screen.getByRole("link", { name: "Glossary" })).toHaveAttribute("href", "/glossary");
  });

  it("omits ?symbol= entirely when none is present in the URL", () => {
    currentPath = "/";
    currentSearch = "";
    render(<TopNav />);

    expect(screen.getByRole("link", { name: "Forecast Lab" })).toHaveAttribute("href", "/forecasts");
  });
});
