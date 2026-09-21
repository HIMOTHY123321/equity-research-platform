"use client";

import { useState } from "react";

import { ResearchResultsPanel } from "@/components/research/ResearchResultsPanel";
import { ApiError, postCatalystResearchQuery } from "@/lib/api";
import {
  deriveEvidenceStateBadges,
  evidenceStateBadgeColorClass,
  formatCatalystCategory,
  formatSignedPercent,
} from "@/lib/format";
import type { CatalystResearchQueryResponse, ConclusionStabilityReport } from "@/lib/types";

type AsyncStatus = "idle" | "running" | "completed" | "failed";

// Every category app.news.schemas.CatalystCategory defines -- kept as a
// plain literal list here (not derived from a TS union at runtime) since
// this is display-only; app/news/schemas.py::CatalystCategory remains the
// single source of truth for what the backend actually accepts.
const CATALYST_CATEGORIES = [
  "earnings", "earnings_preannouncement", "guidance", "analyst_rating", "price_target",
  "product_launch", "product_issue", "regulatory", "legal_lawsuit", "merger_acquisition",
  "financing_capital_raise", "buyback", "dividend", "management_change", "filing",
  "macroeconomic", "federal_reserve", "interest_rates", "inflation", "employment",
  "geopolitical", "supply_chain", "sector_industry", "company_specific_other", "unknown",
];

function ConclusionStabilityTable({ report }: { report: ConclusionStabilityReport }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        <span className="text-[11px] font-semibold text-foreground">{report.finding_label}</span>
        <span className="rounded bg-border px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted">
          {report.label.replace(/_/g, " ")}
        </span>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-muted">
            <th className="text-left font-normal">Level</th>
            <th className="text-right font-normal">{report.raw.group_a_label}</th>
            <th className="text-right font-normal">{report.raw.group_b_label}</th>
            <th className="text-right font-normal">Difference</th>
          </tr>
        </thead>
        <tbody>
          {(["raw", "episode", "purged"] as const).map((level) => {
            const c = report[level];
            return (
              <tr key={level}>
                <td className="py-0.5 pr-3 font-mono text-[11px] capitalize text-muted">{level}</td>
                <td className="py-0.5 pr-3 text-right font-mono text-[11px] text-foreground">
                  {formatSignedPercent(c.group_a_distribution.median)}{" "}
                  <span className="text-[10px] text-muted">n={c.group_a_distribution.n}</span>
                </td>
                <td className="py-0.5 pr-3 text-right font-mono text-[11px] text-foreground">
                  {formatSignedPercent(c.group_b_distribution.median)}{" "}
                  <span className="text-[10px] text-muted">n={c.group_b_distribution.n}</span>
                </td>
                <td className="py-0.5 text-right font-mono text-[11px] text-foreground">
                  {formatSignedPercent(c.median_difference)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-[10px] text-muted">{report.label_basis}</p>
    </div>
  );
}

export function CatalystResearchPanel({ runIds }: { runIds: string[] }) {
  const [setupType, setSetupType] = useState("");
  const [direction, setDirection] = useState("");
  const [qualificationState, setQualificationState] = useState("");
  const [horizonBars, setHorizonBars] = useState(5);
  const [catalystCategory, setCatalystCategory] = useState("");
  const [requireCatalyst, setRequireCatalyst] = useState(false);
  const [maxHoursSince, setMaxHoursSince] = useState("");
  const [rvolElevated, setRvolElevated] = useState<"" | "true" | "false">("");
  const [compareToNoCatalyst, setCompareToNoCatalyst] = useState(false);

  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CatalystResearchQueryResponse | null>(null);

  // (§AG) A "compare vs. baseline" request only produces a meaningfully
  // distinct comparison cohort when at least one catalyst constraint is
  // actually applied -- otherwise the "filtered" and "unfiltered" groups
  // are the same underlying set.
  const hasCatalystConstraint =
    requireCatalyst || catalystCategory !== "" || maxHoursSince !== "" || rvolElevated !== "";

  async function handleQuery(e: React.FormEvent) {
    e.preventDefault();
    if (runIds.length === 0) {
      setError("Run a replay (single-symbol or universe) first.");
      setStatus("failed");
      return;
    }
    setStatus("running");
    setError(null);
    try {
      const res = await postCatalystResearchQuery({
        runIds,
        setupType: setupType || undefined,
        direction: direction || undefined,
        qualificationState: qualificationState || undefined,
        horizonBars,
        requireCatalyst,
        catalystCategory: catalystCategory || undefined,
        catalystMaxHoursSince: maxHoursSince ? Number(maxHoursSince) : undefined,
        catalystRvolElevated: rvolElevated === "" ? undefined : rvolElevated === "true",
        compareToNoCatalyst: compareToNoCatalyst && hasCatalystConstraint,
      });
      setResult(res);
      setStatus("completed");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Catalyst research query failed");
      setStatus("failed");
    }
  }

  const badges = result
    ? deriveEvidenceStateBadges({
        evidence_maturity: result.independence.evidence_maturity,
        flags: result.evidence_card.flags,
        walk_forward_stability: result.independence.walk_forward.stability,
        temporal_stability: result.temporal_stability.stability,
        concentration_warning_count: result.concentration.warnings.length,
        overlap_warning: result.overlap.warning,
        contradiction_statuses: result.contradictions.map((c) => c.status),
        conclusion_stability_label: result.independence.conclusion_stability?.label ?? null,
      })
    : [];

  return (
    <section className="space-y-3 rounded-md border border-border bg-surface p-4">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Catalyst research</h2>
        <p className="mt-0.5 text-[11px] text-muted">
          Study a catalyst-filtered cohort (e.g. earnings + breakout_retest, or catalyst-present vs.
          catalyst-absent) with the same RAW/EPISODE/PURGED, walk-forward, and bootstrap rigor as the
          Setup Research section above -- descriptive statistics only, never a score or a recommendation.
        </p>
      </div>

      <form onSubmit={handleQuery} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Setup type
          <input
            value={setupType}
            onChange={(e) => setSetupType(e.target.value)}
            placeholder="e.g. breakout_retest"
            className="w-44 rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Direction
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          >
            <option value="">any</option>
            <option value="bullish">bullish</option>
            <option value="bearish">bearish</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Qualified vs rejected
          <select
            value={qualificationState}
            onChange={(e) => setQualificationState(e.target.value)}
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          >
            <option value="">any</option>
            <option value="qualified">qualified</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Catalyst category
          <select
            value={catalystCategory}
            onChange={(e) => setCatalystCategory(e.target.value)}
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          >
            <option value="">any</option>
            {CATALYST_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {formatCatalystCategory(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Time since catalyst (max hours)
          <input
            type="number"
            min={0}
            value={maxHoursSince}
            onChange={(e) => setMaxHoursSince(e.target.value)}
            placeholder="e.g. 24"
            className="w-32 rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          RVOL bucket
          <select
            value={rvolElevated}
            onChange={(e) => setRvolElevated(e.target.value as "" | "true" | "false")}
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          >
            <option value="">any</option>
            <option value="true">elevated</option>
            <option value="false">not elevated</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Horizon (bars)
          <select
            value={horizonBars}
            onChange={(e) => setHorizonBars(Number(e.target.value))}
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          >
            {[1, 3, 5, 10, 20].map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 pb-1.5 text-xs text-muted">
          <input
            type="checkbox"
            checked={requireCatalyst}
            onChange={(e) => setRequireCatalyst(e.target.checked)}
          />
          Require catalyst
        </label>
        <label
          className={`flex items-center gap-1.5 pb-1.5 text-xs ${hasCatalystConstraint ? "text-muted" : "text-muted/50"}`}
          title={
            hasCatalystConstraint
              ? undefined
              : "Add a catalyst constraint (Require catalyst, a category, time-since, or RVOL bucket) first -- otherwise the filtered and unfiltered cohorts would be identical and the comparison would be meaningless."
          }
        >
          <input
            type="checkbox"
            checked={compareToNoCatalyst && hasCatalystConstraint}
            disabled={!hasCatalystConstraint}
            onChange={(e) => setCompareToNoCatalyst(e.target.checked)}
          />
          Compare vs. baseline (no match)
        </label>
        <button
          type="submit"
          disabled={status === "running"}
          className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
        >
          {status === "running" ? "QUERYING…" : "RUN CATALYST RESEARCH QUERY"}
        </button>
      </form>
      <p className="text-[10px] text-muted">
        Session, structure-state, and higher-timeframe-alignment filters are not yet wired to the
        backend and are intentionally omitted here rather than shown non-functional.
      </p>

      {status === "failed" && error && (
        <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">{error}</div>
      )}

      {status === "completed" && result && (
        <div className="space-y-3">
          {badges.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {badges.map((b) => (
                <span
                  key={b}
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${evidenceStateBadgeColorClass(b)}`}
                >
                  {b}
                </span>
              ))}
            </div>
          )}

          <div className="rounded border border-border bg-surface-raised p-3">
            <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">
              CATALYST FILTER SUMMARY
            </h3>
            <div className="grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-3">
              <div>
                <div className="text-muted">Raw sample, filtered</div>
                <div className="font-mono text-foreground">{result.catalyst_filtered_raw_sample_count}</div>
              </div>
              <div>
                <div className="text-muted">Raw sample, unfiltered</div>
                <div className="font-mono text-foreground">{result.unfiltered_raw_sample_count}</div>
              </div>
              <div>
                <div className="text-muted">Independent episodes (filtered)</div>
                <div className="font-mono text-foreground">
                  {result.independence.sample_composition.episode_count}
                </div>
              </div>
            </div>
            <p className="mt-1.5 text-[10px] text-muted">
              Raw counts above are ledger-entry counts, not independent sample size -- see the
              Independence &amp; robustness section below for episode/purged counts, which are what
              this cohort&apos;s actual statistical power rests on.
            </p>
          </div>

          {(result.qualification_lift || Object.keys(result.rejection_value).length > 0) && (
            <div className="rounded border border-border bg-surface-raised p-3">
              <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">
                QUALIFICATION / REJECTION VALUE (WITHIN THIS CATALYST COHORT)
              </h3>
              <div className="space-y-3">
                {result.qualification_lift && <ConclusionStabilityTable report={result.qualification_lift} />}
                {Object.entries(result.rejection_value).map(([code, report]) => (
                  <ConclusionStabilityTable key={code} report={report} />
                ))}
              </div>
            </div>
          )}

          {result.catalyst_vs_baseline && (
            <div className="rounded border border-border bg-surface-raised p-3">
              <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-muted">
                CATALYST COHORT VS. BASELINE (NO MATCH)
              </h3>
              <ConclusionStabilityTable report={result.catalyst_vs_baseline} />
            </div>
          )}

          <ResearchResultsPanel result={result} />
        </div>
      )}
    </section>
  );
}
