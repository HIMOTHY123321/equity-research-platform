"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { CandlestickChart } from "@/components/CandlestickChart";
import { SymbolSearch } from "@/components/SymbolSearch";
import { TopNav } from "@/components/TopNav";
import {
  evidenceQualityColorClass,
  forecastOutcomeColorClass,
  forecastStatusColorClass,
  formatEnumLabel,
  formatExchangeTimestamp,
  freshnessColorClass,
  freshnessDotClass,
  gateDecisionColorClass,
} from "@/lib/format";
import { ApiError, postForecast, resolveForecast } from "@/lib/api";
import { useForecastGate, useForecastList, useForecastPerformance } from "@/hooks/useForecasts";
import { useCandles, useSetups } from "@/hooks/useMarketQueries";
import { useLiveConnectionState, useLiveGlobalEvent, useLiveSymbol } from "@/hooks/useLiveSymbol";
import type {
  ForecastCategoryKind,
  ForecastOutcome,
  ForecastPerformanceBreakdown,
  ForwardForecast,
  LiveServerFrame,
  Timeframe,
} from "@/lib/types";

const FORECAST_CATEGORIES: ForecastCategoryKind[] = [
  "direction",
  "structure",
  "volatility",
  "catalyst_reaction",
  "setup_outcome",
];

function BreakdownTable({ title, rows }: { title: string; rows: ForecastPerformanceBreakdown[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-left font-mono text-xs">
          <thead className="text-muted">
            <tr>
              <th className="px-2 py-1">Group</th>
              <th className="px-2 py-1">N</th>
              <th className="px-2 py-1">Resolved</th>
              <th className="px-2 py-1">Accuracy</th>
              <th className="px-2 py-1">Coverage</th>
              <th className="px-2 py-1">Abstention</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.group} className="border-t border-border">
                <td className="px-2 py-1">{formatEnumLabel(row.group)}</td>
                <td className="px-2 py-1">{row.forecast_count}</td>
                <td className="px-2 py-1">{row.resolved_count}</td>
                <td className="px-2 py-1">
                  {row.directional_accuracy === null ? "—" : `${(row.directional_accuracy * 100).toFixed(0)}%`}
                </td>
                <td className="px-2 py-1">{row.coverage_rate === null ? "—" : `${(row.coverage_rate * 100).toFixed(0)}%`}</td>
                <td className="px-2 py-1">
                  {row.abstention_rate === null ? "—" : `${(row.abstention_rate * 100).toFixed(0)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
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

export default function ForecastLabPage() {
  const [urlSymbol, setUrlSymbol] = useState<string | null>(null);
  return (
    <>
      <Suspense fallback={null}>
        <SymbolUrlWatcher onChange={setUrlSymbol} />
      </Suspense>
      <ForecastLabPageInner urlSymbol={urlSymbol} />
    </>
  );
}

function ForecastLabPageInner({ urlSymbol }: { urlSymbol: string | null }) {
  const router = useRouter();
  // (#9) A symbol selected on Overview (`/?symbol=NVDA`) must persist here
  // rather than always resetting to a hardcoded default -- derived from the
  // URL (via SymbolUrlWatcher above, the single source of truth) so browser
  // back/forward and cross-page navigation both just work, no local state
  // to fall out of sync with it.
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
  const [forecastCategory, setForecastCategory] = useState<ForecastCategoryKind>("structure");
  const [horizonBars, setHorizonBars] = useState(20);
  const [setupId, setSetupId] = useState("");

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [outcomesByForecastId, setOutcomesByForecastId] = useState<Record<string, ForecastOutcome>>({});

  const candles = useCandles(symbol, timeframe, 300);
  const setups = useSetups(symbol, timeframe);
  const { candles: liveCandles } = useLiveSymbol(symbol, [timeframe]);
  const forecasts = useForecastList({ symbol, refreshKey });
  const performance = useForecastPerformance(symbol, refreshKey);
  const gate = useForecastGate(refreshKey);
  const connectionState = useLiveConnectionState();

  // Phase 12.1 (#I/#W): forecasts also resolve automatically in the
  // background (app.live.forecast_monitor), independent of this page even
  // being open. No refresh button -- a forecast_resolved push over the
  // shared live WebSocket connection is what moves a forecast from ACTIVE
  // to RESOLVED here and refreshes performance/gate.
  const handleLiveEvent = useCallback((frame: LiveServerFrame) => {
    if (frame.type === "forecast_resolved") {
      setOutcomesByForecastId((prev) => ({ ...prev, [frame.forecast_id]: frame.outcome }));
      setRefreshKey((k) => k + 1);
    }
  }, []);
  useLiveGlobalEvent(handleLiveEvent);

  const setupPool = setups.data
    ? [...setups.data.qualified_setups, ...setups.data.candidates, ...setups.data.rejected_candidates]
    : [];

  async function handleStartBenchmark(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await postForecast({
        symbol,
        timeframe,
        forecastCategory,
        horizonBars,
        setupId: setupId || undefined,
      });
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to create forecast");
    } finally {
      setCreating(false);
    }
  }

  async function handleResolve(forecastId: string) {
    setResolvingId(forecastId);
    try {
      const outcome = await resolveForecast(forecastId);
      setOutcomesByForecastId((prev) => ({ ...prev, [forecastId]: outcome }));
    } catch {
      // Resolution honestly fails (e.g. horizon hasn't closed yet) -- no
      // outcome is recorded; the forecast remains ACTIVE until retried.
    } finally {
      setResolvingId(null);
    }
  }

  const allForecasts = forecasts.data ?? [];
  const resolvedForecastIds = new Set(Object.keys(outcomesByForecastId));
  const activeForecasts = allForecasts.filter(
    (f) => f.status === "active" && !resolvedForecastIds.has(f.forecast_id),
  );
  const abstainedForecasts = allForecasts.filter((f) => f.status === "abstained");
  const resolvedRows = allForecasts
    .map((f) => ({ forecast: f, outcome: outcomesByForecastId[f.forecast_id] }))
    .filter((row): row is { forecast: ForwardForecast; outcome: ForecastOutcome } => row.outcome !== undefined);

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-5 px-6 py-6">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h1 className="font-mono text-lg font-semibold">FORECAST LAB</h1>
            <p className="text-xs text-muted">
              Prospective forward validation -- locked, machine-evaluable forecasts against a frozen evidence packet,
              resolved only once the horizon genuinely closes. No BUY/SELL, no price targets, no probabilities. RANKING
              GATE remains FAIL; this measures forecast accuracy only.
            </p>
          </div>
          <div className="flex items-center gap-1.5 whitespace-nowrap font-mono text-[11px]">
            <span className={`h-1.5 w-1.5 rounded-full ${freshnessDotClass(connectionState === "connected" ? "live" : "disconnected")}`} />
            <span className={freshnessColorClass(connectionState === "connected" ? "live" : "disconnected")}>
              {connectionState === "connected" ? "AUTO-UPDATING" : connectionState === "resyncing" ? "RESYNCING" : "DISCONNECTED"}
            </span>
          </div>
        </div>

        {/* ---- BLIND BENCHMARK ---- */}
        <section className="space-y-3 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Blind Benchmark</h2>
          <form onSubmit={handleStartBenchmark} className="flex flex-wrap items-end gap-3">
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
              Forecast type
              <select
                value={forecastCategory}
                onChange={(e) => setForecastCategory(e.target.value as ForecastCategoryKind)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              >
                {FORECAST_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {formatEnumLabel(c)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Horizon (bars)
              <input
                type="number"
                min={1}
                value={horizonBars}
                onChange={(e) => setHorizonBars(Number(e.target.value))}
                className="w-20 rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              />
            </label>
            <label className="flex min-w-[240px] flex-col gap-1 text-xs text-muted">
              Setup (optional -- required for direction/structure/setup_outcome)
              <select
                value={setupId}
                onChange={(e) => setSetupId(e.target.value)}
                className="rounded border border-border bg-surface-raised px-2 py-1 font-mono text-sm text-foreground"
              >
                <option value="">symbol-level (no setup)</option>
                {setupPool.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.setup_type} · {s.direction} · {formatExchangeTimestamp(s.candidate_candle_timestamp)}
                    {/* (§L) Two candidates can share type/direction/candle
                        but differ by reference_source/reference_price --
                        disambiguated here rather than looking like an
                        unexplained duplicate. */}
                    {s.reference_source ? ` · ref: ${s.reference_source}` : ""}
                    {s.reference_price !== null ? ` @ ${s.reference_price.toFixed(2)}` : ""}
                    {` · #${s.id.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={creating}
              className="rounded bg-accent px-4 py-1.5 font-mono text-xs font-semibold text-white disabled:opacity-50"
            >
              {creating ? "STARTING…" : "START BENCHMARK"}
            </button>
          </form>
          {createError && (
            <div className="rounded border border-negative/40 bg-negative/10 p-2 text-xs text-negative">
              {createError}
            </div>
          )}
        </section>

        {/* ---- CHART ---- */}
        <section className="h-[420px] rounded-md border border-border bg-surface p-2">
          {candles.data && (
            <CandlestickChart
              candles={candles.data.candles}
              forecasts={allForecasts}
              liveCandle={liveCandles[timeframe] ?? null}
              symbol={symbol}
              timeframe={timeframe}
            />
          )}
        </section>

        {/* ---- ACTIVE FORECASTS ---- */}
        <section className="space-y-2 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Active Forecasts ({activeForecasts.length})
          </h2>
          {/* (§I) Resolution is automatic -- the background ForecastMonitor
              resolves every forecast the instant its horizon genuinely
              closes, with no user action required. The per-row button
              below is a developer/debug escape hatch only, never the
              normal path. */}
          <p className="text-[10px] text-muted">
            Forecasts resolve automatically in the background once their horizon closes -- no action required.
          </p>
          {activeForecasts.length === 0 ? (
            <p className="text-xs text-muted">No active forecasts for {symbol}.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="text-muted">
                  <tr>
                    <th className="px-2 py-1">Type</th>
                    <th className="px-2 py-1">Value</th>
                    <th className="px-2 py-1">Locked at (market_as_of)</th>
                    <th className="px-2 py-1">Horizon</th>
                    <th className="px-2 py-1">Evidence</th>
                    <th className="px-2 py-1">Origin</th>
                    <th className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody>
                  {activeForecasts.map((f) => (
                    <tr key={f.forecast_id} className="border-t border-border">
                      <td className="px-2 py-1">{formatEnumLabel(f.forecast_category)}</td>
                      <td className={`px-2 py-1 ${forecastStatusColorClass(f.status)}`}>
                        {formatEnumLabel(f.forecast_value)}
                      </td>
                      <td className="px-2 py-1">{formatExchangeTimestamp(f.market_as_of)}</td>
                      <td className="px-2 py-1">{f.forecast_horizon_bars} bars</td>
                      <td className={`px-2 py-1 ${evidenceQualityColorClass(f.evidence_quality)}`}>
                        {formatEnumLabel(f.evidence_quality)}
                      </td>
                      <td className="px-2 py-1">{formatEnumLabel(f.origin)}</td>
                      <td className="px-2 py-1">
                        <button
                          type="button"
                          onClick={() => handleResolve(f.forecast_id)}
                          disabled={resolvingId === f.forecast_id}
                          title="Debug only -- forecasts resolve automatically in the background; this forces an immediate check instead of waiting for the next automatic scan."
                          className="rounded border border-border px-2 py-0.5 text-[10px] text-muted hover:border-accent hover:text-accent disabled:opacity-50"
                        >
                          {resolvingId === f.forecast_id ? "CHECKING…" : "CHECK NOW (DEBUG)"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ---- RESOLVED FORECASTS ---- */}
        <section className="space-y-2 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Resolved Forecasts ({resolvedRows.length})
          </h2>
          {resolvedRows.length === 0 ? (
            <p className="text-xs text-muted">
              No forecasts resolved yet in this session -- resolution happens automatically in the background once a
              forecast&apos;s horizon closes.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="text-muted">
                  <tr>
                    <th className="px-2 py-1">Type</th>
                    <th className="px-2 py-1">Forecast</th>
                    <th className="px-2 py-1">Actual</th>
                    <th className="px-2 py-1">Outcome</th>
                    <th className="px-2 py-1">Resolved at</th>
                    <th className="px-2 py-1">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {resolvedRows.map(({ forecast, outcome }) => (
                    <tr key={forecast.forecast_id} className="border-t border-border">
                      <td className="px-2 py-1">{formatEnumLabel(forecast.forecast_category)}</td>
                      <td className="px-2 py-1">{formatEnumLabel(forecast.forecast_value)}</td>
                      <td className="px-2 py-1">{formatEnumLabel(outcome.actual_value)}</td>
                      <td className={`px-2 py-1 ${forecastOutcomeColorClass(outcome.outcome)}`}>
                        {formatEnumLabel(outcome.outcome)}
                      </td>
                      <td className="px-2 py-1">{formatExchangeTimestamp(outcome.resolved_at)}</td>
                      <td className="px-2 py-1 text-muted">{outcome.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ---- ABSTENTIONS ---- */}
        <section className="space-y-2 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Abstentions ({abstainedForecasts.length})
          </h2>
          {abstainedForecasts.length === 0 ? (
            <p className="text-xs text-muted">No abstentions recorded for {symbol}.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="text-muted">
                  <tr>
                    <th className="px-2 py-1">Type</th>
                    <th className="px-2 py-1">Locked at</th>
                    <th className="px-2 py-1">Reason</th>
                    <th className="px-2 py-1">Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {abstainedForecasts.map((f) => (
                    <tr key={f.forecast_id} className="border-t border-border">
                      <td className="px-2 py-1">{formatEnumLabel(f.forecast_category)}</td>
                      <td className="px-2 py-1">{formatExchangeTimestamp(f.market_as_of)}</td>
                      <td className="px-2 py-1 text-muted">{formatEnumLabel(f.abstention_reason)}</td>
                      <td className="px-2 py-1 text-muted">{f.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ---- PERFORMANCE / BASELINES / BREAKDOWNS ---- */}
        <section className="space-y-4 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Performance</h2>
          {performance.data && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted">Forecasts</div>
                  <div className="font-mono text-lg text-foreground">{performance.data.overall.forecast_count}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted">Resolved</div>
                  <div className="font-mono text-lg text-foreground">{performance.data.overall.resolved_count}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted">Directional accuracy</div>
                  <div className="font-mono text-lg text-foreground">
                    {performance.data.overall.directional_accuracy === null
                      ? "— (insufficient sample)"
                      : `${(performance.data.overall.directional_accuracy * 100).toFixed(0)}%`}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted">Abstention rate</div>
                  <div className="font-mono text-lg text-foreground">
                    {performance.data.overall.abstention_rate === null
                      ? "—"
                      : `${(performance.data.overall.abstention_rate * 100).toFixed(0)}%`}
                  </div>
                </div>
              </div>

              <BreakdownTable title="Baselines" rows={performance.data.baselines.map((b) => ({
                group: b.name,
                forecast_count: b.sample_size,
                active_count: 0,
                resolved_count: b.sample_size,
                abstained_count: 0,
                correct_count: 0,
                incorrect_count: 0,
                neutral_count: 0,
                directional_accuracy: b.accuracy,
                average_forward_return_percent: null,
                average_mfe_atr: null,
                average_mae_atr: null,
                coverage_rate: null,
                abstention_rate: null,
              }))} />
              <BreakdownTable title="By Symbol" rows={performance.data.by_symbol} />
              <BreakdownTable title="By Setup Type" rows={performance.data.by_setup_type} />
              <BreakdownTable title="By Catalyst Category" rows={performance.data.by_catalyst_category} />
              <BreakdownTable title="By Horizon" rows={performance.data.by_horizon} />
            </>
          )}
        </section>

        {/* ---- FORWARD VALIDATION GATE ---- */}
        <section className="space-y-2 rounded-md border border-border bg-surface p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Forward Validation Gate</h2>
          {gate.data && (
            <>
              <p className="font-mono text-sm">
                Gate {gate.data.gate_version}:{" "}
                <span className={`font-semibold ${gateDecisionColorClass(gate.data.decision)}`}>
                  {formatEnumLabel(gate.data.decision)}
                </span>
              </p>
              <p className="text-[11px] text-muted">
                {gate.data.forecast_count} prospective forecast(s) · {gate.data.resolved_count} resolved ·{" "}
                {gate.data.independent_episode_estimate} independent episode(s) (coarse estimate)
              </p>
              {gate.data.reasons.length > 0 && (
                <ul className="list-inside list-disc text-[11px] text-muted">
                  {gate.data.reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              )}
              <p className="text-[10px] text-muted">
                Separate from, and never a replacement for, the Phase 9 RANKING GATE (still FAIL). Thresholds are
                fixed and versioned before results are observed.
              </p>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
