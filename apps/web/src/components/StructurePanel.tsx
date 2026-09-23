import { GlossaryHint } from "@/components/GlossaryHint";
import { Block, Row } from "@/components/PanelPrimitives";
import type { AsyncResource } from "@/hooks/useAsyncResource";
import {
  capitalize,
  directionColorClass,
  formatPrice,
  formatSwingClassification,
  swingClassificationAbbrev,
} from "@/lib/format";
import type { MarketStructureSnapshot } from "@/lib/types";

function trendColorClass(trend: string): string {
  if (trend === "bullish") return "text-positive";
  if (trend === "bearish") return "text-negative";
  return "text-muted";
}

/** Presentational only: fetching lives in useStructure(), owned by
 * MarketWorkspace, so the same request also feeds the chart's swing/BOS/CHOCH
 * overlay without a second network call. */
export function StructurePanel({ query }: { query: AsyncResource<MarketStructureSnapshot> }) {
  const { data: snapshot, state, error } = query;

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading structure…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!snapshot) {
    return <div className="p-4 text-xs text-muted">No structure data.</div>;
  }

  const { trend, latest_swing_high, latest_swing_low, breaks_of_structure, changes_of_character, active_range, swings, data_quality } =
    snapshot;

  const lastBos = breaks_of_structure.length > 0 ? breaks_of_structure[breaks_of_structure.length - 1] : null;
  const lastChoch = changes_of_character.length > 0 ? changes_of_character[changes_of_character.length - 1] : null;

  const recentEvents = [...swings]
    .filter((s) => s.classification !== null)
    .slice(-8)
    .reverse();

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Block title="TREND">
          <Row
            label="Classification"
            value={capitalize(trend.trend)}
            valueClassName={trendColorClass(trend.trend)}
          />
          <Row label="Strength" value={trend.strength ? capitalize(trend.strength) : "—"} />
        </Block>

        <Block title="LATEST SWING HIGH">
          <Row label="Price" value={latest_swing_high ? formatPrice(latest_swing_high.price) : "—"} />
          <Row
            label="Type"
            value={latest_swing_high ? formatSwingClassification(latest_swing_high.classification) : "—"}
          />
        </Block>

        <Block title="LATEST SWING LOW">
          <Row label="Price" value={latest_swing_low ? formatPrice(latest_swing_low.price) : "—"} />
          <Row
            label="Type"
            value={latest_swing_low ? formatSwingClassification(latest_swing_low.classification) : "—"}
          />
        </Block>

        <Block title={<GlossaryHint termId="break-of-structure" label="Last Break of Structure (BOS)" />}>
          <Row
            label="Event"
            value={lastBos ? `${capitalize(lastBos.direction)} @ ${formatPrice(lastBos.broken_level)}` : "—"}
            valueClassName={lastBos ? directionColorClass(lastBos.direction) : undefined}
          />
        </Block>

        <Block title={<GlossaryHint termId="change-of-character" label="Last Change of Character (CHOCH)" />}>
          <Row
            label="Event"
            value={
              lastChoch ? `${capitalize(lastChoch.direction)} @ ${formatPrice(lastChoch.broken_level)}` : "—"
            }
            valueClassName={lastChoch ? directionColorClass(lastChoch.direction) : undefined}
          />
        </Block>

        <Block title="ACTIVE RANGE">
          <Row
            label="Range"
            value={
              active_range.status === "ok"
                ? `${formatPrice(active_range.low)} – ${formatPrice(active_range.high)}`
                : "—"
            }
          />
          <Row
            label="Position"
            value={active_range.position_percent === null ? "—" : `${active_range.position_percent.toFixed(0)}%`}
          />
        </Block>
      </div>

      {recentEvents.length > 0 && (
        <div className="rounded border border-border bg-surface-raised p-3">
          <h3 className="mb-1.5 text-[11px] font-semibold tracking-wide text-muted">
            RECENT STRUCTURE EVENTS
          </h3>
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-foreground">
            {recentEvents.map((swing) => (
              <span key={`${swing.type}-${swing.pivot_timestamp}`}>
                {swingClassificationAbbrev(swing.classification)} {formatPrice(swing.price)}
              </span>
            ))}
          </div>
        </div>
      )}

      {data_quality.warnings.length > 0 && (
        <p className="text-[11px] text-warning">{data_quality.warnings.join(" · ")}</p>
      )}
      <p className="text-[10px] text-muted">
        {data_quality.confirmed_swing_count} confirmed swing(s) · {data_quality.candidate_swing_count} pending
      </p>
    </div>
  );
}
