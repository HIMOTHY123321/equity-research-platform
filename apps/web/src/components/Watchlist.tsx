"use client";

import { useEffect, useState } from "react";

import { SymbolSearch } from "@/components/SymbolSearch";
import { ApiError, addWatchlistSymbol, getWatchlist, removeWatchlistSymbol } from "@/lib/api";
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { formatSignedPercent, freshnessDotClass } from "@/lib/format";
import type { WatchlistSymbol } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

export function Watchlist({
  selected,
  onSelect,
}: {
  selected: string;
  onSelect: (ticker: string) => void;
}) {
  const [symbols, setSymbols] = useState<WatchlistSymbol[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setState("loading");
    try {
      const data = await getWatchlist();
      setSymbols(data);
      setState("ready");
    } catch {
      setState("error");
    }
  }

  useEffect(() => {
    // load() sets state synchronously before its first await (the standard
    // React data-fetching-effect pattern) — see MarketWorkspace.tsx for the
    // same justification.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  async function handleAdd(ticker: string) {
    setSubmitting(true);
    setActionError(null);
    try {
      await addWatchlistSymbol(ticker);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Failed to add symbol");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(ticker: string) {
    setActionError(null);
    try {
      await removeWatchlistSymbol(ticker);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Failed to remove symbol");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* (#2) Watchlist-add now uses the shared SymbolSearch -- selecting a
          result adds it immediately, never a silent fallback. */}
      <SymbolSearch
        value=""
        onSelect={handleAdd}
        watchlistTickers={symbols.map((s) => s.ticker)}
        placeholder={submitting ? "Adding…" : "Add ticker"}
      />

      {actionError && <p className="text-[11px] text-negative">{actionError}</p>}

      {state === "loading" && <p className="text-xs text-muted">Loading watchlist…</p>}
      {state === "error" && <p className="text-xs text-negative">Failed to load watchlist.</p>}
      {state === "ready" && symbols.length === 0 && (
        <p className="text-xs text-muted">Watchlist is empty.</p>
      )}

      <ul className="flex flex-col gap-0.5">
        {symbols.map((s) => (
          <WatchlistRow
            key={s.ticker}
            ticker={s.ticker}
            selected={s.ticker === selected}
            onSelect={() => onSelect(s.ticker)}
            onRemove={() => handleRemove(s.ticker)}
          />
        ))}
      </ul>
    </div>
  );
}

/** Phase 12.1 (#N): watchlist tickers update automatically without opening
 * each one -- subscribed at "watchlist" priority (below the viewed ticker
 * and any active-forecast symbol, but still live) so a large watchlist
 * never starves the symbol the user is actually looking at. */
function WatchlistRow({
  ticker,
  selected,
  onSelect,
  onRemove,
}: {
  ticker: string;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const { quote } = useLiveSymbol(ticker, ["1h"], "watchlist");

  return (
    <li className="flex items-center justify-between gap-1">
      <button
        type="button"
        onClick={onSelect}
        className={`flex flex-1 items-center justify-between gap-1 rounded px-2 py-1 text-left font-mono text-xs transition-colors ${
          selected ? "bg-surface-raised text-foreground" : "text-muted hover:text-foreground"
        }`}
      >
        <span className="flex items-center gap-1.5">
          {quote && <span className={`h-1.5 w-1.5 rounded-full ${freshnessDotClass(quote.freshness.freshness_state)}`} />}
          {ticker}
        </span>
        {quote && (
          <span className="flex items-center gap-1.5 text-[10px]">
            <span>{quote.price.toFixed(2)}</span>
            {quote.percent_change !== null && (
              <span className={quote.percent_change >= 0 ? "text-positive" : "text-negative"}>
                {formatSignedPercent(quote.percent_change)}
              </span>
            )}
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${ticker}`}
        className="px-2 text-[11px] text-muted hover:text-negative"
      >
        ✕
      </button>
    </li>
  );
}
