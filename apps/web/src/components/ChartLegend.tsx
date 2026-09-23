"use client";

import { GlossaryHint } from "@/components/GlossaryHint";

/**
 * FINAL TERMINAL POLISH PASS (#2): lightweight-charts markers/labels (BOS,
 * CHOCH, SWEEP, PWH, PWL, HH, HL, LH, LL, MA, RANGE) are drawn on an HTML
 * canvas, not real DOM nodes -- they can't host a hover/click popover
 * directly. This legend strip is the accessible equivalent: one ⓘ per
 * abbreviation actually used on the chart, each backed by the same
 * centralized glossary entry the marker itself represents.
 */
const CHART_LEGEND_TERMS: { abbreviation: string; termId: string }[] = [
  { abbreviation: "BOS", termId: "break-of-structure" },
  { abbreviation: "CHOCH", termId: "change-of-character" },
  { abbreviation: "SWEEP", termId: "liquidity-sweep" },
  { abbreviation: "PWH", termId: "previous-week-high" },
  { abbreviation: "PWL", termId: "previous-week-low" },
  { abbreviation: "HH", termId: "higher-high" },
  { abbreviation: "HL", termId: "higher-low" },
  { abbreviation: "LH", termId: "lower-high" },
  { abbreviation: "LL", termId: "lower-low" },
  { abbreviation: "MA", termId: "moving-average" },
  { abbreviation: "RANGE", termId: "range" },
];

export function ChartLegend() {
  return (
    <div
      aria-label="Chart marker legend"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-2 py-1.5 font-mono text-[10px] text-muted"
    >
      {CHART_LEGEND_TERMS.map(({ abbreviation, termId }) => (
        <GlossaryHint key={termId} termId={termId} label={abbreviation} />
      ))}
    </div>
  );
}
