"""Detector inputs, and the frozen SetupContext snapshot (#18) that gets
attached to every candidate.

`DetectorInputs` bundles the four Phase 6 inputs -- Candles, FeatureSnapshot,
MarketStructureSnapshot (per timeframe), SupportResistanceSnapshot -- exactly
as received from the already-computed, already-lookahead-safe engines from
Phases 2-5. Detectors never recompute those engines' logic; they only read
the finished outputs plus the raw candle series for their own sequential
scans (see the ADR for why point-in-time indicator values, when a detector
needs them mid-history, are recomputed via the *same* pure functions those
engines use -- app.features.indicators -- rather than duplicated).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.features.indicators import ema, sma, true_range_series, wilder_atr_series
from app.features.schemas import FeatureSnapshot
from app.market_structure.schemas import MarketStructureSnapshot
from app.schemas.market_data import Candle, Timeframe
from app.setup_detection.config import SetupDetectionConfig
from app.setup_detection.schemas import MarketContext, SetupContext
from app.support_resistance.schemas import SupportResistanceSnapshot


@dataclass(frozen=True)
class DetectorInputs:
    symbol: str
    timeframe: Timeframe
    candles: list[Candle]  # completed, truncated to as_of, primary timeframe, full available history
    daily_candles: list[Candle]  # completed, truncated to as_of
    as_of: datetime
    feature_snapshot: FeatureSnapshot
    structure_by_timeframe: dict[Timeframe, MarketStructureSnapshot]
    levels_snapshot: SupportResistanceSnapshot
    config: SetupDetectionConfig
    market_context: Optional[MarketContext] = None


def build_setup_context(inputs: DetectorInputs, as_of: Optional[datetime] = None) -> SetupContext:
    """The "live" context: pulled directly from the already-computed
    snapshots passed into the engine, which are already anchored at
    `inputs.as_of`. Used whenever a candidate's detection instant is the
    same bar the top-level snapshots were computed for."""
    fs = inputs.feature_snapshot
    daily = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
    four_hour = inputs.structure_by_timeframe.get(Timeframe.FOUR_HOUR)
    one_hour = inputs.structure_by_timeframe.get(Timeframe.ONE_HOUR)
    levels = inputs.levels_snapshot

    return SetupContext(
        as_of=as_of or inputs.as_of,
        daily_structure=daily.trend.trend if daily else None,
        four_hour_structure=four_hour.trend.trend if four_hour else None,
        one_hour_structure=one_hour.trend.trend if one_hour else None,
        atr=fs.atr.value,
        rvol=fs.volume.relative_volume,
        ema20=fs.moving_averages.ema20.value,
        sma50=fs.moving_averages.sma50.value,
        sma200=fs.moving_averages.sma200.value,
        active_range_high=(inputs.structure_by_timeframe.get(inputs.timeframe) or daily).active_range.high
        if (inputs.structure_by_timeframe.get(inputs.timeframe) or daily)
        else None,
        active_range_low=(inputs.structure_by_timeframe.get(inputs.timeframe) or daily).active_range.low
        if (inputs.structure_by_timeframe.get(inputs.timeframe) or daily)
        else None,
        gap_percent=fs.gap.gap_percent,
        gap_direction=fs.gap.direction,
        nearest_support_price=levels.nearest_support.representative_price if levels.nearest_support else None,
        nearest_resistance_price=(
            levels.nearest_resistance.representative_price if levels.nearest_resistance else None
        ),
        market_context=inputs.market_context,
    )


def point_in_time_ema(candles: list[Candle], period: int, up_to_index: int) -> Optional[float]:
    """EMA using only `candles[:up_to_index + 1]` -- the same `ema()` the
    feature engine uses, just evaluated at an earlier point in the series.
    Reuses the real indicator math rather than duplicating it (#12)."""
    closes = [c.close for c in candles[: up_to_index + 1]]
    return ema(closes, period)


def point_in_time_sma(candles: list[Candle], period: int, up_to_index: int) -> Optional[float]:
    closes = [c.close for c in candles[: up_to_index + 1]]
    return sma(closes, period)


def point_in_time_atr(candles: list[Candle], period: int, up_to_index: int) -> Optional[float]:
    window = candles[: up_to_index + 1]
    if len(window) < period:
        return None
    highs = [c.high for c in window]
    lows = [c.low for c in window]
    closes = [c.close for c in window]
    series = wilder_atr_series(true_range_series(highs, lows, closes), period)
    return series[-1] if series else None
