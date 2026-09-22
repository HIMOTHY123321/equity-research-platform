import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { SymbolSearch } from "./SymbolSearch";
import * as api from "@/lib/api";
import type { SymbolMatch } from "@/lib/types";

const NVDA: SymbolMatch = { ticker: "NVDA", name: "NVIDIA Corporation", asset_type: "equity", match_tier: 1 };
const NKE: SymbolMatch = { ticker: "NKE", name: "NIKE, Inc.", asset_type: "equity", match_tier: 2 };

describe("SymbolSearch (#2/#3/#4)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows matching results as the user types", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "NV", results: [NVDA, NKE] });
    const onSelect = vi.fn();
    render(<SymbolSearch value="SPY" onSelect={onSelect} />);

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "NV" } });

    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());
    expect(screen.getByText("NIKE, Inc.")).toBeInTheDocument();
  });

  it("selects a result with mouse click and calls onSelect", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "NV", results: [NVDA] });
    const onSelect = vi.fn();
    render(<SymbolSearch value="SPY" onSelect={onSelect} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "NV" } });
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.mouseDown(screen.getByRole("option", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("keyboard: ArrowDown highlights, Enter selects", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "N", results: [NVDA, NKE] });
    const onSelect = vi.fn();
    render(<SymbolSearch value="SPY" onSelect={onSelect} />);

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "N" } });
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("NKE");
  });

  it("Escape closes the dropdown and reverts to the last confirmed value", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "NV", results: [NVDA] });
    render(<SymbolSearch value="SPY" onSelect={vi.fn()} />);

    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "NV" } });
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("NVDA")).not.toBeInTheDocument());
    expect(input.value).toBe("SPY");
  });

  it("shows a no-matches state when the search returns nothing", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "ZZ", results: [] });
    render(<SymbolSearch value="SPY" onSelect={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ZZ" } });
    await waitFor(() => expect(screen.getByText("No matches")).toBeInTheDocument());
  });

  it("never silently falls back to SPY on an unmatched Enter -- shows 'Symbol not found'", async () => {
    vi.spyOn(api, "searchSymbols").mockResolvedValue({ query: "XYZNOTREAL", results: [] });
    const onSelect = vi.fn();
    render(<SymbolSearch value="SPY" onSelect={onSelect} />);

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "XYZNOTREAL" } });
    await waitFor(() => expect(screen.getByText("No matches")).toBeInTheDocument());

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByText(/Symbol not found/)).toBeInTheDocument());
    expect(onSelect).not.toHaveBeenCalled();
  });
});
