"use client";

import { useState } from "react";

import { formatSignedPercent } from "@/lib/format";
import type { AnalogDiversityReport, AnalogResult } from "@/lib/types";

function AnalogRow({ analog }: { analog: AnalogResult }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="rounded border border-border bg-surface-raised">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px]"
      >
        <span className="flex items-center gap-3">
          <span className="font-mono text-foreground">{analog.symbol}</span>
          <span className="text-muted">{new Date(analog.timestamp).toLocaleString()}</span>
          <span className="text-muted">{analog.setup_type.replace(/_/g, " ")}</span>
          <span className="text-muted">{analog.direction}</span>
        </span>
        <span className="font-mono text-accent">distance {analog.distance.distance.toFixed(3)}</span>
      </button>
      {expanded && (
        <div className="grid grid-cols-1 gap-3 border-t border-border px-3 py-2 text-[11px] sm:grid-cols-3">
          <div>
            <h4 className="mb-1 font-semibold uppercase tracking-wide text-muted">What matched</h4>
            {analog.distance.matched_dimensions.length > 0 ? (
              <ul className="space-y-0.5 text-foreground">
                {analog.distance.matched_dimensions.map((d) => (
                  <li key={d}>{d.replace(/_/g, " ")}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">none</p>
            )}
          </div>
          <div>
            <h4 className="mb-1 font-semibold uppercase tracking-wide text-muted">What differed</h4>
            {analog.distance.differing_dimensions.length > 0 ? (
              <ul className="space-y-0.5 text-foreground">
                {analog.distance.differing_dimensions.map((d) => (
                  <li key={d}>{d.replace(/_/g, " ")}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">none</p>
            )}
            {analog.distance.missing_dimensions.length > 0 && (
              <p className="mt-1 text-muted">
                (missing: {analog.distance.missing_dimensions.map((d) => d.replace(/_/g, " ")).join(", ")})
              </p>
            )}
          </div>
          <div>
            <h4 className="mb-1 font-semibold uppercase tracking-wide text-muted">What happened afterward</h4>
            {analog.outcome ? (
              <ul className="space-y-0.5 text-foreground">
                <li>1-bar: <span className="font-mono">{formatSignedPercent(analog.outcome.one_bar_directional_return_percent)}</span></li>
                <li>5-bar: <span className="font-mono">{formatSignedPercent(analog.outcome.five_bar_directional_return_percent)}</span></li>
                <li>10-bar: <span className="font-mono">{formatSignedPercent(analog.outcome.ten_bar_directional_return_percent)}</span></li>
                <li>MFE: <span className="font-mono text-positive">{analog.outcome.mfe_atr?.toFixed(2) ?? "—"} ATR</span></li>
                <li>MAE: <span className="font-mono text-negative">{analog.outcome.mae_atr?.toFixed(2) ?? "—"} ATR</span></li>
              </ul>
            ) : (
              <p className="text-muted">not evaluated</p>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export function HistoricalAnalogsPanel({
  analogs,
  diversity,
  diverseAnalogs,
}: {
  analogs: AnalogResult[];
  diversity?: AnalogDiversityReport;
  diverseAnalogs?: AnalogResult[];
}) {
  const [showDiverse, setShowDiverse] = useState(false);
  if (analogs.length === 0) {
    return <p className="text-[11px] text-muted">No analogs found in the selected corpus.</p>;
  }
  // (#21) Same distance-sorted list, same underlying similarity calc --
  // toggling only switches which already-computed list is displayed.
  const canShowDiverse = diverseAnalogs !== undefined && diverseAnalogs.length < analogs.length;
  const displayed = showDiverse && diverseAnalogs ? diverseAnalogs : analogs;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">Similar historical setups</h3>
        {canShowDiverse && (
          <button
            type="button"
            onClick={() => setShowDiverse((v) => !v)}
            className="rounded border border-accent px-2 py-0.5 font-mono text-[10px] font-semibold text-accent"
          >
            {showDiverse ? "SHOW ALL ANALOGS" : "SHOW DIVERSE ANALOGS"}
          </button>
        )}
      </div>
      {diversity?.warning && (
        <p className="mb-2 rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1 text-[11px] text-amber-600 dark:text-amber-400">
          {diversity.warning}
        </p>
      )}
      <ul className="space-y-1.5">
        {displayed.map((a) => (
          <AnalogRow key={a.setup_id} analog={a} />
        ))}
      </ul>
    </div>
  );
}
