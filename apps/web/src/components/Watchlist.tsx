"use client";

import { useEffect, useState, type FormEvent } from "react";

import { ApiError, addWatchlistSymbol, getWatchlist, removeWatchlistSymbol } from "@/lib/api";
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
  const [draft, setDraft] = useState("");
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

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await addWatchlistSymbol(draft.trim());
      setDraft("");
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
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add ticker"
          maxLength={7}
          className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-xs uppercase text-foreground placeholder:text-muted placeholder:normal-case focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          type="submit"
          disabled={submitting}
          className="rounded border border-border px-2 py-1 text-xs text-muted hover:text-foreground disabled:opacity-50"
        >
          Add
        </button>
      </form>

      {actionError && <p className="text-[11px] text-negative">{actionError}</p>}

      {state === "loading" && <p className="text-xs text-muted">Loading watchlist…</p>}
      {state === "error" && <p className="text-xs text-negative">Failed to load watchlist.</p>}
      {state === "ready" && symbols.length === 0 && (
        <p className="text-xs text-muted">Watchlist is empty.</p>
      )}

      <ul className="flex flex-col gap-0.5">
        {symbols.map((s) => (
          <li key={s.ticker} className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => onSelect(s.ticker)}
              className={`flex-1 rounded px-2 py-1 text-left font-mono text-xs transition-colors ${
                s.ticker === selected
                  ? "bg-surface-raised text-foreground"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {s.ticker}
            </button>
            <button
              type="button"
              onClick={() => handleRemove(s.ticker)}
              aria-label={`Remove ${s.ticker}`}
              className="px-2 text-[11px] text-muted hover:text-negative"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
