"use client";

import { useState, type ReactNode } from "react";

import type { AsyncResource } from "@/hooks/useAsyncResource";
import { getCatalystReaction } from "@/lib/api";
import {
  formatCatalystCategory,
  formatClockTime,
  formatRatio,
  formatSignedPercent,
  formatSourceCount,
  percentColorClass,
} from "@/lib/format";
import type { CatalystEvent, MarketReaction, SetupCandidate, Timeframe } from "@/lib/types";

const MS_PER_HOUR = 3_600_000;
const SETUP_LINK_WINDOW_HOURS = 72;

function TimelineStep({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="w-16 shrink-0 text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <div className="text-[11px] text-foreground">{children}</div>
    </div>
  );
}

function TimelineItem({
  event,
  symbol,
  timeframe,
  nearbySetups,
}: {
  event: CatalystEvent;
  symbol: string;
  timeframe: Timeframe;
  nearbySetups: SetupCandidate[];
}) {
  const [reaction, setReaction] = useState<MarketReaction | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (reaction) return;
    setLoading(true);
    try {
      setReaction(await getCatalystReaction(event.event_id, symbol, timeframe));
    } catch {
      // best-effort -- the timeline still shows the catalyst itself
    } finally {
      setLoading(false);
    }
  }

  const oneHour = reaction?.price_horizons.find((h) => h.horizon_bars === 1 && h.available) ?? null;
  const latest = reaction?.price_horizons.filter((h) => h.available).slice(-1)[0] ?? null;

  return (
    <li className="relative border-l border-border pl-4">
      <span className="absolute -left-[5px] top-1 h-2 w-2 rounded-full bg-accent" />
      <button type="button" onClick={toggle} className="flex w-full items-start justify-between gap-2 text-left">
        <div>
          <div className="flex items-center gap-1.5">
            <span className="rounded bg-muted/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted">
              {formatCatalystCategory(event.category)}
            </span>
            <span className="text-[11px] text-muted">
              {formatClockTime(event.primary_timestamp)} · {formatSourceCount(event.source_count)}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-foreground">{event.title}</p>
        </div>
        <span className="text-[11px] text-muted">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5 border-t border-border pt-2">
          <TimelineStep label="Catalyst">
            {formatCatalystCategory(event.category)} · {formatSourceCount(event.source_count)}
          </TimelineStep>
          <TimelineStep label="Price">
            {loading && "Loading…"}
            {!loading && oneHour && (
              <span className={percentColorClass(oneHour.directional_return_percent)}>
                1h: {formatSignedPercent(oneHour.directional_return_percent)}
              </span>
            )}
            {!loading && latest && latest !== oneHour && (
              <span className={`ml-2 ${percentColorClass(latest.directional_return_percent)}`}>
                {latest.horizon_bars}-bar: {formatSignedPercent(latest.directional_return_percent)}
              </span>
            )}
            {!loading && !oneHour && "No reaction data available"}
          </TimelineStep>
          <TimelineStep label="Volume">
            {!loading && reaction?.rvol_at_event !== undefined && reaction?.rvol_at_event !== null
              ? `RVOL ${formatRatio(reaction.rvol_at_event)}`
              : !loading && "—"}
          </TimelineStep>
          <TimelineStep label="Structure">
            {reaction?.structure_state_at_event ?? "—"}
            {reaction?.bos_after_event && " · BOS after"}
            {reaction?.choch_after_event && " · CHOCH after"}
          </TimelineStep>
          <TimelineStep label="Setups">
            {nearbySetups.length === 0
              ? "No setup formed within 72h"
              : `${nearbySetups.length} setup(s) formed within 72h`}
          </TimelineStep>
        </div>
      )}
    </li>
  );
}

/**
 * Catalyst → price reaction → volume reaction → structure change → setup
 * formation, in chronological order (#K.2) -- fetching lives in
 * useSymbolCatalysts(), owned by MarketWorkspace, same convention as every
 * other panel in this workspace.
 */
export function SymbolCatalystTimeline({
  query,
  symbol,
  timeframe,
  setups,
}: {
  query: AsyncResource<CatalystEvent[]>;
  symbol: string;
  timeframe: Timeframe;
  setups: SetupCandidate[];
}) {
  const { data: events, state, error } = query;

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading catalyst timeline…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!events || events.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
        No recent catalysts found for {symbol}.
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {events.map((event) => {
        const eventTime = new Date(event.primary_timestamp).getTime();
        const nearbySetups = setups.filter((s) => {
          const setupTime = new Date(s.candidate_candle_timestamp).getTime();
          const deltaHours = (setupTime - eventTime) / MS_PER_HOUR;
          return deltaHours >= 0 && deltaHours <= SETUP_LINK_WINDOW_HOURS;
        });
        return (
          <TimelineItem
            key={event.event_id}
            event={event}
            symbol={symbol}
            timeframe={timeframe}
            nearbySetups={nearbySetups}
          />
        );
      })}
    </ul>
  );
}
