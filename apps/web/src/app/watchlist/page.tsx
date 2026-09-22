"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { TopNav } from "@/components/TopNav";
import { useLiveConnectionState, useLiveSymbol } from "@/hooks/useLiveSymbol";
import { useStreamingActive } from "@/hooks/useStreamingActive";
import { useTickingAgeSeconds } from "@/hooks/useTickingAge";
import { ApiError, addWatchlistSymbol, getWatchlist, removeWatchlistSymbol } from "@/lib/api";
import {
  formatAgeSeconds,
  formatExchangeTimestamp,
  formatFreshnessLabel,
  formatSignedPercent,
  freshnessColorClass,
  freshnessDotClass,
} from "@/lib/format";
import type { WatchlistSymbol } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

/**
 * Hardening pass (§18): the WATCHLIST nav item previously went nowhere --
 * this reuses the exact same persistence (app.watchlist) and centralized
 * live subscription layer (useLiveSymbol/liveClient) the sidebar widget
 * already used; every row shares one underlying WebSocket connection, this
 * page never opens a poller per ticker.
 */
export default function WatchlistPage() {
  const [symbols, setSymbols] = useState<WatchlistSymbol[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [actionError, setActionError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const connectionState = useLiveConnectionState();
  const streamingActive = useStreamingActive();

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
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Watchlist</h1>
          <div className="flex items-center gap-1.5 text-[11px] text-muted">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connectionState === "connected" ? "bg-positive" : "bg-negative"
              }`}
            />
            {connectionState === "connected" ? "API connected" : connectionState}
          </div>
        </div>

        <form onSubmit={handleAdd} className="flex max-w-sm gap-2">
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
            className="rounded border border-border px-3 py-1 text-xs text-muted hover:text-foreground disabled:opacity-50"
          >
            Add
          </button>
        </form>

        {actionError && <p className="text-[11px] text-negative">{actionError}</p>}

        <section className="rounded-md border border-border bg-surface">
          {state === "loading" && <p className="p-4 text-xs text-muted">Loading watchlist…</p>}
          {state === "error" && <p className="p-4 text-xs text-negative">Failed to load watchlist.</p>}
          {state === "ready" && symbols.length === 0 && (
            <p className="p-4 text-xs text-muted">
              Watchlist is empty. Add a ticker above to start tracking it.
            </p>
          )}
          {state === "ready" && symbols.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted">
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2">Last Price</th>
                    <th className="px-3 py-2">Change</th>
                    <th className="px-3 py-2">%</th>
                    <th className="px-3 py-2">Market Data</th>
                    <th className="px-3 py-2">Freshness</th>
                    <th className="px-3 py-2">Session</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((s) => (
                    <WatchlistPageRow
                      key={s.ticker}
                      ticker={s.ticker}
                      streamingActive={streamingActive}
                      onRemove={() => handleRemove(s.ticker)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function WatchlistPageRow({
  ticker,
  streamingActive,
  onRemove,
}: {
  ticker: string;
  streamingActive: boolean;
  onRemove: () => void;
}) {
  const router = useRouter();
  const { quote } = useLiveSymbol(ticker, ["1h"], "watchlist");
  const freshness = quote?.freshness;
  const tickingAge = useTickingAgeSeconds(freshness?.source_timestamp ?? null);
  const href = `/?symbol=${ticker}`;

  return (
    <tr
      role="link"
      tabIndex={0}
      aria-label={`Open ${ticker} on Overview`}
      onClick={() => router.push(href)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(href);
        }
      }}
      className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-surface-raised/50 focus-visible:bg-surface-raised/50 focus-visible:outline-none"
    >
      <td className="px-3 py-2">
        <Link href={href} onClick={(e) => e.stopPropagation()} className="font-semibold text-foreground hover:text-accent">
          {ticker}
        </Link>
      </td>
      <td className="px-3 py-2">{quote ? quote.price.toFixed(2) : "—"}</td>
      <td className={`px-3 py-2 ${quote && quote.percent_change !== null ? (quote.percent_change >= 0 ? "text-positive" : "text-negative") : "text-muted"}`}>
        {quote && quote.previous_close !== null
          ? (quote.price - quote.previous_close).toFixed(2)
          : "—"}
      </td>
      <td className={`px-3 py-2 ${quote && quote.percent_change !== null ? (quote.percent_change >= 0 ? "text-positive" : "text-negative") : "text-muted"}`}>
        {quote && quote.percent_change !== null ? formatSignedPercent(quote.percent_change) : "—"}
      </td>
      <td className="px-3 py-2 text-muted">
        {freshness?.source_timestamp ? formatExchangeTimestamp(freshness.source_timestamp) : "—"}
      </td>
      <td className="px-3 py-2">
        {freshness ? (
          <span className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${freshnessDotClass(freshness.freshness_state)}`} />
            <span className={freshnessColorClass(freshness.freshness_state)}>
              {formatFreshnessLabel(freshness.freshness_state, streamingActive)}
            </span>
            <span className="text-muted">{formatAgeSeconds(tickingAge)}</span>
          </span>
        ) : (
          <span className="text-muted">Waiting…</span>
        )}
      </td>
      <td className="px-3 py-2 text-muted uppercase">
        {freshness?.market_session.replace("_", " ") ?? "—"}
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${ticker}`}
          className="text-[11px] text-muted hover:text-negative"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}
