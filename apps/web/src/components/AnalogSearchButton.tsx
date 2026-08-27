"use client";

import { useState } from "react";

import { HistoricalAnalogsPanel } from "@/components/research/HistoricalAnalogsPanel";
import { ApiError, postAnalogQuery, postReplay } from "@/lib/api";
import type { AnalogResult, SetupCandidate, Timeframe } from "@/lib/types";

type Status = "idle" | "running" | "completed" | "failed";

// A short, fast default corpus window so this stays responsive from the
// live dashboard -- the Research Lab's own analog search lets a user pick
// a much larger, already-built corpus when they want a deeper search.
const CORPUS_DAYS = 30;

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
}

export function AnalogSearchButton({ candidate }: { candidate: SetupCandidate }) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [analogs, setAnalogs] = useState<AnalogResult[] | null>(null);

  async function handleClick() {
    if (status === "running") return;
    if (analogs) {
      setAnalogs(null); // collapse if already shown
      return;
    }
    setStatus("running");
    setError(null);
    try {
      const run = await postReplay(
        candidate.symbol,
        candidate.timeframe as Timeframe,
        isoDaysAgo(CORPUS_DAYS),
        isoDaysAgo(0),
      );
      const res = await postAnalogQuery(candidate, [run.id], 10);
      setAnalogs(res.analogs);
      setStatus("completed");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Analog search failed");
      setStatus("failed");
    }
  }

  return (
    <div className="mt-2 border-t border-border pt-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={status === "running"}
        className="rounded border border-accent px-2.5 py-1 font-mono text-[10px] font-semibold text-accent disabled:opacity-50"
      >
        {status === "running"
          ? "SEARCHING…"
          : analogs
            ? "HIDE HISTORICAL ANALOGS"
            : "VIEW HISTORICAL ANALOGS"}
      </button>
      <p className="mt-1 text-[10px] text-muted">
        Searches the last {CORPUS_DAYS} days of {candidate.symbol} for a fast result -- use Research Lab for a
        deeper, larger-corpus search.
      </p>
      {status === "failed" && error && <p className="mt-1 text-[11px] text-negative">{error}</p>}
      {analogs && (
        <div className="mt-2">
          <HistoricalAnalogsPanel analogs={analogs} />
        </div>
      )}
    </div>
  );
}
