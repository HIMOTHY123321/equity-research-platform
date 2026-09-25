"use client";

import { useEffect, useState } from "react";

import { SymbolSearch } from "@/components/SymbolSearch";
import { ApiError, addWatchlistSymbol, getWatchlist, removeWatchlistSymbol } from "@/lib/api";
import { useDecisionScanner } from "@/hooks/useDecisionScanner";
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { useMonitoringSubscriptions } from "@/hooks/useMonitoring";
import { formatSignedPercent, freshnessDotClass } from "@/lib/format";
import type { WatchlistSymbol } from "@/lib/types";

// Compact, non-interactive -- deliberately not the same badge component
// DecisionPlanCard uses (which includes text + a GlossaryHint button);
// this is a plain colored dot so it can never be mistaken for something
// clickable inside a row that already has two real buttons.
const DECISION_DOT_STYLES: Record<string, string> = {
  watching: "bg-accent",
  entry_conditions_met: "bg-positive",
  active_thesis: "bg-positive",
  thesis_strengthening: "bg-positive",
  thesis_weakening: "bg-warning",
  invalidated: "bg-negative",
  exit_conditions_met: "bg-negative",
};

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

      <WatchlistRows symbols={symbols} selected={selected} onSelect={onSelect} onRemove={handleRemove} />
    </div>
  );
}

function WatchlistRows({
  symbols,
  selected,
  onSelect,
  onRemove,
}: {
  symbols: WatchlistSymbol[];
  selected: string;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}) {
  const { rows: scannerRows } = useDecisionScanner();
  const { isMonitored, toggle } = useMonitoringSubscriptions();
  const stateBySymbol = new Map(scannerRows.map((r) => [r.symbol, r.state]));

  return (
    <ul className="flex flex-col gap-0.5">
      {symbols.map((s) => (
        <WatchlistRow
          key={s.ticker}
          ticker={s.ticker}
          selected={s.ticker === selected}
          decisionState={stateBySymbol.get(s.ticker) ?? null}
          monitored={isMonitored(s.ticker)}
          onSelect={() => onSelect(s.ticker)}
          onRemove={() => onRemove(s.ticker)}
          onToggleMonitoring={() => toggle(s.ticker)}
        />
      ))}
    </ul>
  );
}

/** Phase 12.1 (#N): watchlist tickers update automatically without opening
 * each one -- subscribed at "watchlist" priority (below the viewed ticker
 * and any active-forecast symbol, but still live) so a large watchlist
 * never starves the symbol the user is actually looking at. */
function WatchlistRow({
  ticker,
  selected,
  decisionState,
  monitored,
  onSelect,
  onRemove,
  onToggleMonitoring,
}: {
  ticker: string;
  selected: boolean;
  decisionState: string | null;
  monitored: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onToggleMonitoring: () => void;
}) {
  const { quote } = useLiveSymbol(ticker, ["1h"], "watchlist");
  const decisionDotClass = decisionState ? DECISION_DOT_STYLES[decisionState] : null;

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
          {/* Phase 14 §39: compact, non-interactive Decision-state
              indicator -- a plain dot, never text/a badge, so it can never
              be mistaken for a third clickable element inside this row. */}
          {decisionDotClass && (
            <span
              className={`h-1.5 w-1.5 rounded-full ${decisionDotClass}`}
              title={`Decision state: ${decisionState}`}
            />
          )}
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
      {/* Sibling of the select/remove buttons, never nested inside either
          -- clicking it must not navigate or remove the row (§39). */}
      <button
        type="button"
        onClick={onToggleMonitoring}
        aria-label={monitored ? `Stop monitoring ${ticker}` : `Monitor ${ticker} for alerts`}
        aria-pressed={monitored}
        title={monitored ? "Monitoring: on" : "Monitoring: off"}
        className={`px-1 text-[11px] ${monitored ? "text-accent" : "text-muted hover:text-foreground"}`}
      >
        {monitored ? "◉" : "◎"}
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
