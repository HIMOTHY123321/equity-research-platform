"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { CatalystResearchPanel } from "@/components/research/CatalystResearchPanel";
import { HistoricalAnalogsPanel } from "@/components/research/HistoricalAnalogsPanel";
import { ResearchResultsPanel } from "@/components/research/ResearchResultsPanel";
import { ResearchSnapshotsPanel } from "@/components/research/ResearchSnapshotsPanel";
import { SetupTypeResearchCard } from "@/components/research/SetupTypeResearchCard";
import { SymbolSearch } from "@/components/SymbolSearch";
import { TopNav } from "@/components/TopNav";
import {
  ApiError,
  getResearchRunSetups,
  getResearchRunSummary,
  postAnalogQuery,
  postReplay,
  postResearchQuery,
  postUniverseReplay,
} from "@/lib/api";
import type {
  AnalogDiversityReport,
  AnalogResult,
  ResearchQueryResponse,
  ResearchRun,
  ResearchRunSummary,
  ResearchSetupLedgerEntry,
  Timeframe,
} from "@/lib/types";

type RunStatus = "idle" | "running" | "completed" | "failed";
type AsyncStatus = "idle" | "running" | "completed" | "failed";

const DEFAULT_UNIVERSE = "SPY,QQQ,NVDA,AAPL,MSFT,META,AMZN,TSLA";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

// Phase 13.1 hardening: isolate useSearchParams() to this tiny, render-
// nothing leaf instead of gating the entire (heavy) page behind its
// Suspense boundary -- see the matching comment in MarketWorkspace.tsx for
// the full root-cause writeup (a cold load never called the page's render
// function at all until a user interaction forced React to flush the
// low-priority Suspense-hydration lane; no console error, no failed
// request).
function SymbolUrlWatcher({ onChange }: { onChange: (symbol: string | null) => void }) {
  const searchParams = useSearchParams();
  const symbol = searchParams.get("symbol");
  useEffect(() => {
    onChange(symbol);
  }, [symbol, onChange]);
  return null;
}

export default function ResearchLabPage() {
  const [urlSymbol, setUrlSymbol] = useState<string | null>(null);
  return (
    <>
      <Suspense fallback={null}>
        <SymbolUrlWatcher onChange={setUrlSymbol} />
      </Suspense>
      <ResearchLabPageInner urlSymbol={urlSymbol} />
    </>
  );
}

function ResearchLabPageInner({ urlSymbol }: { urlSymbol: string | null }) {
  const router = useRouter();
  // ---- Single-symbol replay (existing, unchanged) --------------------------
  // (#9) Same URL-query-state persistence convention as Forecast Lab/
  // Overview -- derived from the URL (via SymbolUrlWatcher above), no local
  // state to fall out of sync with it.
  const symbol = urlSymbol?.toUpperCase().trim() || "SPY";

  const setSymbol = useCallback(
    (next: string) => {
      // Read the live URL at call time -- an event-handler-only read, never
      // during render/SSR -- instead of depending on useSearchParams() in
      // this (heavy) component; see SymbolUrlWatcher above.
      const params = new URLSearchParams(window.location.search);
      params.set("symbol", next);
      // push (not replace): each symbol change is its own back-stack entry.
      router.push(`?${params.toString()}`, { scroll: false });
    },
    [router],
  );
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [start, setStart] = useState(isoDaysAgo(30));
  const [end, setEnd] = useState(isoDaysAgo(2));

  const [status, setStatus] = useState<RunStatus>("idle");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [summary, setSummary] = useState<ResearchRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ---- Dataset: pooled run ids (single-symbol + universe) -------------------
  const [poolRunIds, setPoolRunIds] = useState<Record<string, string>>({});

  // ---- Universe replay --------------------------------------------------
  const [universeInput, setUniverseInput] = useState(DEFAULT_UNIVERSE);
  const [universeStatus, setUniverseStatus] = useState<AsyncStatus>("idle");
  const [universeError, setUniverseError] = useState<string | null>(null);
  const [universeFailures, setUniverseFailures] = useState<Record<string, string>>({});

  // ---- Setup research filters + query ------------------------------------
  const [setupType, setSetupType] = useState("");
  const [direction, setDirection] = useState("");
  const [qualificationState, setQualificationState] = useState("");
  const [horizonBars, setHorizonBars] = useState(5);
  const [queryStatus, setQueryStatus] = useState<AsyncStatus>("idle");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<ResearchQueryResponse | null>(null);

  // ---- Historical analogs --------------------------------------------------
  const [runEntries, setRunEntries] = useState<ResearchSetupLedgerEntry[]>([]);
  const [selectedEntryId, setSelectedEntryId] = useState("");
  const [entryFilter, setEntryFilter] = useState("");
  const [analogs, setAnalogs] = useState<AnalogResult[] | null>(null);
  const [analogDiversity, setAnalogDiversity] = useState<AnalogDiversityReport | null>(null);
  const [diverseAnalogs, setDiverseAnalogs] = useState<AnalogResult[] | null>(null);
  const [diverseAnalogsDiversity, setDiverseAnalogsDiversity] = useState<AnalogDiversityReport | null>(null);
  const [diversityUnavailableReason, setDiversityUnavailableReason] = useState<string | null>(null);
  const [analogQuerySetupType, setAnalogQuerySetupType] = useState<string | null>(null);
  const [analogStatus, setAnalogStatus] = useState<AsyncStatus>("idle");
  const [analogError, setAnalogError] = useState<string | null>(null);

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setStatus("running");
    setError(null);
    setRun(null);
    setSummary(null);
    try {
      const startIso = new Date(`${start}T00:00:00Z`).toISOString();
      const endIso = new Date(`${end}T23:59:59Z`).toISOString();
      const completedRun = await postReplay(symbol, timeframe, startIso, endIso);
      setRun(completedRun);
      if (completedRun.status === "completed") {
        const s = await getResearchRunSummary(completedRun.id);
        setSummary(s);
        setStatus("completed");
        setPoolRunIds((prev) => ({ ...prev, [symbol]: completedRun.id }));
        const setups = await getResearchRunSetups(completedRun.id, { limit: 150 });
        setRunEntries(setups.entries);
      } else {
        setStatus("failed");
        setError(completedRun.error ?? "Replay did not complete");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Replay failed");
      setStatus("failed");
    }
  }

  async function handleUniverseReplay(e: React.FormEvent) {
    e.preventDefault();
    setUniverseStatus("running");
    setUniverseError(null);
    setUniverseFailures({});
    try {
      const symbols = universeInput
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);
      const startIso = new Date(`${start}T00:00:00Z`).toISOString();
      const endIso = new Date(`${end}T23:59:59Z`).toISOString();
      const res = await postUniverseReplay(symbols, timeframe, startIso, endIso);
      setPoolRunIds((prev) => ({ ...prev, ...res.run_ids }));
      setUniverseFailures(res.failures);
      setUniverseStatus("completed");
    } catch (err) {
      setUniverseError(err instanceof ApiError ? err.message : "Universe replay failed");
      setUniverseStatus("failed");
    }
  }

  async function handleQuery(e: React.FormEvent) {
    e.preventDefault();
    const runIds = Object.values(poolRunIds);
    if (runIds.length === 0) {
      setQueryError("Run a replay (single-symbol or universe) first.");
      setQueryStatus("failed");
      return;
    }
    setQueryStatus("running");
    setQueryError(null);
    try {
      const result = await postResearchQuery({
        runIds,
        setupType: setupType || undefined,
        direction: direction || undefined,
        qualificationState: qualificationState || undefined,
        horizonBars,
      });
      setQueryResult(result);
      setQueryStatus("completed");
    } catch (err) {
      setQueryError(err instanceof ApiError ? err.message : "Research query failed");
      setQueryStatus("failed");
    }
  }

  async function handleFindAnalogs() {
    const entry = runEntries.find((e) => e.setup_id === selectedEntryId);
    const runIds = Object.values(poolRunIds);
    if (!entry || runIds.length === 0) return;
    setAnalogStatus("running");
    setAnalogError(null);
    try {
      const res = await postAnalogQuery(entry.detection, runIds, 10);
      setAnalogs(res.analogs);
      setAnalogDiversity(res.diversity);
      setDiverseAnalogs(res.diverse_analogs);
      setDiverseAnalogsDiversity(res.diverse_analogs_diversity);
      setDiversityUnavailableReason(res.diversity_unavailable_reason ?? null);
      setAnalogQuerySetupType(entry.detection.setup_type);
      setAnalogStatus("completed");
    } catch (err) {
      setAnalogError(err instanceof ApiError ? err.message : "Analog query failed");
      setAnalogStatus("failed");
    }
  }

  const pooledSymbols = Object.keys(poolRunIds);
  const filteredEntries = entryFilter
    ? runEntries.filter((e) => e.setup_type.includes(entryFilter.toLowerCase().replace(/\s+/g, "_")))
    : runEntries;

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-5 px-6 py-6">
        <div>
          <h1 className="font-mono text-lg font-semibold">RESEARCH LAB</h1>
          <p className="text-xs text-muted">
            Historical replay, setup ledger, and research intelligence -- descriptive statistics only, no scores,
            no P&amp;L, no predictions.
          </p>
        </div>

        {/* ---- DATASET ---- */}
        <section className="space-y-3 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Dataset</h2>

          <form onSubmit={handleRun} className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Symbol
              <SymbolSearch value={symbol} onSelect={setSymbol} className="w-32" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Timeframe
              <select
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value as Timeframe)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              >
                <option value="5m">5M</option>
                <option value="15m">15M</option>
                <option value="1h">1H</option>
                <option value="4h">4H</option>
                <option value="1d">1D</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Start date
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              End date
              <input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              />
            </label>
            <button
              type="submit"
              disabled={status === "running"}
              className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
            >
              {status === "running" ? "RUNNING…" : "RUN HISTORICAL REPLAY"}
            </button>
          </form>

          <form onSubmit={handleUniverseReplay} className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
            <label className="flex flex-1 min-w-[280px] flex-col gap-1 text-xs text-muted">
              Universe (comma-separated symbols, uses the same timeframe/date range above)
              <input
                value={universeInput}
                onChange={(e) => setUniverseInput(e.target.value)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              />
            </label>
            <button
              type="submit"
              disabled={universeStatus === "running"}
              className="rounded border border-accent px-4 py-1.5 font-mono text-xs font-semibold text-accent disabled:opacity-50"
            >
              {universeStatus === "running" ? "RUNNING…" : "RUN UNIVERSE REPLAY"}
            </button>
          </form>

          {status === "failed" && error && (
            <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">{error}</div>
          )}
          {universeError && (
            <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">
              {universeError}
            </div>
          )}
          {Object.keys(universeFailures).length > 0 && (
            <div className="rounded border border-amber-500/40 bg-amber-500/5 p-2 text-[11px] text-amber-600 dark:text-amber-400">
              {Object.entries(universeFailures).map(([sym, msg]) => (
                <div key={sym}>
                  {sym}: {msg}
                </div>
              ))}
            </div>
          )}

          {pooledSymbols.length > 0 && (
            <p className="text-[11px] text-muted">
              Dataset pool: <span className="font-mono text-foreground">{pooledSymbols.join(", ")}</span> ·{" "}
              {timeframe} · {start} – {end} · partitions: development/validation/test (chronological, 60/20/20)
            </p>
          )}
        </section>

        {status === "completed" && run && summary && (
          <section className="space-y-3">
            <div className="grid grid-cols-2 gap-3 rounded-md border border-border bg-surface p-4 sm:grid-cols-4">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted">Bars processed</div>
                <div className="font-mono text-lg text-foreground">{summary.bars_processed}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted">Qualified setups</div>
                <div className="font-mono text-lg text-positive">{summary.qualified_count}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted">Rejected near-misses</div>
                <div className="font-mono text-lg text-negative">{summary.rejected_count}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted">Run duration</div>
                <div className="font-mono text-lg text-foreground">{summary.runtime_seconds.toFixed(1)}s</div>
              </div>
            </div>

            {summary.setup_types.length > 0 && (
              <div className="space-y-3">
                {summary.setup_types.map((st) => (
                  <SetupTypeResearchCard key={st.setup_type} summary={st} />
                ))}
              </div>
            )}
          </section>
        )}

        {/* ---- SETUP RESEARCH / FILTERS / RESULTS ---- */}
        <section className="space-y-3 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Setup research</h2>
          <form onSubmit={handleQuery} className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Setup type
              <input
                value={setupType}
                onChange={(e) => setSetupType(e.target.value)}
                placeholder="e.g. breakout_retest"
                className="w-48 rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
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
              Qualification
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
            <button
              type="submit"
              disabled={queryStatus === "running"}
              className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
            >
              {queryStatus === "running" ? "QUERYING…" : "RUN RESEARCH QUERY"}
            </button>
          </form>

          {queryStatus === "failed" && queryError && (
            <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">
              {queryError}
            </div>
          )}

          {queryStatus === "completed" && queryResult && <ResearchResultsPanel result={queryResult} />}
        </section>

        {/* ---- CATALYST RESEARCH ---- */}
        <CatalystResearchPanel runIds={Object.values(poolRunIds)} />

        {/* ---- HISTORICAL ANALOGS ---- */}
        {runEntries.length > 0 && (
          <section className="space-y-3 rounded-md border border-border bg-surface p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Similar historical setups</h2>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex w-48 flex-col gap-1 text-xs text-muted">
                Filter (setup type)
                <input
                  value={entryFilter}
                  onChange={(e) => setEntryFilter(e.target.value)}
                  placeholder="e.g. breakout"
                  className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
                />
              </label>
              <label className="flex flex-1 min-w-[280px] flex-col gap-1 text-xs text-muted">
                Ledger entry ({Math.min(filteredEntries.length, 100)} of {filteredEntries.length} shown)
                <select
                  value={selectedEntryId}
                  onChange={(e) => setSelectedEntryId(e.target.value)}
                  className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
                >
                  <option value="">select a setup…</option>
                  {filteredEntries.slice(0, 100).map((e) => (
                    <option key={e.setup_id} value={e.setup_id}>
                      {e.symbol} · {e.setup_type} · {e.direction} ·{" "}
                      {new Date(e.candidate_candle_timestamp).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={handleFindAnalogs}
                disabled={!selectedEntryId || analogStatus === "running"}
                className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
              >
                {analogStatus === "running" ? "SEARCHING…" : "VIEW HISTORICAL ANALOGS"}
              </button>
            </div>
            {analogStatus === "failed" && analogError && (
              <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">
                {analogError}
              </div>
            )}
            {analogStatus === "completed" && analogs && (
              <HistoricalAnalogsPanel
                analogs={analogs}
                diversity={analogDiversity ?? undefined}
                diverseAnalogs={diverseAnalogs ?? undefined}
                diverseAnalogsDiversity={diverseAnalogsDiversity ?? undefined}
                diversityUnavailableReason={diversityUnavailableReason}
                querySetupType={analogQuerySetupType ?? undefined}
              />
            )}
          </section>
        )}

        {/* ---- RESEARCH SNAPSHOTS ---- */}
        {Object.keys(poolRunIds).length > 0 && (
          <ResearchSnapshotsPanel
            runIds={Object.values(poolRunIds)}
            cohortDefinition={{
              setup_type: setupType || null,
              direction: direction || null,
              qualification_state: qualificationState || null,
            }}
            queryResult={queryResult}
          />
        )}
      </main>
    </div>
  );
}
