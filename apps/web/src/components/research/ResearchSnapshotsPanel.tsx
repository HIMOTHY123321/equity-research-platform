"use client";

import { useState } from "react";

import { ApiError, compareResearchSnapshots, createResearchSnapshot, listResearchSnapshots } from "@/lib/api";
import type { ResearchQueryResponse, ResearchSnapshot, SnapshotComparison } from "@/lib/types";

type Status = "idle" | "running" | "completed" | "failed";

export function ResearchSnapshotsPanel({
  runIds,
  cohortDefinition,
  queryResult,
}: {
  runIds: string[];
  cohortDefinition: Record<string, unknown>;
  queryResult: ResearchQueryResponse | null;
}) {
  const [label, setLabel] = useState("");
  const [saveStatus, setSaveStatus] = useState<Status>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const [snapshots, setSnapshots] = useState<ResearchSnapshot[]>([]);
  const [listStatus, setListStatus] = useState<Status>("idle");

  const [snapshotA, setSnapshotA] = useState("");
  const [snapshotB, setSnapshotB] = useState("");
  const [comparison, setComparison] = useState<SnapshotComparison | null>(null);
  const [compareStatus, setCompareStatus] = useState<Status>("idle");
  const [compareError, setCompareError] = useState<string | null>(null);

  async function refreshList() {
    setListStatus("running");
    try {
      const list = await listResearchSnapshots();
      setSnapshots(list);
      setListStatus("completed");
    } catch {
      setListStatus("failed");
    }
  }

  async function handleSave() {
    if (!queryResult || runIds.length === 0) return;
    setSaveStatus("running");
    setSaveError(null);
    try {
      await createResearchSnapshot({
        label: label || `${cohortDefinition.setup_type ?? "all"} snapshot`,
        research_run_ids: runIds,
        config_hash: "live-query",
        dataset_manifest: { symbols: [], timeframe: "", requested_start: "", requested_end: "" },
        cohort_definition: cohortDefinition,
        filters: { horizon_bars: queryResult.evidence_card.horizon_bars },
        statistical_output: queryResult as unknown as Record<string, unknown>,
        warning_flags: queryResult.evidence_card.flags,
      });
      setSaveStatus("completed");
      setLabel("");
      await refreshList();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to save snapshot");
      setSaveStatus("failed");
    }
  }

  async function handleCompare() {
    if (!snapshotA || !snapshotB) return;
    setCompareStatus("running");
    setCompareError(null);
    try {
      const result = await compareResearchSnapshots(snapshotA, snapshotB);
      setComparison(result);
      setCompareStatus("completed");
    } catch (err) {
      setCompareError(err instanceof ApiError ? err.message : "Failed to compare snapshots");
      setCompareStatus("failed");
    }
  }

  return (
    <section className="space-y-3 rounded-md border border-border bg-surface p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Research snapshots</h2>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-1 min-w-[240px] flex-col gap-1 text-xs text-muted">
          Label
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. trend_pullback SPY Aug 2026"
            className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
          />
        </label>
        <button
          type="button"
          onClick={handleSave}
          disabled={!queryResult || saveStatus === "running"}
          className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
        >
          {saveStatus === "running" ? "SAVING…" : "SAVE CURRENT RESULT AS SNAPSHOT"}
        </button>
        <button
          type="button"
          onClick={refreshList}
          className="rounded border border-border px-4 py-1.5 font-mono text-xs font-semibold text-foreground"
        >
          {listStatus === "running" ? "LOADING…" : "REFRESH LIST"}
        </button>
      </div>
      {saveStatus === "failed" && saveError && (
        <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">{saveError}</div>
      )}
      {!queryResult && <p className="text-[11px] text-muted">Run a research query first to save a snapshot.</p>}

      {snapshots.length > 0 && (
        <ul className="space-y-1 text-[11px]">
          {snapshots.map((s) => (
            <li key={s.snapshot_id} className="flex items-center justify-between">
              <span className="text-foreground">
                {s.label} <span className="text-muted">({new Date(s.created_at).toLocaleString()})</span>
              </span>
              <span className="font-mono text-muted">{s.snapshot_id.slice(0, 8)}</span>
            </li>
          ))}
        </ul>
      )}

      {snapshots.length >= 2 && (
        <div className="border-t border-border pt-3">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Compare two snapshots</h3>
          <div className="flex flex-wrap items-end gap-3">
            <select
              value={snapshotA}
              onChange={(e) => setSnapshotA(e.target.value)}
              className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
            >
              <option value="">snapshot A…</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  {s.label}
                </option>
              ))}
            </select>
            <select
              value={snapshotB}
              onChange={(e) => setSnapshotB(e.target.value)}
              className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
            >
              <option value="">snapshot B…</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  {s.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleCompare}
              disabled={!snapshotA || !snapshotB || compareStatus === "running"}
              className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
            >
              {compareStatus === "running" ? "COMPARING…" : "COMPARE"}
            </button>
          </div>
          {compareStatus === "failed" && compareError && (
            <div className="mt-2 rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">
              {compareError}
            </div>
          )}
          {comparison && (
            <div className="mt-2 text-[11px]">
              <p className="text-muted">
                Same config: <span className="font-mono text-foreground">{String(comparison.same_config_hash)}</span>
                {" · "}Same dataset:{" "}
                <span className="font-mono text-foreground">{String(comparison.same_dataset)}</span>
              </p>
              <ul className="mt-1 space-y-0.5">
                {comparison.field_diffs
                  .filter((d) => d.changed)
                  .map((d) => (
                    <li key={d.field} className="text-foreground">
                      <span className="text-muted">{d.field}:</span> {d.snapshot_a_value ?? "—"} →{" "}
                      {d.snapshot_b_value ?? "—"}
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
