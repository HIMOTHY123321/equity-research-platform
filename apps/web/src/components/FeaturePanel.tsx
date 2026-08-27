import { Block, Row } from "@/components/PanelPrimitives";
import type { AsyncResource } from "@/hooks/useAsyncResource";
import {
  classificationColorClass,
  directionColorClass,
  formatPercent,
  formatPrice,
  formatRatio,
  formatVolume,
  percentColorClass,
} from "@/lib/format";
import type { FeatureSnapshot } from "@/lib/types";

/** Presentational only: fetching lives in useFeatures(), owned by
 * MarketWorkspace, so the same request can also feed the chart overlay. */
export function FeaturePanel({ query }: { query: AsyncResource<FeatureSnapshot> }) {
  const { data: snapshot, state, error } = query;

  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Loading features…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!snapshot) {
    return <div className="p-4 text-xs text-muted">No feature data.</div>;
  }

  const {
    previous_day,
    previous_week,
    gap,
    atr,
    moving_averages,
    volume,
    intraday_relative_volume,
    latest_candle,
    data_quality,
  } = snapshot;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Block title="PREVIOUS DAY">
          <Row label="High" value={formatPrice(previous_day.high)} />
          <Row label="Low" value={formatPrice(previous_day.low)} />
          <Row label="Close" value={formatPrice(previous_day.close)} />
          <Row
            label="Change"
            value={formatPercent(previous_day.percent_change)}
            valueClassName={percentColorClass(previous_day.percent_change)}
          />
        </Block>

        <Block title="PREVIOUS WEEK">
          <Row label="High" value={formatPrice(previous_week.high)} />
          <Row label="Low" value={formatPrice(previous_week.low)} />
          <Row label="Close" value={formatPrice(previous_week.close)} />
          <Row
            label="Change"
            value={formatPercent(previous_week.percent_change)}
            valueClassName={percentColorClass(previous_week.percent_change)}
          />
        </Block>

        <Block title="GAP">
          <Row label="Prev Close" value={formatPrice(gap.previous_close)} />
          <Row label="Session Open" value={formatPrice(gap.session_open)} />
          <Row
            label="Gap %"
            value={formatPercent(gap.gap_percent)}
            valueClassName={directionColorClass(gap.direction)}
          />
        </Block>

        <Block title={`ATR (${atr.period})`}>
          <Row label="Value" value={formatPrice(atr.value)} />
          <Row label="Method" value={atr.value === null ? "—" : atr.method} />
        </Block>

        <Block title="EMA 20">
          <Row label="Value" value={formatPrice(moving_averages.ema20.value)} />
          <Row
            label="Distance"
            value={formatPercent(moving_averages.ema20.distance_percent)}
            valueClassName={percentColorClass(moving_averages.ema20.distance_percent)}
          />
          <Row label="Position" value={moving_averages.ema20.position ?? "—"} />
        </Block>

        <Block title="SMA 50">
          <Row label="Value" value={formatPrice(moving_averages.sma50.value)} />
          <Row
            label="Distance"
            value={formatPercent(moving_averages.sma50.distance_percent)}
            valueClassName={percentColorClass(moving_averages.sma50.distance_percent)}
          />
          <Row label="Position" value={moving_averages.sma50.position ?? "—"} />
        </Block>

        <Block title="SMA 200">
          <Row label="Value" value={formatPrice(moving_averages.sma200.value)} />
          <Row
            label="Distance"
            value={formatPercent(moving_averages.sma200.distance_percent)}
            valueClassName={percentColorClass(moving_averages.sma200.distance_percent)}
          />
          <Row label="Position" value={moving_averages.sma200.position ?? "—"} />
        </Block>

        <Block title="RELATIVE VOLUME">
          <Row label="Current" value={formatVolume(volume.current_volume)} />
          <Row label="Average" value={formatVolume(volume.average_volume)} />
          <Row label="RVOL" value={formatRatio(volume.relative_volume)} />
          {volume.current_bar_is_partial && <Row label="Note" value="bar forming" />}
        </Block>

        {intraday_relative_volume.status === "ok" && (
          <Block title="INTRADAY RVOL">
            <Row
              label="Today (thru)"
              value={formatVolume(intraday_relative_volume.cumulative_volume_today)}
            />
            <Row
              label="Avg (thru)"
              value={formatVolume(intraday_relative_volume.cumulative_volume_reference_average)}
            />
            <Row label="RVOL" value={formatRatio(intraday_relative_volume.intraday_relative_volume)} />
          </Block>
        )}

        <Block title="LATEST CANDLE">
          <Row
            label="Classification"
            value={latest_candle.classification ?? "—"}
            valueClassName={classificationColorClass(latest_candle.classification)}
          />
          <Row
            label="Body %"
            value={
              latest_candle.body_percent_of_range === null
                ? "—"
                : `${latest_candle.body_percent_of_range.toFixed(1)}%`
            }
          />
          <Row label="Range" value={formatPrice(latest_candle.full_range)} />
        </Block>
      </div>

      {data_quality.warnings.length > 0 && (
        <p className="text-[11px] text-warning">{data_quality.warnings.join(" · ")}</p>
      )}
      <p className="text-[10px] text-muted">
        {data_quality.candle_count} candles · latest{" "}
        {data_quality.latest_candle_is_complete ? "complete" : "forming"}
      </p>
    </div>
  );
}
