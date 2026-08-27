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
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { swingClassificationAbbrev } from "@/lib/format";
import type {
  BreakOfStructureEvent,
  Candle,
  ChangeOfCharacterEvent,
  SetupCandidate,
  SwingPoint,
  Zone,
} from "@/lib/types";

const RESISTANCE_COLOR = "#ef4444";
const SUPPORT_COLOR = "#22c55e";
const CHOCH_COLOR = "#eab308";
const SETUP_COLOR = "#a78bfa";
const MAX_ZONES_DRAWN = 6;
const MAX_SETUP_MARKERS_DRAWN = 8;
// Uncapped defaults for structural pivots would draw one marker per
// confirmed swing (routinely 50-100+ on a full history) -- readable only
// with "all pivots" explicitly turned on.
const MAX_SWINGS_DRAWN_DEFAULT = 12;
const MAX_BOS_DRAWN_DEFAULT = 3;
const MAX_CHOCH_DRAWN_DEFAULT = 3;

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
  display = DEFAULT_CHART_DISPLAY_OPTIONS,
}: {
  candles: Candle[];
  structure?: StructureOverlay;
  zones?: ZoneOverlay;
  setups?: SetupCandidate[];
  display?: ChartDisplayOptions;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

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

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersApiRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    series.setData(
      candles.map((candle) => ({
        time: toUtcTimestamp(candle.timestamp),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

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

    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersApi.setMarkers(markers);
  }, [structure, setups, display]);

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

  return <div ref={containerRef} className="h-full w-full" />;
}
