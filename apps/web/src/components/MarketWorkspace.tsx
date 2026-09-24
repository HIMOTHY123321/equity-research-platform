"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useState } from "react";

import { CandlestickChart, DEFAULT_CHART_DISPLAY_OPTIONS, type ChartDisplayOptions } from "@/components/CandlestickChart";
import { ChartLegend } from "@/components/ChartLegend";
import { DecisionMonitorPanel } from "@/components/DecisionMonitorPanel";
import { FeaturePanel } from "@/components/FeaturePanel";
import { RangeSelector } from "@/components/RangeSelector";
import { SetupInspectorPanel } from "@/components/SetupInspectorPanel";
import { StructurePanel } from "@/components/StructurePanel";
import { SupportResistancePanel } from "@/components/SupportResistancePanel";
import { LiveQuoteHeader } from "@/components/LiveQuoteHeader";
import { RealTimeToggle } from "@/components/RealTimeToggle";
import { SymbolCatalystTimeline } from "@/components/SymbolCatalystTimeline";
import { SymbolSearch } from "@/components/SymbolSearch";
import { TimeframeSelector } from "@/components/TimeframeSelector";
import { Watchlist } from "@/components/Watchlist";
import { WhatsMovingPanel } from "@/components/WhatsMovingPanel";
import {
  useCandles,
  useFeatures,
  useLevels,
  useSetups,
  useStructure,
  useSymbolCatalysts,
} from "@/hooks/useMarketQueries";
import { useCandleHistoryPagination } from "@/hooks/useCandleHistoryPagination";
import { useDecisionPlans } from "@/hooks/useDecisionPlans";
import { useLiveFollow } from "@/hooks/useLiveFollow";
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { useStreamingActive } from "@/hooks/useStreamingActive";
import { DEFAULT_RANGE, limitForRange, resolveRangeCompatibility, type ChartRange } from "@/lib/chartRanges";
import type { Timeframe } from "@/lib/types";

/**
 * Owns every market-data request for the selected symbol/timeframe exactly
 * once (candles, features, structure, levels) and hands the results down to
 * both the panels and the chart overlay -- no component below this one
 * fetches anything itself, and structure/levels are each requested only
 * once even though both a panel AND the chart use them.
 */
export function MarketWorkspace({ defaultSymbol }: { defaultSymbol: string }) {
  return (
    <Suspense fallback={null}>
      <MarketWorkspaceInner defaultSymbol={defaultSymbol} />
    </Suspense>
  );
}

function MarketWorkspaceInner({ defaultSymbol }: { defaultSymbol: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // (#5/#9) Derived from the URL (server-set on first load via `defaultSymbol`,
  // client-navigated thereafter) so a symbol change here is a real history
  // entry -- back/forward and cross-page persistence both just work, no
  // local state to fall out of sync with it.
  const symbol = searchParams.get("symbol")?.toUpperCase().trim() || defaultSymbol;
  const setSymbol = useCallback(
    (next: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("symbol", next);
      // push (not replace): each symbol change is a distinct back-stack
      // entry -- "SPY -> NVDA -> AAPL -> Back = NVDA -> Back = SPY".
      router.push(`?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [range, setRange] = useState<ChartRange>(DEFAULT_RANGE);
  const [display, setDisplay] = useState<ChartDisplayOptions>(DEFAULT_CHART_DISPLAY_OPTIONS);
  const [realTimeMode, setRealTimeMode] = useState(false);
  const streamingActive = useStreamingActive();
  // (#6) Architecture for live-follow: real end-to-end behavior can't be
  // verified without a genuine Massive entitlement (not active here), so
  // this is wired defensively and covered by mocked hook tests instead.
  const liveFollow = useLiveFollow(streamingActive && realTimeMode);

  function toggleDisplay(key: keyof ChartDisplayOptions) {
    setDisplay((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  // (#5/#6) MAX+1m and similar impossible (range, interval) combinations
  // never silently return a tiny recent window -- the actual resolution
  // used everywhere below is the resolved one, and `compat.note` discloses
  // any substitution to the user rather than hiding it.
  const compat = resolveRangeCompatibility(range, timeframe);
  const effectiveTimeframe = compat.effectiveTimeframe;

  const candlesQuery = useCandles(symbol, effectiveTimeframe, limitForRange(range, effectiveTimeframe));
  const featuresQuery = useFeatures(symbol, effectiveTimeframe);
  const structureQuery = useStructure(symbol, effectiveTimeframe);
  const levelsQuery = useLevels(symbol, effectiveTimeframe);
  const setupsQuery = useSetups(symbol, effectiveTimeframe);
  const decisionsQuery = useDecisionPlans(symbol, effectiveTimeframe);
  const catalystsQuery = useSymbolCatalysts(symbol);
  const { candles: liveCandles } = useLiveSymbol(symbol, [effectiveTimeframe]);
  const history = useCandleHistoryPagination(symbol, effectiveTimeframe, candlesQuery);

  const candles = history.candles;
  const chartState =
    candlesQuery.state === "ready" && candles.length === 0 ? "empty" : candlesQuery.state;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
        <aside className="rounded-md border border-border bg-surface p-3">
          {/* (#2) The primary symbol selector -- searchable by ticker or
              company name, never a plain "type an exact ticker" box. */}
          <SymbolSearch value={symbol} onSelect={setSymbol} placeholder="Search symbol…" className="mb-3" />
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">WATCHLIST</h2>
          <Watchlist selected={symbol} onSelect={setSymbol} />
        </aside>

        <section className="rounded-md border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <div className="flex items-center gap-3">
              <h2 className="font-mono text-sm font-semibold text-foreground">{symbol}</h2>
              <LiveQuoteHeader symbol={symbol} timeframe={effectiveTimeframe} realTimeMode={realTimeMode} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5 text-[10px]">
                {(
                  [
                    ["structure", "Structure"],
                    ["supportResistance", "S/R"],
                    ["setups", "Setups"],
                    ["decisions", "Decisions"],
                    ["allPivots", "All Pivots"],
                  ] as [keyof ChartDisplayOptions, string][]
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggleDisplay(key)}
                    className={`rounded border px-2 py-1 font-mono uppercase tracking-wide ${
                      display[key]
                        ? "border-accent bg-accent/15 text-accent"
                        : "border-border text-muted"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <RealTimeToggle
                active={realTimeMode}
                streamingActive={streamingActive}
                onToggle={() => setRealTimeMode((v) => !v)}
              />
              <RangeSelector value={range} onChange={setRange} />
              {/* (#5/#6) Always reflects the ACTUAL resolution in use, not
                  necessarily what was last clicked -- clicking still sets
                  the desired interval via onChange, but an incompatible
                  combination shows the resolved fallback here instead of
                  a selector that lies about what's on screen. */}
              <TimeframeSelector value={effectiveTimeframe} onChange={setTimeframe} />
            </div>
          </div>
          {compat.note && (
            <div className="border-b border-border bg-amber-500/5 px-4 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              {compat.note}
            </div>
          )}
          <div
            className="relative h-[480px] p-2"
            // (#6) A manual pan/zoom while REAL TIME is active pauses
            // auto-follow -- new events may keep arriving in the
            // background without snapping the chart away from what the
            // user is inspecting. No-op when REAL TIME isn't active.
            onWheel={liveFollow.pause}
            onPointerDown={liveFollow.pause}
          >
            {liveFollow.showReturnToLive && (
              <button
                type="button"
                onClick={liveFollow.resume}
                className="absolute right-4 top-4 z-10 rounded border border-accent bg-surface px-2.5 py-1 font-mono text-[10px] font-semibold text-accent shadow"
              >
                RETURN TO LIVE
              </button>
            )}
            {chartState === "loading" && (
              <div className="flex h-full items-center justify-center text-xs text-muted">
                Loading chart…
              </div>
            )}
            {chartState === "error" && (
              <div className="flex h-full items-center justify-center text-xs text-negative">
                {candlesQuery.error}
              </div>
            )}
            {chartState === "empty" && (
              <div className="flex h-full items-center justify-center text-xs text-muted">
                No candles returned for {symbol} at {effectiveTimeframe}.
              </div>
            )}
            {chartState === "ready" && (
              <CandlestickChart
                candles={candles}
                structure={
                  structureQuery.data
                    ? {
                        swings: structureQuery.data.swings,
                        breaksOfStructure: structureQuery.data.breaks_of_structure,
                        changesOfCharacter: structureQuery.data.changes_of_character,
                      }
                    : undefined
                }
                zones={
                  levelsQuery.data
                    ? {
                        support: levelsQuery.data.active_support_zones,
                        resistance: levelsQuery.data.active_resistance_zones,
                      }
                    : undefined
                }
                setups={
                  setupsQuery.data
                    ? [...setupsQuery.data.qualified_setups, ...setupsQuery.data.candidates]
                    : undefined
                }
                decisions={decisionsQuery.data ?? undefined}
                // (#6) Paused (autoFollow=false) suppresses the live overlay
                // so the forming candle stops visually updating while the
                // user is inspecting an older part of the chart -- events
                // keep arriving in the background (useLiveSymbol itself
                // never stops), only the visual snap is withheld.
                liveCandle={liveFollow.autoFollow ? (liveCandles[effectiveTimeframe] ?? null) : null}
                display={display}
                symbol={symbol}
                timeframe={effectiveTimeframe}
                onNeedOlderHistory={history.loadOlder}
              />
            )}
            {/* (FINAL TERMINAL POLISH PASS #1) Pan-left pagination status --
                non-blocking overlays so the chart itself is never obscured. */}
            {chartState === "ready" && history.loadingOlder && (
              <div className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded border border-border bg-surface/90 px-2.5 py-1 font-mono text-[10px] text-muted">
                LOADING OLDER HISTORY…
              </div>
            )}
            {chartState === "ready" && !history.loadingOlder && history.error && (
              <div className="absolute bottom-2 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded border border-negative/40 bg-surface/95 px-2.5 py-1 font-mono text-[10px] text-negative">
                <span>Failed to load older history.</span>
                <button type="button" onClick={history.retry} className="underline">
                  RETRY
                </button>
              </div>
            )}
            {chartState === "ready" && !history.loadingOlder && !history.error && history.historyExhausted && (
              <div className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded border border-border bg-surface/90 px-2.5 py-1 font-mono text-[10px] text-muted">
                EARLIEST AVAILABLE DATA
              </div>
            )}
          </div>
          <ChartLegend />
        </section>
      </div>

      {/* Decision-first ordering: setup intelligence (what matters right now
          and why) leads, structure/S-R support that read, and raw feature
          data -- the most "debug terminal" of these panels -- comes last. */}
      <section className="rounded-md border border-border bg-surface p-3">
        <SetupInspectorPanel query={setupsQuery} />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <DecisionMonitorPanel symbol={symbol} query={decisionsQuery} />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">WHAT&apos;S MOVING THE MARKET</h2>
        <WhatsMovingPanel />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">
          CATALYST TIMELINE — {symbol}
        </h2>
        <SymbolCatalystTimeline
          query={catalystsQuery}
          symbol={symbol}
          timeframe={effectiveTimeframe}
          setups={setupsQuery.data ? [...setupsQuery.data.qualified_setups, ...setupsQuery.data.candidates] : []}
        />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">
          MARKET STRUCTURE — {symbol}
        </h2>
        <StructurePanel query={structureQuery} />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">
          SUPPORT / RESISTANCE — {symbol}
        </h2>
        <SupportResistancePanel query={levelsQuery} />
      </section>

      <section className="rounded-md border border-border bg-surface p-3">
        <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">
          FEATURES — {symbol}
        </h2>
        <FeaturePanel query={featuresQuery} />
      </section>
    </div>
  );
}
