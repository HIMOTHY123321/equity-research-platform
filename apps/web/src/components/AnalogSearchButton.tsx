"use client";

import { useState } from "react";

import { HistoricalAnalogsPanel } from "@/components/research/HistoricalAnalogsPanel";
import { ApiError, postAnalogQuery, postReplay, postResearchQuery } from "@/lib/api";
import type {
  AnalogDiversityReport,
  AnalogResult,
  EvidenceQualityFlagKind,
  SetupCandidate,
  Timeframe,
} from "@/lib/types";

// (Phase 9 #29) Deliberately a short allow-list, not "any flag at all" --
// the dashboard stays decision-first, so only the two flags that most
// directly mean "this specific research sample can't be trusted at face
// value" get a pill here; the rest live in the Research Lab's full
// Independence and robustness section.
const DASHBOARD_PILL_FLAGS: EvidenceQualityFlagKind[] = ["high_overlap", "low_independent_sample"];

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

export function AnalogSearchButton({
  candidate,
  includeCatalystContext = false,
  label,
}: {
  candidate: SetupCandidate;
  /** Phase 10 (#I) -- opt in to the analog engine's optional catalyst-context
   * dimensions. Everything else about this component is unchanged. */
  includeCatalystContext?: boolean;
  label?: string;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [analogs, setAnalogs] = useState<AnalogResult[] | null>(null);
  const [diversity, setDiversity] = useState<AnalogDiversityReport | null>(null);
  const [diverseAnalogs, setDiverseAnalogs] = useState<AnalogResult[] | null>(null);
  const [diversityUnavailableReason, setDiversityUnavailableReason] = useState<string | null>(null);
  const [sampleFlags, setSampleFlags] = useState<EvidenceQualityFlagKind[]>([]);

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
      const res = await postAnalogQuery(candidate, [run.id], 10, includeCatalystContext);
      setAnalogs(res.analogs);
      setDiversity(res.diversity);
      setDiverseAnalogs(res.diverse_analogs);
      setDiversityUnavailableReason(res.diversity_unavailable_reason ?? null);

      // (#29) Best-effort only -- this same quick corpus's independence
      // flags for this exact setup type/direction, not a new research pass.
      // A failure here (e.g. too few matching entries) never blocks analogs.
      try {
        const evidence = await postResearchQuery({
          runIds: [run.id],
          setupType: candidate.setup_type,
          direction: candidate.direction,
          horizonBars: 5,
        });
        setSampleFlags(evidence.evidence_card.flags.filter((f) => DASHBOARD_PILL_FLAGS.includes(f)));
      } catch {
        setSampleFlags([]);
      }

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
            ? `HIDE ${label ?? "HISTORICAL ANALOGS"}`
            : (label ?? "VIEW HISTORICAL ANALOGS")}
      </button>
      <p className="mt-1 text-[10px] text-muted">
        Searches the last {CORPUS_DAYS} days of {candidate.symbol} for a fast result -- use Research Lab for a
        deeper, larger-corpus search.
      </p>
      {status === "failed" && error && <p className="mt-1 text-[11px] text-negative">{error}</p>}
      {analogs && sampleFlags.length > 0 && (
        <p className="mt-1.5 inline-block rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-amber-600 dark:text-amber-400">
          research sample highly overlapping
        </p>
      )}
      {analogs && (
        <div className="mt-2">
          <HistoricalAnalogsPanel
            analogs={analogs}
            diversity={diversity ?? undefined}
            diverseAnalogs={diverseAnalogs ?? undefined}
            diversityUnavailableReason={diversityUnavailableReason}
            querySetupType={candidate.setup_type}
          />
        </div>
      )}
    </div>
  );
}
