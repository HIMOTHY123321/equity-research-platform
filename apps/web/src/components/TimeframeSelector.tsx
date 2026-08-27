"use client";

import { TIMEFRAMES, type Timeframe } from "@/lib/types";

export function TimeframeSelector({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (timeframe: Timeframe) => void;
}) {
  return (
    <div className="flex gap-1">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => onChange(tf)}
          className={`rounded px-2 py-1 font-mono text-xs transition-colors ${
            tf === value
              ? "bg-accent text-white"
              : "border border-border text-muted hover:text-foreground"
          }`}
        >
          {tf.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
