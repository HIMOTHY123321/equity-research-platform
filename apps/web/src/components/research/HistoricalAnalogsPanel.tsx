"use client";

import { useState } from "react";

import { GlossaryHint } from "@/components/GlossaryHint";
import { formatAnalogTimestamp, formatSignedPercent } from "@/lib/format";
import type { AnalogDiversityReport, AnalogResult } from "@/lib/types";

function AnalogRow({ analog, querySetupType }: { analog: AnalogResult; querySetupType?: string }) {
  const [expanded, setExpanded] = useState(false);
  // (§Q) Feature-based cross-setup analogs can be legitimate similarity
  // matches, but must never be visually indistinguishable from a same-
  // setup-type analog -- the two claims mean different things.
  const isSameSetup = querySetupType !== undefined && analog.setup_type === querySetupType;
  return (
    <li className="rounded border border-border bg-surface-raised">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px]"
      >
        <span className="flex items-center gap-3">
          <span className="font-mono text-foreground">{analog.symbol}</span>
          {/* (§P/#9) The real detection timestamp, exchange-timezone-aware --
              never the browser's own local time. Daily-timeframe entries
              show an honest date-only label instead of a fabricated
              00:00:00 clock time; finer timeframes show the real detection
              time, never silently truncated to a session date. */}
          {(() => {
            const { text, dateOnly } = formatAnalogTimestamp(analog.timestamp, analog.timeframe);
            return (
              <span className="text-muted" title={dateOnly ? "Only a date is stored for this daily-timeframe setup -- no intraday detection time exists." : undefined}>
                {text}
              </span>
            );
          })()}
          <span className="text-muted">{analog.setup_type.replace(/_/g, " ")}</span>
          <span className="text-muted">{analog.direction}</span>
          {querySetupType !== undefined && (
            <span
              className={`rounded px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide ${
                isSameSetup ? "bg-accent/15 text-accent" : "bg-muted/15 text-muted"
              }`}
            >
              {isSameSetup ? "Same setup" : "Cross-setup"}
            </span>
          )}
        </span>
        <span className="flex flex-col items-end">
          <span className="inline-flex items-center gap-1 font-mono text-accent" title="Lower distance = more similar. Normalized across matched feature dimensions -- expand for the contributing dimensions.">
            distance {analog.distance.distance.toFixed(3)}
            <GlossaryHint termId="analog-distance" />
          </span>
          {/* (#11) Visible, not just a hover tooltip -- distance is not a
              probability or confidence score, only a similarity ranking. */}
          <span className="text-[9px] text-muted">Lower = more similar</span>
        </span>
      </button>
      {expanded && (
        <div className="grid grid-cols-1 gap-3 border-t border-border px-3 py-2 text-[11px] sm:grid-cols-3">
          {!isSameSetup && querySetupType !== undefined && (
            <p className="text-muted sm:col-span-3">
              Cross-setup analog: matched on shared feature dimensions (below), not on setup type -- a{" "}
              {analog.setup_type.replace(/_/g, " ")} case being similar to a {querySetupType.replace(/_/g, " ")}{" "}
              query on structure/volatility/RVOL/gap/S-R geometry.
            </p>
          )}
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
                <li>
                  <GlossaryHint termId="maximum-favorable-excursion" label="MFE" />:{" "}
                  <span className="font-mono text-positive">{analog.outcome.mfe_atr?.toFixed(2) ?? "—"} ATR</span>
                </li>
                <li>
                  <GlossaryHint termId="maximum-adverse-excursion" label="MAE" />:{" "}
                  <span className="font-mono text-negative">{analog.outcome.mae_atr?.toFixed(2) ?? "—"} ATR</span>
                </li>
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
  diverseAnalogsDiversity,
  diversityUnavailableReason,
  querySetupType,
}: {
  analogs: AnalogResult[];
  diversity?: AnalogDiversityReport;
  diverseAnalogs?: AnalogResult[];
  /** (#12) Describes `diverseAnalogs`, not `analogs` -- shown instead of
   * `diversity` whenever the diverse list is the one on screen, so the
   * warning always matches the actual displayed row count. */
  diverseAnalogsDiversity?: AnalogDiversityReport;
  /** Hardening pass (§T): when set, the corpus itself can't support a
   * genuinely cross-symbol-diverse result -- shown explicitly rather than
   * silently hiding the diverse-analogs control, which would otherwise
   * look identical to "not requested yet". */
  diversityUnavailableReason?: string | null;
  /** (§Q) The setup type actually being queried against -- lets each row
   * distinguish a same-setup-type analog from a feature-based cross-setup
   * analog rather than presenting both identically. */
  querySetupType?: string;
}) {
  const [showDiverse, setShowDiverse] = useState(false);
  if (analogs.length === 0) {
    return <p className="text-[11px] text-muted">No analogs found in the selected corpus.</p>;
  }
  // (#21) Same distance-sorted list, same underlying similarity calc --
  // toggling only switches which already-computed list is displayed.
  const canShowDiverse = diverseAnalogs !== undefined && diverseAnalogs.length < analogs.length;
  const displayed = showDiverse && diverseAnalogs ? diverseAnalogs : analogs;
  const activeDiversity = showDiverse ? diverseAnalogsDiversity : diversity;

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
      {(showDiverse || !canShowDiverse) && diversityUnavailableReason && (
        <p className="mb-2 rounded border border-border bg-surface-raised px-2 py-1 text-[11px] text-muted">
          {diversityUnavailableReason}
        </p>
      )}
      {activeDiversity?.warning && (
        <p className="mb-2 rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1 text-[11px] text-amber-600 dark:text-amber-400">
          {activeDiversity.warning}
        </p>
      )}
      <ul className="space-y-1.5">
        {displayed.map((a) => (
          <AnalogRow key={a.setup_id} analog={a} querySetupType={querySetupType} />
        ))}
      </ul>
    </div>
  );
}
