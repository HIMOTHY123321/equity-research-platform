import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// jsdom has no Next.js app-router context to mount into -- stub the two
// hooks GlossaryPage actually uses so it renders as it would with an empty
// `?term=` query, same approach other client-router-dependent pages in
// this app need under vitest (no app-router provider exists in this test
// environment).
const currentSearch = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(currentSearch),
  usePathname: () => "/glossary",
}));

import GlossaryPage from "./page";

describe("GlossaryPage", () => {
  it("renders every category collapsed by default, with correct counts", () => {
    render(<GlossaryPage />);
    expect(screen.getByRole("heading", { name: "Glossary" })).toBeInTheDocument();
    expect(screen.getByText(/Trading Basics/)).toBeInTheDocument();
    expect(screen.getByText(/Chart & Market Structure/)).toBeInTheDocument();
    // Collapsed: no term detail (e.g. a definition sentence) is in the DOM yet.
    expect(screen.queryByText(/confirmed swing high or low/i)).not.toBeInTheDocument();
  });

  it("expands a category on click, showing its terms alphabetically", () => {
    render(<GlossaryPage />);
    fireEvent.click(screen.getByRole("button", { name: /Chart & Market Structure/ }));

    expect(screen.getByRole("heading", { name: /Break of Structure/, level: 3 })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent ?? "");
    const sorted = [...headings].sort((a, b) => a.localeCompare(b));
    expect(headings).toEqual(sorted);
  });

  it("collapsing a category removes its term details", () => {
    render(<GlossaryPage />);
    const toggle = screen.getByRole("button", { name: /Chart & Market Structure/ });
    fireEvent.click(toggle);
    expect(screen.getByRole("heading", { name: /Break of Structure/, level: 3 })).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByText("Break of Structure (BOS)")).not.toBeInTheDocument();
  });

  it("search matches by abbreviation and shows results instead of categories", () => {
    render(<GlossaryPage />);
    fireEvent.change(screen.getByPlaceholderText("SEARCH TERMS…"), { target: { value: "RVOL" } });

    expect(screen.getByText(/Relative Volume/)).toBeInTheDocument();
    // Category accordion list is replaced by search results.
    expect(screen.queryByRole("button", { name: /Trading Basics/ })).not.toBeInTheDocument();
  });

  it("search matches definition text (bad excursion phrasing) via the centralized glossary lookup", () => {
    render(<GlossaryPage />);
    fireEvent.change(screen.getByPlaceholderText("SEARCH TERMS…"), { target: { value: "excursion" } });

    expect(screen.getByText(/Maximum Favorable Excursion/)).toBeInTheDocument();
    expect(screen.getByText(/Maximum Adverse Excursion/)).toBeInTheDocument();
  });

  it("shows a no-results message for a query matching nothing", () => {
    render(<GlossaryPage />);
    fireEvent.change(screen.getByPlaceholderText("SEARCH TERMS…"), {
      target: { value: "zzz_not_a_real_query_zzz" },
    });
    expect(screen.getByText(/no glossary terms match/i)).toBeInTheDocument();
  });

  it("category toggle button is keyboard accessible (native button semantics, Enter/Space activate)", () => {
    render(<GlossaryPage />);
    const toggle = screen.getByRole("button", { name: /Chart & Market Structure/ });
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
