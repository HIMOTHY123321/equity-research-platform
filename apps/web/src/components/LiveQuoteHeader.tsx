"use client";

import { formatAgeSeconds, formatExchangeTimestamp, formatFreshnessLabel, freshnessColorClass, freshnessDotClass } from "@/lib/format";
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import type { Timeframe } from "@/lib/types";

/**
 * Phase 12.1 (#B/#F): the automatically-updating price readout for the
 * currently-viewed ticker -- no refresh button, no manual re-fetch.
 * Subscribes at "viewed" priority (the highest tier) via useLiveSymbol,
 * which shares its single underlying WebSocket subscription with every
 * other live consumer on the page.
 */
export function LiveQuoteHeader({ symbol, timeframe }: { symbol: string; timeframe: Timeframe }) {
  const { quote, connectionState } = useLiveSymbol(symbol, [timeframe]);

  if (!quote) {
    return (
      <span className="flex items-center gap-1.5 text-[11px] text-muted">
        <span className={`h-1.5 w-1.5 rounded-full ${connectionState === "connected" ? "bg-muted" : "bg-negative"}`} />
        {connectionState === "connected" ? "Waiting for live data…" : "Connecting…"}
      </span>
    );
  }

  const freshness = quote.freshness;
  const changeColor = quote.percent_change === null ? "text-muted" : quote.percent_change >= 0 ? "text-positive" : "text-negative";

  return (
    <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
      <span className="text-sm font-semibold text-foreground">{quote.price.toFixed(2)}</span>
      {quote.percent_change !== null && (
        <span className={changeColor}>
          {quote.percent_change >= 0 ? "+" : ""}
          {quote.percent_change.toFixed(2)}%
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${freshnessDotClass(freshness.freshness_state)}`} />
        <span className={freshnessColorClass(freshness.freshness_state)}>
          {formatFreshnessLabel(freshness.freshness_state)}
        </span>
      </span>
      <span className="text-muted" title={freshness.source_timestamp ? formatExchangeTimestamp(freshness.source_timestamp) : undefined}>
        {formatAgeSeconds(freshness.age_seconds)}
      </span>
      <span className="text-muted">via {freshness.provider}</span>
      {quote.is_approximate && <span className="text-muted">(approximate)</span>}
    </div>
  );
}
