"""The single entry point: Candle[] -> FeatureSnapshot. This is the only
function anything outside app/features should call.

`primary_candles` drives everything timeframe-specific (ATR, moving
averages, rolling levels, volume, latest-candle, session). `daily_candles`
drives previous-day/previous-week/gap, since those have session/daily
semantics regardless of what chart timeframe is being viewed — when
`timeframe` is already ONE_DAY, callers should pass the same list for both.
Both series are defensively re-truncated to `as_of` here (see
app/features/common.py for the full as-of/no-lookahead policy).
"""

from __future__ import annotations

from datetime import datetime

from app.features.atr import compute_atr_feature
from app.features.candle_features import compute_candle_features
from app.features.common import is_candle_complete, truncate_to_as_of
from app.features.config import DEFAULT_FEATURE_CONFIG, FeatureConfig
from app.features.gap import compute_gap
from app.features.moving_averages import compute_moving_averages_bundle
from app.features.previous_period import compute_previous_day_levels, compute_previous_week_levels
from app.features.rolling import compute_rolling_levels
from app.features.schemas import DataQuality, FeatureSnapshot
from app.features.session_features import compute_session_features
from app.features.volume import compute_intraday_relative_volume, compute_volume_features
from app.schemas.market_data import Candle, Timeframe


def compute_feature_snapshot(
    symbol: str,
    timeframe: Timeframe,
    primary_candles: list[Candle],
    daily_candles: list[Candle],
    as_of: datetime,
    config: FeatureConfig = DEFAULT_FEATURE_CONFIG,
) -> FeatureSnapshot:
    primary, primary_dropped = truncate_to_as_of(primary_candles, as_of)
    daily, daily_dropped = truncate_to_as_of(daily_candles, as_of)

    warnings: list[str] = []
    if daily_dropped:
        warnings.append(f"Dropped {daily_dropped} daily candle(s) timestamped after as_of")

    data_quality = _build_data_quality(primary, timeframe, as_of, primary_dropped, warnings)

    return FeatureSnapshot(
        symbol=symbol,
        as_of=as_of,
        timeframe=timeframe,
        previous_day=compute_previous_day_levels(daily, as_of),
        previous_week=compute_previous_week_levels(daily, as_of),
        gap=compute_gap(daily, as_of),
        atr=compute_atr_feature(primary, config.atr_period),
        moving_averages=compute_moving_averages_bundle(primary, config),
        rolling_levels=compute_rolling_levels(primary, config),
        volume=compute_volume_features(primary, config.rvol_period, as_of),
        intraday_relative_volume=compute_intraday_relative_volume(
            primary, as_of, timeframe, config.intraday_rvol_lookback_days
        ),
        latest_candle=compute_candle_features(primary, as_of, config),
        session=compute_session_features(primary, as_of),
        data_quality=data_quality,
    )


def _build_data_quality(
    candles: list[Candle],
    timeframe: Timeframe,
    as_of: datetime,
    future_dropped: int,
    warnings: list[str],
) -> DataQuality:
    if future_dropped:
        warnings.append(f"Dropped {future_dropped} primary candle(s) timestamped after as_of")

    if not candles:
        warnings.append("No candles available")
        return DataQuality(
            source_timeframe=timeframe,
            candle_count=0,
            future_candles_dropped=future_dropped,
            warnings=warnings,
        )

    latest = candles[-1]
    return DataQuality(
        source_timeframe=timeframe,
        candle_count=len(candles),
        earliest_candle_timestamp=candles[0].timestamp,
        latest_candle_timestamp=latest.timestamp,
        latest_candle_is_complete=is_candle_complete(latest, as_of),
        latest_candle_session=latest.session,
        future_candles_dropped=future_dropped,
        warnings=warnings,
    )
