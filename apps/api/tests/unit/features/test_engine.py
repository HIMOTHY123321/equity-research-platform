"""Integration tests for the top-level FeatureSnapshot, with special focus on
lookahead-bias safety — the single most important property this package has
to guarantee, since the same engine will drive the backtester later.
"""

from datetime import timedelta

import pytest

from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from app.features.engine import compute_feature_snapshot
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle

TOLERANCE = 1e-9


def _weekday_daily_series(n: int, start_price: float = 100.0):
    """n consecutive weekday daily candles starting 2026-01-05 (a Monday)."""
    candles = []
    day = et(2026, 1, 5, 9, 30)
    price = start_price
    while len(candles) < n:
        if day.weekday() < 5:
            candles.append(
                make_candle(
                    timeframe=Timeframe.ONE_DAY,
                    timestamp=day,
                    session=MarketSession.REGULAR,
                    open=price,
                    high=price + 2,
                    low=price - 2,
                    close=price + 1,
                    volume=1_000_000 + len(candles) * 1000,
                )
            )
            price += 0.5
        day += timedelta(days=1)
    return candles


FULL_SERIES = _weekday_daily_series(260)


def test_full_snapshot_is_internally_consistent():
    as_of = FULL_SERIES[220].timestamp + timedelta(hours=2)
    candles = FULL_SERIES[:221]

    snapshot = compute_feature_snapshot("TEST", Timeframe.ONE_DAY, candles, candles, as_of)

    assert snapshot.symbol == "TEST"
    assert snapshot.previous_day.status == FeatureStatus.OK
    assert snapshot.previous_week.status == FeatureStatus.OK
    assert snapshot.gap.status == FeatureStatus.OK
    assert snapshot.atr.status == FeatureStatus.OK
    assert snapshot.moving_averages.ema20.status == FeatureStatus.OK
    assert snapshot.moving_averages.sma50.status == FeatureStatus.OK
    assert snapshot.moving_averages.sma200.status == FeatureStatus.OK
    assert snapshot.volume.status == FeatureStatus.OK
    assert snapshot.latest_candle.status == FeatureStatus.OK
    assert snapshot.session.status == FeatureStatus.OK
    assert snapshot.data_quality.candle_count == 221
    assert snapshot.data_quality.future_candles_dropped == 0


_VOLATILE_DATA_QUALITY_FIELDS = {"future_candles_dropped", "warnings"}


def _feature_values(snapshot):
    """Snapshot contents excluding the fields that legitimately differ based
    on how much future data the caller happened to pass in (dropped-count,
    warning text) — the actual computed features must still be identical."""
    return snapshot.model_dump(exclude={"data_quality": _VOLATILE_DATA_QUALITY_FIELDS})


def test_appending_future_candles_does_not_change_an_earlier_snapshot():
    as_of = FULL_SERIES[150].timestamp + timedelta(hours=2)

    snapshot_without_future = compute_feature_snapshot(
        "TEST", Timeframe.ONE_DAY, FULL_SERIES[:151], FULL_SERIES[:151], as_of
    )
    snapshot_with_future = compute_feature_snapshot(
        "TEST", Timeframe.ONE_DAY, FULL_SERIES, FULL_SERIES, as_of
    )

    assert _feature_values(snapshot_without_future) == _feature_values(snapshot_with_future)
    assert snapshot_without_future.data_quality.candle_count == snapshot_with_future.data_quality.candle_count


def test_engine_defensively_truncates_even_if_caller_forgot_to():
    as_of = FULL_SERIES[100].timestamp + timedelta(hours=2)

    truncated = compute_feature_snapshot(
        "TEST", Timeframe.ONE_DAY, FULL_SERIES[:101], FULL_SERIES[:101], as_of
    )
    # Caller passes the FULL series (including everything after as_of) by mistake.
    untruncated = compute_feature_snapshot("TEST", Timeframe.ONE_DAY, FULL_SERIES, FULL_SERIES, as_of)

    assert _feature_values(truncated) == _feature_values(untruncated)
    assert untruncated.data_quality.future_candles_dropped == len(FULL_SERIES) - 101


def test_previous_day_never_reflects_the_current_session():
    day = FULL_SERIES[50]
    next_day = FULL_SERIES[51]
    as_of = next_day.timestamp + timedelta(hours=1)

    snapshot = compute_feature_snapshot(
        "TEST", Timeframe.ONE_DAY, FULL_SERIES[:52], FULL_SERIES[:52], as_of
    )

    assert snapshot.previous_day.close == pytest.approx(day.close, abs=TOLERANCE)
    assert snapshot.previous_day.close != pytest.approx(next_day.close, abs=TOLERANCE)


def test_previous_week_never_reflects_the_partial_current_week():
    # as_of lands mid-week; the current (partial) week must never appear as
    # "previous week" no matter how much of it has already printed.
    as_of = FULL_SERIES[200].timestamp + timedelta(hours=1)
    snapshot = compute_feature_snapshot(
        "TEST", Timeframe.ONE_DAY, FULL_SERIES[:201], FULL_SERIES[:201], as_of
    )

    current_week = FULL_SERIES[200].timestamp.isocalendar()[:2]
    assert snapshot.previous_week.week_start_date.isocalendar()[:2] != current_week


def test_rolling_levels_excluding_current_never_include_the_last_bars_extreme():
    spiked = FULL_SERIES[:200] + [
        make_candle(
            timeframe=Timeframe.ONE_DAY,
            timestamp=FULL_SERIES[199].timestamp + timedelta(days=1),
            session=MarketSession.REGULAR,
            open=100,
            high=100_000,  # absurd spike, must not leak into "excluding_current"
            low=100,
            close=100,
            volume=1,
        )
    ]
    as_of = spiked[-1].timestamp + timedelta(hours=1)

    snapshot = compute_feature_snapshot("TEST", Timeframe.ONE_DAY, spiked, spiked, as_of)

    including = next(lvl for lvl in snapshot.rolling_levels.including_current if lvl.period == 5)
    excluding = next(lvl for lvl in snapshot.rolling_levels.excluding_current if lvl.period == 5)

    assert including.high == pytest.approx(100_000, abs=TOLERANCE)
    assert excluding.high != pytest.approx(100_000, abs=TOLERANCE)


def test_rvol_reference_average_excludes_the_current_observation():
    spiked = FULL_SERIES[:200] + [
        make_candle(
            timeframe=Timeframe.ONE_DAY,
            timestamp=FULL_SERIES[199].timestamp + timedelta(days=1),
            session=MarketSession.REGULAR,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=999_999_999,  # extreme current-bar volume
        )
    ]
    as_of = spiked[-1].timestamp + timedelta(hours=1)

    snapshot = compute_feature_snapshot("TEST", Timeframe.ONE_DAY, spiked, spiked, as_of, FeatureConfig())

    assert snapshot.volume.average_volume < 999_999_999
    assert snapshot.volume.relative_volume > 100  # hugely elevated, proves it wasn't self-averaged away
