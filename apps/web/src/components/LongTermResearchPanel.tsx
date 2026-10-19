"use client";

import { useCallback, useState } from "react";

import { listLongTermResearch, runLongTermScan } from "@/lib/api";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import type { LongTermResearchResult, LongTermResearchState } from "@/lib/types";

const STATE_STYLES: Record<LongTermResearchState, string> = {
  ACCUMULATION_CANDIDATE: "bg-positive/15 text-positive",
  LONG_TERM_THESIS_STRENGTHENING: "bg-positive/15 text-positive",
  HOLDING_THESIS_INTACT: "bg-muted/15 text-muted",
  WATCH_FOR_BETTER_ENTRY: "bg-accent/15 text-accent",
  LONG_TERM_THESIS_WEAKENING: "bg-warning/15 text-warning",
  REVIEW_POSITION: "bg-warning/15 text-warning",
  THESIS_INVALIDATED: "bg-negative/15 text-negative",
  NOT_ENOUGH_EVIDENCE: "bg-muted/15 text-muted",
};

function stateLabel(state: LongTermResearchState): string {
  return state.replace(/_/g, " ");
}

function StateBadge({ state }: { state: LongTermResearchState }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATE_STYLES[state]}`}
    >
      {stateLabel(state)}
    </span>
  );
}

function formatPrice(price: number | null): string {
  return price === null ? "--" : `$${price.toFixed(2)}`;
}

function formatAsOf(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}

function ResearchCard({ result }: { result: LongTermResearchResult }) {
  const { factors } = result;
  return (
    <li className="rounded border border-border bg-surface p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{result.symbol}</span>
          <StateBadge state={result.research_state} />
          {factors.limited_history && (
            <span className="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-warning">
              Limited History
            </span>
          )}
        </div>
        <span className="text-sm font-mono text-foreground">{formatPrice(result.price)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
        <div>
          <div className="text-muted">Business quality</div>
          <div className="text-foreground">{factors.business_quality.replace(/_/g, " ")}</div>
        </div>
        <div>
          <div className="text-muted">Growth</div>
          <div className="text-foreground">{factors.growth.replace(/_/g, " ")}</div>
        </div>
        <div>
          <div className="text-muted">Valuation</div>
          <div className="text-foreground">{factors.valuation.replace(/_/g, " ")}</div>
        </div>
        <div>
          <div className="text-muted">Long-term trend</div>
          <div className="text-foreground">{factors.long_term_trend.replace(/_/g, " ")}</div>
        </div>
      </div>

      {(factors.accumulation_area_low !== null || factors.invalidation_level !== null) && (
        <div className="flex flex-wrap gap-4 text-[11px]">
          {factors.accumulation_area_low !== null && (
            <div>
              <span className="text-muted">Key accumulation area: </span>
              <span className="font-mono text-foreground">
                ${factors.accumulation_area_low.toFixed(2)}-${factors.accumulation_area_high?.toFixed(2)}
              </span>
            </div>
          )}
          {factors.invalidation_level !== null && (
            <div>
              <span className="text-muted">Invalidation level: </span>
              <span className="font-mono text-negative">${factors.invalidation_level.toFixed(2)}</span>
            </div>
          )}
        </div>
      )}

      {result.positive_evidence.length > 0 && (
        <div className="text-[11px]">
          <div className="font-semibold text-positive">Main reasons FOR</div>
          <ul className="ml-4 list-disc text-muted">
            {result.positive_evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {result.negative_evidence.length > 0 && (
        <div className="text-[11px]">
          <div className="font-semibold text-negative">Main reasons AGAINST</div>
          <ul className="ml-4 list-disc text-muted">
            {result.negative_evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {result.contradictions.length > 0 && (
        <div className="text-[11px] text-warning">{result.contradictions.join(" ")}</div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2 text-[10px] text-muted">
        <span>
          Evidence quality: <span className="text-foreground">{result.evidence_quality.replace(/_/g, " ")}</span>
        </span>
        <span>Last updated: {formatAsOf(result.as_of)}</span>
      </div>
    </li>
  );
}

export function LongTermResearchPanel() {
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const fetcher = useCallback(() => listLongTermResearch(), []);
  const { data, state, error } = useAsyncResource(fetcher, [refreshToken]);

  async function handleRunScan() {
    setScanning(true);
    setScanError(null);
    try {
      await runLongTermScan();
      setRefreshToken((token) => token + 1);
    } catch {
      setScanError("Scan failed -- check server logs.");
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button
          onClick={handleRunScan}
          disabled={scanning}
          className="rounded border border-accent bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          {scanning ? "Running scan..." : "RUN LONG-TERM SCAN"}
        </button>
        {scanError && <span className="text-[11px] text-negative">{scanError}</span>}
      </div>

      {state === "loading" && <p className="text-[11px] text-muted">Loading...</p>}
      {state === "error" && <p className="text-[11px] text-negative">{error}</p>}
      {state === "ready" && data && data.length === 0 && (
        <p className="text-[11px] text-muted">
          No long-term research yet for your watchlist. Run a scan to generate one.
        </p>
      )}
      {state === "ready" && data && data.length > 0 && (
        <ul className="space-y-3">
          {data.map((result) => (
            <ResearchCard key={result.symbol} result={result} />
          ))}
        </ul>
      )}
    </div>
  );
}
