"use client";

import { useState } from "react";

import { AIResearchAnalystPanel } from "@/components/AIResearchAnalystPanel";
import { AnalogSearchButton } from "@/components/AnalogSearchButton";
import { CatalystContextCard } from "@/components/CatalystContextCard";
import type { AsyncResource } from "@/hooks/useAsyncResource";
import { formatDetectionTime, formatLifecycleState, formatPrice, formatSetupType } from "@/lib/format";
import type { EvidenceCheck, SetupCandidate, SetupDetectionSnapshot } from "@/lib/types";

function StateBadge({ state }: { state: string }) {
  const styles: Record<string, string> = {
    qualified: "bg-positive/15 text-positive",
    triggered: "bg-positive/15 text-positive",
    candidate: "bg-muted/15 text-muted",
    rejected: "bg-negative/15 text-negative",
    invalidated: "bg-negative/15 text-negative",
    expired: "bg-muted/15 text-muted",
  };
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        styles[state] ?? "bg-muted/15 text-muted"
      }`}
    >
      {formatLifecycleState(state)}
    </span>
  );
}

function CheckRow({ check }: { check: EvidenceCheck }) {
  return (
    <div className="flex items-start justify-between gap-2 text-[11px]">
      <span className={check.passed ? "text-positive" : "text-negative"}>
        {check.passed ? "✓" : "✕"} {check.label}
      </span>
      {check.actual !== null && check.required !== null && (
        <span className="whitespace-nowrap font-mono text-muted">
          {check.actual.toFixed(2)} / {check.required.toFixed(2)}
        </span>
      )}
    </div>
  );
}

function EvidenceTree({ candidate }: { candidate: SetupCandidate }) {
  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      {candidate.hard_checks.length > 0 && (
        <div className="space-y-1">
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">HARD REQUIREMENTS</h5>
          {candidate.hard_checks.map((check) => (
            <CheckRow key={check.code} check={check} />
          ))}
        </div>
      )}
      {candidate.soft_checks.length > 0 && (
        <div className="space-y-1">
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">SOFT CONFIRMATION</h5>
          {candidate.soft_checks.map((check) => (
            <CheckRow key={check.code} check={check} />
          ))}
        </div>
      )}
      {candidate.conflicts.length > 0 && (
        <div className="space-y-1">
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">CONFLICTS</h5>
          {candidate.conflicts.map((conflict) => (
            <div key={conflict.code} className="text-[11px] text-warning">
              ⚠ {conflict.label}
            </div>
          ))}
        </div>
      )}
      {candidate.invalidation_criteria.length > 0 && (
        <div className="space-y-1">
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">WOULD INVALIDATE IF</h5>
          {candidate.invalidation_criteria.map((criterion, idx) => (
            <p key={idx} className="text-[11px] text-muted">
              {criterion}
            </p>
          ))}
        </div>
      )}
      {candidate.reference_price !== null && (
        <p className="text-[11px] text-muted">
          Reference: {formatPrice(candidate.reference_price)}
          {candidate.reference_source ? ` (${candidate.reference_source.replace(/_/g, " ")})` : ""}
        </p>
      )}
    </div>
  );
}

function SetupCard({ candidate }: { candidate: SetupCandidate }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="rounded border border-border bg-surface-raised p-3">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-start justify-between gap-2 text-left"
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-foreground">{formatSetupType(candidate.setup_type)}</span>
            <span className={`text-[10px] uppercase ${candidate.direction === "bullish" ? "text-positive" : "text-negative"}`}>
              {candidate.direction}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-muted">
            Detected {formatDetectionTime(candidate.candidate_candle_timestamp, candidate.timeframe)}
            {candidate.reference_price !== null ? ` · ${formatPrice(candidate.reference_price)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StateBadge state={candidate.current_state} />
          <span className="text-[11px] text-muted">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>
      {expanded && (
        <>
          <EvidenceTree candidate={candidate} />
          <CatalystContextCard candidate={candidate} />
          <AnalogSearchButton candidate={candidate} />
          <AIResearchAnalystPanel candidate={candidate} />
        </>
      )}
    </li>
  );
}

function NearMissCard({ candidate }: { candidate: SetupCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const failedHard = candidate.hard_checks.filter((c) => !c.passed);
  return (
    <li className="rounded border border-border bg-surface-raised p-3">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-start justify-between gap-2 text-left"
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-foreground">{candidate.symbol}</span>
            <span className="text-[11px] text-muted">{formatSetupType(candidate.setup_type)}</span>
          </div>
          <p className="mt-0.5 text-[11px] text-negative">
            {failedHard.length > 0
              ? failedHard[0].label
              : candidate.invalidation_reason ?? "Did not qualify"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StateBadge state={candidate.current_state} />
          <span className="text-[11px] text-muted">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1 border-t border-border pt-2">
          {failedHard.map((check) => (
            <div key={check.code} className="text-[11px] text-negative">
              ✕ {check.label}
            </div>
          ))}
          {candidate.hard_checks
            .filter((c) => c.passed)
            .map((check) => (
              <div key={check.code} className="text-[11px] text-positive">
                ✓ {check.label}
              </div>
            ))}
          <CatalystContextCard candidate={candidate} />
          <AnalogSearchButton candidate={candidate} />
          <AIResearchAnalystPanel candidate={candidate} />
        </div>
      )}
    </li>
  );
}

/** Presentational only: fetching lives in useSetups(), owned by MarketWorkspace. */
export function SetupInspectorPanel({ query }: { query: AsyncResource<SetupDetectionSnapshot> }) {
  const { data: snapshot, state, error } = query;

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading setups…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!snapshot) {
    return <div className="p-4 text-xs text-muted">No setup data.</div>;
  }

  if (snapshot.data_quality.status === "unavailable") {
    return (
      <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
        Not enough history yet to evaluate setups ({snapshot.data_quality.candles_consumed} candle(s) available).
      </div>
    );
  }

  const active = [...snapshot.qualified_setups, ...snapshot.candidates];
  const nearMisses = [...snapshot.rejected_candidates, ...snapshot.recently_invalidated];

  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">
          SETUP INTELLIGENCE — {snapshot.symbol}
        </h3>
        {active.length === 0 ? (
          <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
            No qualified setups right now.
          </div>
        ) : (
          <ul className="space-y-2">
            {active.map((candidate) => (
              <SetupCard key={candidate.id} candidate={candidate} />
            ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">NEAR MISSES</h3>
        {nearMisses.length === 0 ? (
          <div className="flex h-12 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
            No rejected candidates right now.
          </div>
        ) : (
          <ul className="space-y-2">
            {nearMisses.map((candidate) => (
              <NearMissCard key={candidate.id} candidate={candidate} />
            ))}
          </ul>
        )}
      </div>

      {snapshot.data_quality.warnings.length > 0 && (
        <p className="text-[11px] text-warning">{snapshot.data_quality.warnings.join(" · ")}</p>
      )}
      <p className="text-[10px] text-muted">{snapshot.data_quality.detectors_run} detector(s) evaluated</p>
    </div>
  );
}
