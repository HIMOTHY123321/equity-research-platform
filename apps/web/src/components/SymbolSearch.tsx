"use client";

import { useEffect, useId, useRef, useState } from "react";

import { useSymbolSearch } from "@/hooks/useSymbolSearch";
import type { SymbolMatch } from "@/lib/types";

/**
 * MARKET UX COMPLETION PASS (#2/#3/#4): one shared ticker + company-name
 * search component, used identically on Overview, Forecast Lab, Research
 * Lab, and Watchlist-add. Selecting a result calls `onSelect` immediately;
 * typing something with zero matches and pressing Enter shows "Symbol not
 * found" and leaves `value` (the last confirmed selection) untouched --
 * this component never silently falls back to any default symbol.
 */
export function SymbolSearch({
  value,
  onSelect,
  watchlistTickers = [],
  placeholder = "Search ticker or company…",
  className = "",
}: {
  /** The currently-confirmed symbol (e.g. from the page's URL state) --
   * shown in the input when the dropdown is closed. */
  value: string;
  onSelect: (ticker: string) => void;
  /** (#3 ranking tier 5) Breaks ties among equally-matched results. */
  watchlistTickers?: string[];
  placeholder?: string;
  className?: string;
}) {
  const [inputValue, setInputValue] = useState(value);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [notFound, setNotFound] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const { results, loading } = useSymbolSearch(isOpen ? inputValue : "", watchlistTickers);

  // Keep the closed-state display in sync with external symbol changes
  // (e.g. browser back/forward, or another component changing `value`).
  // Deferred via setTimeout(0) -- never a synchronous setState call inside
  // the effect body itself.
  useEffect(() => {
    if (isOpen) return;
    const timer = setTimeout(() => setInputValue(value), 0);
    return () => clearTimeout(timer);
  }, [value, isOpen]);

  useEffect(() => {
    const timer = setTimeout(() => setHighlightedIndex(0), 0);
    return () => clearTimeout(timer);
  }, [results]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setInputValue(value);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [value]);

  function select(match: SymbolMatch) {
    setNotFound(null);
    setIsOpen(false);
    setInputValue(match.ticker);
    onSelect(match.ticker);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIsOpen(true);
      setHighlightedIndex((i) => Math.min(i + 1, Math.max(results.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[highlightedIndex]) {
        select(results[highlightedIndex]);
      } else if (inputValue.trim() && !loading) {
        // (#4) No match -- never silently fall back to any default.
        setNotFound(inputValue.trim().toUpperCase());
      }
    } else if (e.key === "Escape") {
      setIsOpen(false);
      setInputValue(value);
      setNotFound(null);
    }
  }

  const showDropdown = isOpen && inputValue.trim().length > 0;

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <input
        type="text"
        role="combobox"
        aria-expanded={showDropdown}
        aria-controls={listboxId}
        aria-autocomplete="list"
        value={inputValue}
        placeholder={placeholder}
        onChange={(e) => {
          setInputValue(e.target.value.toUpperCase());
          setIsOpen(true);
          setNotFound(null);
        }}
        onFocus={() => setIsOpen(true)}
        onKeyDown={handleKeyDown}
        className="w-full rounded border border-border bg-surface-raised px-2 py-1 font-mono text-xs uppercase text-foreground placeholder:normal-case placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
      />
      {showDropdown && (
        <div
          id={listboxId}
          role="listbox"
          className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto rounded border border-border bg-surface shadow-lg"
        >
          {loading && <p className="px-2 py-1.5 text-[11px] text-muted">Searching…</p>}
          {!loading && notFound && (
            <p className="px-2 py-1.5 text-[11px] text-negative">Symbol not found: {notFound}</p>
          )}
          {!loading && !notFound && results.length === 0 && (
            <p className="px-2 py-1.5 text-[11px] text-muted">No matches</p>
          )}
          {!loading &&
            results.map((match, i) => (
              <button
                key={match.ticker}
                type="button"
                role="option"
                aria-selected={i === highlightedIndex}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus so onBlur/outside-click doesn't fire first
                  select(match);
                }}
                onMouseEnter={() => setHighlightedIndex(i)}
                className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs ${
                  i === highlightedIndex ? "bg-accent/15 text-accent" : "text-foreground hover:bg-surface-raised"
                }`}
              >
                <span className="font-mono font-semibold">{match.ticker}</span>
                <span className="truncate text-muted">{match.name}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
