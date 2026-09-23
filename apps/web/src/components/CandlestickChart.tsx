"use client";

import {
  CandlestickSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LogicalRange,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { countPrependedCandles, shiftLogicalRange } from "@/lib/chartHistoryMerge";
import { liveCandleMatchesSelection, resolveLiveCandleAction } from "@/lib/chartLiveMerge";
import { formatEnumLabel, formatExchangeTimestamp, swingClassificationAbbrev } from "@/lib/format";
import type {
  BreakOfStructureEvent,
  Candle,
  ChangeOfCharacterEvent,
  ForwardForecast,
  LiveCandle,
  SetupCandidate,
  SwingPoint,
  Zone,
} from "@/lib/types";

const RESISTANCE_COLOR = "#ef4444";
const SUPPORT_COLOR = "#22c55e";
const CHOCH_COLOR = "#eab308";
const SETUP_COLOR = "#a78bfa";
const FORECAST_COLOR = "#38bdf8";
const MAX_ZONES_DRAWN = 6;
const MAX_SETUP_MARKERS_DRAWN = 8;
// Uncapped defaults for structural pivots would draw one marker per
// confirmed swing (routinely 50-100+ on a full history) -- readable only
// with "all pivots" explicitly turned on.
const MAX_SWINGS_DRAWN_DEFAULT = 12;
const MAX_BOS_DRAWN_DEFAULT = 3;
const MAX_CHOCH_DRAWN_DEFAULT = 3;
// (FINAL TERMINAL POLISH PASS #1) How close to the start of the loaded
// series (in bars) the visible range must get before an older-history page
// is requested -- close enough that the user never visibly runs out of
// data while panning, far enough that a single page load stays ahead of it.
const OLDER_HISTORY_TRIGGER_THRESHOLD_BARS = 20;

export interface ChartDisplayOptions {
  structure: boolean;
  supportResistance: boolean;
  setups: boolean;
  allPivots: boolean;
}

export const DEFAULT_CHART_DISPLAY_OPTIONS: ChartDisplayOptions = {
  structure: true,
  supportResistance: true,
  setups: true,
  allPivots: false,
};

function toUtcTimestamp(isoTimestamp: string): UTCTimestamp {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000) as UTCTimestamp;
}

export interface StructureOverlay {
  swings: SwingPoint[];
  breaksOfStructure: BreakOfStructureEvent[];
  changesOfCharacter: ChangeOfCharacterEvent[];
}

export interface ZoneOverlay {
  support: Zone[];
  resistance: Zone[];
}

const SETUP_TYPE_MARKER_ABBREV: Record<string, string> = {
  previous_day_high_breakout: "PDH",
  previous_day_low_breakdown: "PDL",
  previous_week_high_breakout: "PWH",
  previous_week_low_breakdown: "PWL",
  breakout_retest: "RETEST",
  wick_failed_breakout: "FAIL",
  confirmed_breakout_failure: "FAIL",
  support_reclaim: "RECLAIM",
  resistance_rejection: "REJECT",
  gap_continuation: "GAP",
  gap_fill: "FILL",
  bullish_liquidity_sweep: "SWEEP",
  bearish_liquidity_sweep: "SWEEP",
  moving_average_reclaim: "MA",
  trend_pullback: "PULLBACK",
  range_breakout: "RANGE",
};

/**
 * Pure rendering component: it only ever receives already-fetched data as
 * props. Fetching, loading, and error states are the caller's job (see
 * MarketWorkspace + the useXyz hooks). Structural markers are placed at
 * `pivot_timestamp`/`break_timestamp` -- the moment the event actually
 * happened -- never at `confirmed_at`, so the chart never visually implies
 * a swing/break was known before it was confirmed.
 */
export function CandlestickChart({
  candles,
  structure,
  zones,
  setups,
  forecasts,
  liveCandle,
  display = DEFAULT_CHART_DISPLAY_OPTIONS,
  symbol,
  timeframe,
  onNeedOlderHistory,
}: {
  candles: Candle[];
  structure?: StructureOverlay;
  zones?: ZoneOverlay;
  setups?: SetupCandidate[];
  forecasts?: ForwardForecast[];
  /** Phase 12.1 (#X): the current forming bar, supplied by the caller via
   * useLiveSymbol -- updates the chart's rightmost candle automatically,
   * every time a new quote arrives, with no refresh. Purely visual: never
   * fed back into `candles`, never touches structure/setup computation.
   *
   * Hardening pass: `candles` (REST) and `liveCandle` (WS overlay) are two
   * independent async sources with no ordering guarantee against each
   * other's *data* -- only render order. `latestSeriesTimeRef` (set
   * whenever `candles` is (re)loaded into the series) is the single source
   * of truth for "what's the newest time already in the series"; every
   * `series.update()` call is gated against it so an older/stale live tick
   * can never be handed to lightweight-charts as an update to already-newer
   * data (which throws "Cannot update oldest data" rather than failing
   * gracefully). */
  liveCandle?: LiveCandle | null;
  display?: ChartDisplayOptions;
  /** The symbol/timeframe this chart is currently displaying -- compared
   * against `liveCandle.symbol`/`.timeframe` so a stale overlay object still
   * in flight from the *previous* selection can never leak onto the new
   * one (§13), even though `liveCandle` itself changed identity. */
  symbol: string;
  timeframe: string;
  /** (FINAL TERMINAL POLISH PASS #1) Called when the visible range pans
   * near the start of the currently-loaded series -- the caller (
   * MarketWorkspace) owns the request-in-flight guard and exhaustion state;
   * this component only ever signals "the user is looking near the edge",
   * never fetches or tracks pagination state itself. */
  onNeedOlderHistory?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const candlesRef = useRef<Candle[]>(candles);
  useEffect(() => {
    candlesRef.current = candles;
  }, [candles]);
  // Always reads the latest callback without forcing the range-change
  // subscription (attached once, at chart creation) to be torn down and
  // reattached every time the caller passes a new function identity.
  const onNeedOlderHistoryRef = useRef(onNeedOlderHistory);
  useEffect(() => {
    onNeedOlderHistoryRef.current = onNeedOlderHistory;
  }, [onNeedOlderHistory]);
  // The previous render's ascending-sorted candles -- compared against the
  // next set to detect a pure older-history prepend (see the `candles`
  // effect below) vs. a fresh symbol/timeframe/range load.
  const prevSortedCandlesRef = useRef<Candle[]>([]);
  // The newest UTCTimestamp actually committed to the series -- reset every
  // time `candles` is reloaded (new symbol/timeframe, or a refetch that
  // advanced the authoritative newest bar), read by the liveCandle effect
  // below to reject stale/out-of-order updates instead of crashing.
  const latestSeriesTimeRef = useRef<UTCTimestamp | null>(null);
  const forecastsRef = useRef<ForwardForecast[]>(forecasts ?? []);
  useEffect(() => {
    forecastsRef.current = forecasts ?? [];
  }, [forecasts]);
  // Crosshair-hover readout (#L): the x-axis itself stays uncluttered
  // (lightweight-charts' own abbreviated tick labels); the full
  // `YYYY-MM-DD HH:mm:ss EST/EDT` timestamp only ever appears here, on
  // hover/selection -- never as a current-time label for a historical bar.
  const [hoveredTimestamp, setHoveredTimestamp] = useState<string | null>(null);
  // Phase 12.1 (#X): forecast marker tooltip -- ticker/id/created/
  // market-as-of/horizon/state/resolution, shown when hovering the bar a
  // forecast was locked against.
  const [hoveredForecast, setHoveredForecast] = useState<ForwardForecast | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#8b93a3",
        fontFamily: "var(--font-geist-mono), monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1a1f2b" },
        horzLines: { color: "#1a1f2b" },
      },
      timeScale: { borderColor: "#232935" },
      rightPriceScale: { borderColor: "#232935" },
      crosshair: { mode: 0 },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;
    markersApiRef.current = createSeriesMarkers(series, []);

    const handleCrosshairMove = (param: { time?: Time }) => {
      if (param.time === undefined) {
        setHoveredTimestamp(null);
        setHoveredForecast(null);
        return;
      }
      const seconds = param.time as number;
      const candle = candlesRef.current.find((c) => Math.floor(new Date(c.timestamp).getTime() / 1000) === seconds);
      setHoveredTimestamp(candle?.timestamp ?? null);
      const forecast = forecastsRef.current.find(
        (f) => Math.floor(new Date(f.market_as_of).getTime() / 1000) === seconds,
      );
      setHoveredForecast(forecast ?? null);
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    // (FINAL TERMINAL POLISH PASS #1) Attached once, here, so it's never
    // re-subscribed on every render -- always calls the *latest* callback
    // via the ref, never a stale closure over the prop from mount time.
    const handleVisibleLogicalRangeChange = (range: LogicalRange | null) => {
      if (!range) return;
      if (range.from <= OLDER_HISTORY_TRIGGER_THRESHOLD_BARS) {
        onNeedOlderHistoryRef.current?.();
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersApiRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series) return;

    const sorted = [...candles].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    );

    // (FINAL TERMINAL POLISH PASS #1) A pan-left pagination page prepends
    // older bars behind everything the user is already looking at -- the
    // viewport must NOT jump. Detected purely from data shape (never a
    // separate "is this a prepend" flag threaded through props), so it's
    // correct regardless of *why* `candles` grew this way.
    const prependCount = countPrependedCandles(prevSortedCandlesRef.current, sorted);
    const preservedRange = prependCount > 0 ? chart?.timeScale().getVisibleLogicalRange() ?? null : null;

    series.setData(
      sorted.map((candle) => ({
        time: toUtcTimestamp(candle.timestamp),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    // The authoritative newest bar just (re)loaded from REST is always the
    // floor for what a live update may touch -- reset on every load, never
    // carried over from a previous symbol/timeframe/refetch.
    latestSeriesTimeRef.current = sorted.length
      ? toUtcTimestamp(sorted[sorted.length - 1].timestamp)
      : null;

    if (preservedRange) {
      // Every already-displayed bar's logical index shifted right by
      // exactly `prependCount` -- shifting the saved range by the same
      // amount keeps the same candles in view, no visual jump.
      chart?.timeScale().setVisibleLogicalRange(shiftLogicalRange(preservedRange, prependCount));
    } else {
      // Fresh symbol/timeframe/range load (not a prepend) -- fitting the
      // whole series is the correct, existing behavior here.
      chart?.timeScale().fitContent();
    }

    prevSortedCandlesRef.current = sorted;
  }, [candles]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !liveCandle) return;
    // A liveCandle object for the *previous* symbol/timeframe selection can
    // still be in flight (async) after the user has already switched --
    // never let it leak onto the new chart (§13), even momentarily.
    if (!liveCandleMatchesSelection(liveCandle, symbol, timeframe)) return;

    const liveTime = toUtcTimestamp(liveCandle.timestamp);
    const action = resolveLiveCandleAction(liveTime, latestSeriesTimeRef.current);
    if (action === "ignore") return;
    // Purely visual (#G): overlays the forming bar onto the chart via
    // lightweight-charts' own last-bar update -- never appended to
    // `candles`, never touched by structure/setup detection, which only
    // ever sees what get_candles() authoritatively returns. `action` is
    // "update" (equal time, same bar) or "append" (strictly newer, a new
    // forming bar) -- lightweight-charts' own `series.update()` handles
    // both natively; only "ignore" (a stale/out-of-order tick) is a case
    // this component must reject itself.
    series.update({
      time: liveTime,
      open: liveCandle.open,
      high: liveCandle.high,
      low: liveCandle.low,
      close: liveCandle.close,
    });
    latestSeriesTimeRef.current = liveTime;
  }, [liveCandle, symbol, timeframe]);

  useEffect(() => {
    const markersApi = markersApiRef.current;
    if (!markersApi) return;

    const markers: SeriesMarker<Time>[] = [];

    if (display.structure) {
      const allSwings = [...(structure?.swings ?? [])].sort(
        (a, b) => new Date(a.pivot_timestamp).getTime() - new Date(b.pivot_timestamp).getTime(),
      );
      const swingsToShow = display.allPivots ? allSwings : allSwings.slice(-MAX_SWINGS_DRAWN_DEFAULT);
      for (const swing of swingsToShow) {
        const isHigh = swing.type === "high";
        const abbrev = swingClassificationAbbrev(swing.classification);
        markers.push({
          time: toUtcTimestamp(swing.pivot_timestamp),
          position: isHigh ? "aboveBar" : "belowBar",
          shape: "circle",
          color: isHigh ? RESISTANCE_COLOR : SUPPORT_COLOR,
          text: abbrev === "—" ? (isHigh ? "SH" : "SL") : abbrev,
        });
      }

      const allBos = [...(structure?.breaksOfStructure ?? [])].sort(
        (a, b) => new Date(a.break_timestamp).getTime() - new Date(b.break_timestamp).getTime(),
      );
      const bosToShow = display.allPivots ? allBos : allBos.slice(-MAX_BOS_DRAWN_DEFAULT);
      for (const bos of bosToShow) {
        const bullish = bos.direction === "bullish";
        markers.push({
          time: toUtcTimestamp(bos.break_timestamp),
          position: bullish ? "belowBar" : "aboveBar",
          shape: bullish ? "arrowUp" : "arrowDown",
          color: bullish ? SUPPORT_COLOR : RESISTANCE_COLOR,
          text: "BOS",
        });
      }

      const allChoch = [...(structure?.changesOfCharacter ?? [])].sort(
        (a, b) => new Date(a.break_timestamp).getTime() - new Date(b.break_timestamp).getTime(),
      );
      const chochToShow = display.allPivots ? allChoch : allChoch.slice(-MAX_CHOCH_DRAWN_DEFAULT);
      for (const choch of chochToShow) {
        const bullish = choch.direction === "bullish";
        markers.push({
          time: toUtcTimestamp(choch.break_timestamp),
          position: bullish ? "belowBar" : "aboveBar",
          shape: "square",
          color: CHOCH_COLOR,
          text: "CHOCH",
        });
      }
    }

    // Restrained (#34): only live setups (qualified/candidate/triggered),
    // never rejected ones -- near-misses belong in the Setup Inspector, not
    // cluttering the chart. Capped the same way zone lines are.
    if (display.setups) {
      const liveSetups = (setups ?? [])
        .filter((s) => s.current_state === "qualified" || s.current_state === "candidate" || s.current_state === "triggered")
        .slice(0, MAX_SETUP_MARKERS_DRAWN);
      for (const setup of liveSetups) {
        const bullish = setup.direction === "bullish";
        markers.push({
          time: toUtcTimestamp(setup.candidate_candle_timestamp),
          position: bullish ? "belowBar" : "aboveBar",
          shape: setup.current_state === "candidate" ? "circle" : "square",
          color: SETUP_COLOR,
          text: SETUP_TYPE_MARKER_ABBREV[setup.setup_type] ?? "SETUP",
        });
      }
    }

    // Phase 12 (#L): forecast markers at `market_as_of` -- the instant the
    // forecast was locked, never `created_at`/a current-time label. Full
    // created_at/market_as_of/resolution timestamps are surfaced via the
    // crosshair-hover readout below, not printed on the marker itself.
    for (const forecast of forecasts ?? []) {
      markers.push({
        time: toUtcTimestamp(forecast.market_as_of),
        position: "inBar",
        shape: forecast.status === "abstained" ? "circle" : "square",
        color: FORECAST_COLOR,
        text: forecast.status === "abstained" ? "ABSTAIN" : "FCST",
      });
    }

    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersApi.setMarkers(markers);
  }, [structure, setups, forecasts, display]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    if (!display.supportResistance) return;

    // Restrained: only the strongest few zones, so the chart stays readable
    // rather than turning into a wall of lines.
    const zoneLimit = display.allPivots ? Infinity : MAX_ZONES_DRAWN;
    const allZones = [...(zones?.resistance ?? []), ...(zones?.support ?? [])]
      .slice()
      .sort((a, b) => b.strength.total - a.strength.total)
      .slice(0, zoneLimit);

    for (const zone of allZones) {
      const color = zone.kind === "resistance" ? RESISTANCE_COLOR : SUPPORT_COLOR;
      const label = `${zone.kind === "resistance" ? "R" : "S"} ${zone.strength.total.toFixed(0)}`;
      priceLinesRef.current.push(
        series.createPriceLine({
          price: zone.upper_bound,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: label,
        }),
      );
      if (zone.upper_bound !== zone.lower_bound) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: zone.lower_bound,
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
            title: "",
          }),
        );
      }
    }
  }, [zones, display]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {hoveredTimestamp && (
        <div className="pointer-events-none absolute left-2 top-2 rounded border border-border bg-surface/90 px-2 py-1 font-mono text-[11px] text-foreground">
          {formatExchangeTimestamp(hoveredTimestamp)}
        </div>
      )}
      {hoveredForecast && (
        <div className="pointer-events-none absolute left-2 top-9 max-w-[260px] space-y-0.5 rounded border border-border bg-surface/95 px-2 py-1.5 font-mono text-[10px] text-foreground">
          <div className="font-semibold text-accent">
            {hoveredForecast.symbol} · {formatEnumLabel(hoveredForecast.forecast_category)}
          </div>
          <div className="text-muted">ID: {hoveredForecast.forecast_id.slice(0, 12)}…</div>
          <div className="text-muted">Created: {formatExchangeTimestamp(hoveredForecast.created_at)}</div>
          <div className="text-muted">As-of: {formatExchangeTimestamp(hoveredForecast.market_as_of)}</div>
          <div className="text-muted">Horizon: {hoveredForecast.forecast_horizon_bars} bars</div>
          <div>State: {formatEnumLabel(hoveredForecast.status)}</div>
          {hoveredForecast.forecast_value && <div>Value: {formatEnumLabel(hoveredForecast.forecast_value)}</div>}
        </div>
      )}
    </div>
  );
}
