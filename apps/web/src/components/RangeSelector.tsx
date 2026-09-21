"use client";

import { RANGE_OPTIONS, type ChartRange } from "@/lib/chartRanges";

/** Separate from TimeframeSelector on purpose (§7): this controls how much
 * history is visible, never the candle duration. */
export function RangeSelector({
  value,
  onChange,
}: {
  value: ChartRange;
  onChange: (range: ChartRange) => void;
}) {
  return (
    <div className="flex gap-1">
      {RANGE_OPTIONS.map((range) => (
        <button
          key={range}
          type="button"
          onClick={() => onChange(range)}
          className={`rounded px-1.5 py-1 font-mono text-[10px] transition-colors ${
            range === value
              ? "bg-accent text-white"
              : "border border-border text-muted hover:text-foreground"
          }`}
        >
          {range}
        </button>
      ))}
    </div>
  );
}
