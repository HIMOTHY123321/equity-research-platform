"""Two distinct, differently-named relative-volume concepts so they can never
be confused later:

- VolumeFeatures.relative_volume: current bar's volume vs. the average of the
  N *preceding* comparable bars (same timeframe). The current bar is never
  included in its own denominator.
- IntradayRelativeVolumeFeature: cumulative volume from today's regular-session
  open through the current bar's time-of-day, vs. the average of the same
  cumulative-through-that-time-of-day volume on the last N prior trading days.
  Only meaningful for intraday timeframes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.features.common import FeatureStatus, is_candle_complete
from app.features.schemas import IntradayRelativeVolumeFeature, VolumeFeatures
from app.market_data.sessions import EXCHANGE_TZ, exchange_trading_date
from app.schemas.market_data import Candle, MarketSession, Timeframe

_NON_INTRADAY_TIMEFRAMES = {Timeframe.ONE_DAY, Timeframe.ONE_WEEK}


def average_volume(candles: list[Candle], period: int) -> Optional[float]:
    """Average volume of the `period` bars immediately preceding the last bar
    in `candles` — the last bar itself is excluded from this average."""
    if len(candles) < period + 1:
        return None
    window = candles[-period - 1 : -1]
    return sum(c.volume for c in window) / period


def compute_volume_features(candles: list[Candle], period: int, as_of: datetime) -> VolumeFeatures:
    if not candles:
        return VolumeFeatures(status=FeatureStatus.INSUFFICIENT_HISTORY, average_volume_period=period)

    current = candles[-1]
    reference_average = average_volume(candles, period)
    current_bar_is_partial = not is_candle_complete(current, as_of)

    if reference_average is None:
        return VolumeFeatures(
            status=FeatureStatus.INSUFFICIENT_HISTORY,
            average_volume_period=period,
            current_volume=current.volume,
            current_bar_is_partial=current_bar_is_partial,
        )

    relative_volume = current.volume / reference_average if reference_average else None

    return VolumeFeatures(
        status=FeatureStatus.OK,
        average_volume_period=period,
        current_volume=current.volume,
        current_bar_is_partial=current_bar_is_partial,
        average_volume=reference_average,
        relative_volume=relative_volume,
    )


def compute_intraday_relative_volume(
    candles: list[Candle], as_of: datetime, timeframe: Timeframe, lookback_days: int
) -> IntradayRelativeVolumeFeature:
    if timeframe in _NON_INTRADAY_TIMEFRAMES:
        return IntradayRelativeVolumeFeature(
            status=FeatureStatus.NOT_APPLICABLE, lookback_days_requested=lookback_days
        )

    regular = [c for c in candles if c.session == MarketSession.REGULAR]
    today = exchange_trading_date(as_of)
    todays_bars = sorted(
        (c for c in regular if exchange_trading_date(c.timestamp) == today), key=lambda c: c.timestamp
    )
    if not todays_bars:
        return IntradayRelativeVolumeFeature(
            status=FeatureStatus.UNAVAILABLE, lookback_days_requested=lookback_days
        )

    cutoff_time = todays_bars[-1].timestamp.astimezone(EXCHANGE_TZ).time()
    cumulative_today = sum(c.volume for c in todays_bars)

    by_day: dict = {}
    for candle in regular:
        trading_date = exchange_trading_date(candle.timestamp)
        if trading_date < today:
            by_day.setdefault(trading_date, []).append(candle)

    historical_cumulatives = []
    for trading_date in sorted(by_day.keys(), reverse=True)[:lookback_days]:
        through_cutoff = [
            c for c in by_day[trading_date] if c.timestamp.astimezone(EXCHANGE_TZ).time() <= cutoff_time
        ]
        if through_cutoff:
            historical_cumulatives.append(sum(c.volume for c in through_cutoff))

    if not historical_cumulatives:
        return IntradayRelativeVolumeFeature(
            status=FeatureStatus.INSUFFICIENT_HISTORY,
            lookback_days_requested=lookback_days,
            as_of_time_of_day=cutoff_time.isoformat(timespec="minutes"),
            cumulative_volume_today=cumulative_today,
        )

    reference_average = sum(historical_cumulatives) / len(historical_cumulatives)
    intraday_rvol = cumulative_today / reference_average if reference_average else None

    return IntradayRelativeVolumeFeature(
        status=FeatureStatus.OK,
        lookback_days_requested=lookback_days,
        lookback_days_used=len(historical_cumulatives),
        as_of_time_of_day=cutoff_time.isoformat(timespec="minutes"),
        cumulative_volume_today=cumulative_today,
        cumulative_volume_reference_average=reference_average,
        intraday_relative_volume=intraday_rvol,
    )
