"use client";

import { useEffect, useState } from "react";

import { getCatalystEvent, getCatalystReaction, getWatchlist, getWhatsMoving } from "@/lib/api";
import {
  catalystRelevanceColorClass,
  formatCatalystCategory,
  formatCatalystRelevance,
  formatClockTime,
  formatExchangeTimestamp,
  formatRatio,
  formatSignedPercent,
  formatSourceCount,
  percentColorClass,
} from "@/lib/format";
import type { CatalystEvent, CatalystEventDetail, MarketReaction } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

function EventCard({ event }: { event: CatalystEvent }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<CatalystEventDetail | null>(null);
  const [reaction, setReaction] = useState<MarketReaction | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  async function toggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (detail) return; // already fetched once
    setLoadingDetail(true);
    try {
      const [eventDetail, reactionResult] = await Promise.allSettled([
        getCatalystEvent(event.event_id),
        getCatalystReaction(event.event_id, event.affected_symbols[0], "1h"),
      ]);
      if (eventDetail.status === "fulfilled") setDetail(eventDetail.value);
      if (reactionResult.status === "fulfilled") setReaction(reactionResult.value);
    } finally {
      setLoadingDetail(false);
    }
  }

  const oneHourReaction = reaction?.price_horizons.find((h) => h.horizon_bars === 1 && h.available) ?? null;

  return (
    <li className="rounded border border-border bg-surface-raised p-3">
      <button type="button" onClick={toggle} className="flex w-full items-start justify-between gap-2 text-left">
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded bg-muted/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted">
              {formatCatalystCategory(event.category)}
            </span>
            {/* (#14) Relevance is a separate dimension from category -- a
                background/general-investing article must never look like a
                primary market-moving catalyst just because it's listed here. */}
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide ${catalystRelevanceColorClass(event.relevance)}`}
            >
              {formatCatalystRelevance(event.relevance)}
            </span>
            {event.affected_symbols.map((symbol) => (
              <span key={symbol} className="font-mono text-[10px] font-semibold text-foreground">
                {symbol}
              </span>
            ))}
          </div>
          <p className="mt-1 text-xs text-foreground">{event.title}</p>
          <p className="mt-0.5 text-[11px] text-muted">
            {formatClockTime(event.primary_timestamp)} · {formatSourceCount(event.source_count)}
            {event.primary_source ? ` · ${event.primary_source}` : ""}
          </p>
          <p className="text-[10px] text-muted" title="Exact publication timestamp of the anchor article">
            Published {formatExchangeTimestamp(event.earliest_published_at)}
          </p>
        </div>
        <span className="text-[11px] text-muted">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 border-t border-border pt-2">
          {loadingDetail && <p className="text-[11px] text-muted">Loading…</p>}

          {reaction && (
            <div className="flex flex-wrap items-center gap-3 text-[11px]">
              {oneHourReaction && (
                <span className={percentColorClass(oneHourReaction.directional_return_percent)}>
                  1h reaction: {formatSignedPercent(oneHourReaction.directional_return_percent)}
                </span>
              )}
              {reaction.rvol_at_event !== null && <span className="text-muted">RVOL {formatRatio(reaction.rvol_at_event)}</span>}
              <span className="text-muted">{reaction.session_at_event.replace(/_/g, " ")}</span>
            </div>
          )}

          {detail && (
            <ul className="space-y-1">
              {detail.articles.map((article) => (
                <li key={article.article_id} className="text-[11px]">
                  <span className="text-muted">{article.source ?? article.provider}</span>
                  {" — "}
                  {article.url ? (
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {article.headline}
                    </a>
                  ) : (
                    <span className="text-foreground">{article.headline}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/** Self-contained: loads the watchlist, then aggregates catalyst events
 * across it (#K.1) -- no market-wide news endpoint exists (see
 * app/news/yfinance_provider.py's documented limitation), so this is
 * explicitly scoped to symbols the user is already tracking. */
export function WhatsMovingPanel() {
  const [symbols, setSymbols] = useState<string[] | null>(null);
  const [events, setEvents] = useState<CatalystEvent[]>([]);
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const watchlist = await getWatchlist();
        const tickers = watchlist.map((w) => w.ticker);
        if (cancelled) return;
        setSymbols(tickers);
        if (tickers.length === 0) {
          setState("ready");
          return;
        }
        const result = await getWhatsMoving(tickers, 5);
        if (cancelled) return;
        setEvents(result.events);
        setFailures(result.symbols_failed);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading market catalysts…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">Failed to load market catalysts.</div>;
  }
  if (symbols !== null && symbols.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
        Add symbols to your watchlist to see what&apos;s moving them.
      </div>
    );
  }
  if (events.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
        No recent catalyst events for your watchlist.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {events.map((event) => (
          <EventCard key={event.event_id} event={event} />
        ))}
      </ul>
      {Object.keys(failures).length > 0 && (
        <p className="text-[10px] text-muted">
          Could not fetch news for: {Object.keys(failures).join(", ")}
        </p>
      )}
    </div>
  );
}
