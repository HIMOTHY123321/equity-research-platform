"use client";

import { useState } from "react";

import { Block, Row } from "@/components/PanelPrimitives";
import type { AsyncResource } from "@/hooks/useAsyncResource";
import { formatBarsAgo, formatPrice, formatSourceLabel, strengthLabel } from "@/lib/format";
import type { SupportResistanceSnapshot, Zone } from "@/lib/types";

function zoneRangeLabel(zone: Zone): string {
  return `${formatPrice(zone.lower_bound)}–${formatPrice(zone.upper_bound)}`;
}

function ZoneSummary({ zone }: { zone: Zone }) {
  const timeframeCount = zone.confluence.timeframe_count;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-sm text-foreground">{zoneRangeLabel(zone)}</span>
        <span
          className={`font-mono text-xs ${
            zone.kind === "resistance" ? "text-negative" : "text-positive"
          }`}
        >
          {strengthLabel(zone.strength.total)} — {zone.strength.total.toFixed(0)}/100
        </span>
      </div>
      {zone.price_relationship && (
        <p className="text-[11px] text-muted">
          {zone.price_relationship.distance_percent.toFixed(1)}% {zone.price_relationship.position.replace("_", " ")}
        </p>
      )}
      {timeframeCount > 1 && (
        <p className="text-[11px] text-muted">
          Confluence: {zone.confluence.source_count} sources across {timeframeCount} timeframes
        </p>
      )}
      <p className="text-[11px] text-muted">
        Independent rejections: {zone.interaction_summary.rejections} · Last tested:{" "}
        {formatBarsAgo(zone.freshness.bars_since_last_touch)}
      </p>
    </div>
  );
}

function WhyThisLevel({ zone }: { zone: Zone }) {
  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      <h4 className="text-[10px] font-semibold tracking-wide text-muted">WHY THIS LEVEL?</h4>
      <div className="space-y-1">
        {zone.evidence.map((entry, idx) => (
          <div key={idx} className="flex items-center justify-between text-[11px]">
            <span className="text-muted">
              {formatSourceLabel(entry.source)} ({entry.source_timeframe})
            </span>
            <span className="font-mono text-foreground">
              {formatPrice(entry.price)} · weight +{entry.weight.toFixed(0)}
            </span>
          </div>
        ))}
      </div>
      <div className="space-y-0.5 border-t border-border pt-1.5 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-muted">Source score</span>
          <span className="font-mono text-foreground">+{zone.strength.source_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted">Confluence score</span>
          <span className="font-mono text-foreground">+{zone.strength.confluence_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted">
            Interactions ({zone.interaction_summary.rejections} rejection(s),{" "}
            {zone.interaction_summary.independent_touches - zone.interaction_summary.rejections} touch(es))
          </span>
          <span className="font-mono text-foreground">+{zone.strength.interaction_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted">Recency</span>
          <span className="font-mono text-foreground">+{zone.strength.recency_score.toFixed(0)}</span>
        </div>
        <div className="flex items-center justify-between font-semibold">
          <span className="text-foreground">Total</span>
          <span className="font-mono text-foreground">{zone.strength.total.toFixed(0)}</span>
        </div>
      </div>
      {zone.lifecycle === "broken" && zone.break_event && (
        <p className="text-[11px] text-warning">
          Broken — closed {zone.break_event.direction === "resistance" ? "above" : "below"} at{" "}
          {formatPrice(zone.break_event.break_price)}
        </p>
      )}
    </div>
  );
}

function ExpandableZoneRow({ zone }: { zone: Zone }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="rounded border border-border bg-surface-raised p-3">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="font-mono text-xs text-foreground">{zoneRangeLabel(zone)}</span>
        <span className="flex items-center gap-2 text-[11px] text-muted">
          <span className="capitalize">{zone.kind}</span>
          <span>{zone.strength.total.toFixed(0)}</span>
          <span>{zone.confluence.source_count} source(s)</span>
          <span>{expanded ? "▲" : "▼"}</span>
        </span>
      </button>
      {expanded && <WhyThisLevel zone={zone} />}
    </li>
  );
}

/** Presentational only: fetching lives in useLevels(), owned by
 * MarketWorkspace, so the same request also feeds the chart's zone overlay. */
export function SupportResistancePanel({ query }: { query: AsyncResource<SupportResistanceSnapshot> }) {
  const { data: snapshot, state, error } = query;

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading levels…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!snapshot) {
    return <div className="p-4 text-xs text-muted">No level data.</div>;
  }

  const { nearest_resistance, nearest_support, active_resistance_zones, active_support_zones, data_quality } =
    snapshot;

  const allActiveZones = [...active_resistance_zones, ...active_support_zones].sort(
    (a, b) => b.strength.total - a.strength.total,
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Block title="NEAREST RESISTANCE">
          {nearest_resistance ? (
            <ZoneSummary zone={nearest_resistance} />
          ) : (
            <Row label="Status" value="unavailable" />
          )}
        </Block>
        <Block title="NEAREST SUPPORT">
          {nearest_support ? <ZoneSummary zone={nearest_support} /> : <Row label="Status" value="unavailable" />}
        </Block>
      </div>

      <div>
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">ACTIVE ZONES</h3>
        {allActiveZones.length === 0 ? (
          <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
            No active zones yet.
          </div>
        ) : (
          <ul className="space-y-2">
            {allActiveZones.map((zone) => (
              <ExpandableZoneRow key={zone.id} zone={zone} />
            ))}
          </ul>
        )}
      </div>

      {data_quality.warnings.length > 0 && (
        <p className="text-[11px] text-warning">{data_quality.warnings.join(" · ")}</p>
      )}
      <p className="text-[10px] text-muted">
        {data_quality.zones_created} zone(s) from {data_quality.raw_levels_generated} raw level(s) ·{" "}
        {data_quality.confirmed_swings_used} confirmed swing(s) used
      </p>
    </div>
  );
}
