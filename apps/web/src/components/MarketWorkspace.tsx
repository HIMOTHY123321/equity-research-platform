"use client";

import { useState } from "react";

import { CandlestickChart, DEFAULT_CHART_DISPLAY_OPTIONS, type ChartDisplayOptions } from "@/components/CandlestickChart";
import { FeaturePanel } from "@/components/FeaturePanel";
import { RangeSelector } from "@/components/RangeSelector";
import { SetupInspectorPanel } from "@/components/SetupInspectorPanel";
import { StructurePanel } from "@/components/StructurePanel";
import { SupportResistancePanel } from "@/components/SupportResistancePanel";
import { LiveQuoteHeader } from "@/components/LiveQuoteHeader";
import { SymbolCatalystTimeline } from "@/components/SymbolCatalystTimeline";
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
import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { DEFAULT_RANGE, limitForRange, type ChartRange } from "@/lib/chartRanges";
import type { Timeframe } from "@/lib/types";

/**
 * Owns every market-data request for the selected symbol/timeframe exactly
 * once (candles, features, structure, levels) and hands the results down to
 * both the panels and the chart overlay -- no component below this one
 * fetches anything itself, and structure/levels are each requested only
 * once even though both a panel AND the chart use them.
 */
export function MarketWorkspace({ defaultSymbol }: { defaultSymbol: string }) {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [range, setRange] = useState<ChartRange>(DEFAULT_RANGE);
  const [display, setDisplay] = useState<ChartDisplayOptions>(DEFAULT_CHART_DISPLAY_OPTIONS);

  function toggleDisplay(key: keyof ChartDisplayOptions) {
    setDisplay((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const candlesQuery = useCandles(symbol, timeframe, limitForRange(range, timeframe));
  const featuresQuery = useFeatures(symbol, timeframe);
  const structureQuery = useStructure(symbol, timeframe);
  const levelsQuery = useLevels(symbol, timeframe);
  const setupsQuery = useSetups(symbol, timeframe);
  const catalystsQuery = useSymbolCatalysts(symbol);
  const { candles: liveCandles } = useLiveSymbol(symbol, [timeframe]);

  const candles = candlesQuery.data?.candles ?? [];
  const chartState =
    candlesQuery.state === "ready" && candles.length === 0 ? "empty" : candlesQuery.state;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
        <aside className="rounded-md border border-border bg-surface p-3">
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-foreground">WATCHLIST</h2>
          <Watchlist selected={symbol} onSelect={setSymbol} />
        </aside>

        <section className="rounded-md border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <div className="flex items-center gap-3">
              <h2 className="font-mono text-sm font-semibold text-foreground">{symbol}</h2>
              <LiveQuoteHeader symbol={symbol} timeframe={timeframe} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5 text-[10px]">
                {(
                  [
                    ["structure", "Structure"],
                    ["supportResistance", "S/R"],
                    ["setups", "Setups"],
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
              <RangeSelector value={range} onChange={setRange} />
              <TimeframeSelector value={timeframe} onChange={setTimeframe} />
            </div>
          </div>
          <div className="h-[480px] p-2">
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
                No candles returned for {symbol} at {timeframe}.
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
                liveCandle={liveCandles[timeframe] ?? null}
                display={display}
                symbol={symbol}
                timeframe={timeframe}
              />
            )}
          </div>
        </section>
      </div>

      {/* Decision-first ordering: setup intelligence (what matters right now
          and why) leads, structure/S-R support that read, and raw feature
          data -- the most "debug terminal" of these panels -- comes last. */}
      <section className="rounded-md border border-border bg-surface p-3">
        <SetupInspectorPanel query={setupsQuery} />
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
          timeframe={timeframe}
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
