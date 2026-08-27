"""Typed feature outputs. Every group carries its own `status` so a missing
value is always explicit — never a fabricated 0.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.features.common import FeatureStatus
from app.schemas.market_data import MarketSession, Timeframe


class PreviousDayLevels(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    trading_date: Optional[date] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    range: Optional[float] = None
    percent_change: Optional[float] = None


class PreviousWeekLevels(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    week_start_date: Optional[date] = None
    week_end_date: Optional[date] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    range: Optional[float] = None
    percent_change: Optional[float] = None
    trading_days_counted: int = 0


class GapFeature(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    previous_close: Optional[float] = None
    session_open: Optional[float] = None
    gap_absolute: Optional[float] = None
    gap_percent: Optional[float] = None
    direction: Optional[str] = None


class ATRFeature(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    period: int
    method: str = "wilder"
    value: Optional[float] = None


class MovingAverageFeature(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    type: str
    period: int
    value: Optional[float] = None
    distance_absolute: Optional[float] = None
    distance_percent: Optional[float] = None
    position: Optional[str] = None


class MovingAveragesBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    ema20: MovingAverageFeature
    sma50: MovingAverageFeature
    sma200: MovingAverageFeature


class RollingLevel(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    period: int
    include_current: bool
    high: Optional[float] = None
    low: Optional[float] = None


class RollingLevels(BaseModel):
    model_config = ConfigDict(frozen=True)

    including_current: list[RollingLevel]
    excluding_current: list[RollingLevel]


class VolumeFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    average_volume_period: int
    current_volume: Optional[float] = None
    current_bar_is_partial: bool = False
    average_volume: Optional[float] = None
    relative_volume: Optional[float] = None


class IntradayRelativeVolumeFeature(BaseModel):
    """Distinct from VolumeFeatures.relative_volume: compares cumulative volume
    through the same time-of-day across recent sessions, not whole-bar volume
    against a whole-bar historical average."""

    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    lookback_days_requested: int
    lookback_days_used: int = 0
    as_of_time_of_day: Optional[str] = None
    cumulative_volume_today: Optional[float] = None
    cumulative_volume_reference_average: Optional[float] = None
    intraday_relative_volume: Optional[float] = None


class CandleFeatures(BaseModel):
    """Computed from the latest *completed* candle, not a still-forming one."""

    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    timestamp: Optional[datetime] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    body_size: Optional[float] = None
    full_range: Optional[float] = None
    upper_wick: Optional[float] = None
    lower_wick: Optional[float] = None
    body_percent_of_range: Optional[float] = None
    classification: Optional[str] = None


class SessionFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FeatureStatus
    session_open: Optional[float] = None
    session_high_so_far: Optional[float] = None
    session_low_so_far: Optional[float] = None
    session_range: Optional[float] = None
    latest_price: Optional[float] = None
    distance_from_high_absolute: Optional[float] = None
    distance_from_high_percent: Optional[float] = None
    distance_from_low_absolute: Optional[float] = None
    distance_from_low_percent: Optional[float] = None


class DataQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_timeframe: Timeframe
    candle_count: int
    earliest_candle_timestamp: Optional[datetime] = None
    latest_candle_timestamp: Optional[datetime] = None
    latest_candle_is_complete: bool = False
    latest_candle_session: Optional[MarketSession] = None
    future_candles_dropped: int = 0
    warnings: list[str] = []


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: datetime
    timeframe: Timeframe

    previous_day: PreviousDayLevels
    previous_week: PreviousWeekLevels
    gap: GapFeature
    atr: ATRFeature
    moving_averages: MovingAveragesBundle
    rolling_levels: RollingLevels
    volume: VolumeFeatures
    intraday_relative_volume: IntradayRelativeVolumeFeature
    latest_candle: CandleFeatures
    session: SessionFeatures
    data_quality: DataQuality
