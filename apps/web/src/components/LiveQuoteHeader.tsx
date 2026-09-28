"use client";

import { GlossaryHint } from "@/components/GlossaryHint";
import {
  formatAgeSeconds,
  formatExchangeTimestamp,
  formatFreshnessLabel,
  formatLiveSession,
  freshnessColorClass,
  freshnessDotClass,
} from "@/lib/format";
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { useStreamingActive } from "@/hooks/useStreamingActive";
import { useTickingAgeSeconds } from "@/hooks/useTickingAge";
import type { Timeframe } from "@/lib/types";

/**
 * Phase 12.1 (#B/#F): the automatically-updating price readout for the
 * currently-viewed ticker -- no refresh button, no manual re-fetch.
 * Subscribes at "viewed" priority (the highest tier) via useLiveSymbol,
 * which shares its single underlying WebSocket subscription with every
 * other live consumer on the page.
 */
export function LiveQuoteHeader({
  symbol,
  timeframe,
  realTimeMode = false,
  monitored,
}: {
  symbol: string;
  timeframe: Timeframe;
  /** (#2) Only ever rendered as active when the caller has ALSO verified
   * `streamingActive` -- this component still re-checks it itself below,
   * since a caller must never be able to force the REAL TIME label onto a
   * polling provider. */
  realTimeMode?: boolean;
  /** Phase 18 (§4/§31): whether this symbol is in the user's monitoring
   * universe -- display-only here (the toggle itself lives in Watchlist/
   * Settings); `undefined` (not yet loaded) renders nothing rather than a
   * misleading "OFF". */
  monitored?: boolean;
}) {
  const { quote, connectionState } = useLiveSymbol(symbol, [timeframe]);
  const streamingActive = useStreamingActive();
  const showRealTime = realTimeMode && streamingActive;
  // (#3) Ticks every second from the fixed source timestamp -- never from
  // the backend's own snapshot `age_seconds`, which only changes between
  // poll/WS messages and would otherwise look frozen for long stretches.
  const tickingAge = useTickingAgeSeconds(quote?.freshness.source_timestamp ?? null);

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
  // Phase 12.2 (#F/#O): last-trade and NBBO carry genuinely independent
  // source timestamps once a streaming provider is active -- shown
  // separately rather than collapsed into one generic "freshness" clock.
  const hasStreamingFields = quote.last_trade_timestamp !== undefined;

  return (
    <div className="flex flex-col gap-1 font-mono text-[11px]">
      {showRealTime && (
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-positive">
          <span className="h-1.5 w-1.5 rounded-full bg-positive" />
          Real Time
        </span>
      )}
      <div className="flex flex-wrap items-center gap-3">
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
            {formatFreshnessLabel(freshness.freshness_state, streamingActive)}
          </span>
          <GlossaryHint termId={streamingActive ? "real-time" : "latest-available"} />
        </span>
        <span className="text-muted" title={freshness.source_timestamp ? formatExchangeTimestamp(freshness.source_timestamp) : undefined}>
          {formatAgeSeconds(tickingAge)}
        </span>
        <span className="text-muted">
          via {freshness.provider}
          {!streamingActive && freshness.provider === "yfinance" ? " development feed" : ""}
        </span>
        {quote.is_approximate && <span className="text-muted">(approximate)</span>}
      </div>
      {/* §4/§5: the underlying MARKET DATA timestamp, always shown
          explicitly -- age/freshness alone can be misread as "just polled"
          rather than "as of this real event". */}
      {freshness.source_timestamp && (
        <div className="text-muted">Last market data: {formatExchangeTimestamp(freshness.source_timestamp)}</div>
      )}
      {hasStreamingFields && (quote.last_trade_timestamp || quote.nbbo_timestamp) && (
        <div className="flex flex-wrap items-center gap-3 text-muted">
          {quote.last_trade_timestamp && (
            <span title="Last trade">Last trade: {formatExchangeTimestamp(quote.last_trade_timestamp)}</span>
          )}
          {quote.nbbo_timestamp && (
            <span className="inline-flex items-center gap-1" title="NBBO quote">
              NBBO: {quote.bid.toFixed(2)} / {quote.ask.toFixed(2)} @ {formatExchangeTimestamp(quote.nbbo_timestamp)}
              <GlossaryHint termId="nbbo" />
            </span>
          )}
        </div>
      )}
      {/* Phase 18 (§4): the always-visible header fields -- bid/ask/spread
          are always present on every LiveQuote (Phase 12.1 schema), never
          gated on a streaming provider; "—" only ever appears if `quote`
          itself is null (handled by the early return above), never here. */}
      <div className="flex flex-wrap items-center gap-3 text-muted">
        <span title="Bid / Ask">
          Bid {quote.bid.toFixed(2)} / Ask {quote.ask.toFixed(2)}
        </span>
        <span className="inline-flex items-center gap-1" title="Spread">
          Spread {quote.spread.toFixed(2)}
          <GlossaryHint termId="spread" />
        </span>
        <span className="inline-flex items-center gap-1">
          Session: {formatLiveSession(freshness.market_session)}
        </span>
        {monitored !== undefined && (
          <span>Monitoring: {monitored ? "ON" : "OFF"}</span>
        )}
      </div>
    </div>
  );
}
