"""Shared test helpers for the setup_detection suite.

Two data sources are used deliberately:

- `session(...)`/`multi_day(...)` build small, fully-controlled synthetic
  hourly candle sequences for testing exact deterministic behavior (anti-
  lookahead, tolerance boundaries, dedup) -- precision matters more than
  realism here.
- `load_real_candles(...)` replays a static, sanitized snapshot of real
  SPY/QQQ/NVDA candles captured from the live yfinance provider (#38) for
  realistic-market-behavior regression tests. No network access is ever
  required to run these tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.features.engine import compute_feature_snapshot
from app.market_structure.common import completed_only, truncate_to_as_of
from app.market_structure.engine import compute_market_structure_snapshot
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.config import DEFAULT_SETUP_DETECTION_CONFIG, SetupDetectionConfig
from app.setup_detection.context import DetectorInputs
from app.support_resistance.engine import compute_support_resistance_snapshot
from tests.conftest import et

SYMBOL = "TEST"
_FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "real_market_data.json"


def hour_bar(day, hour, high, low, open=None, close=None, volume=1000, month=8, year=2026):  # noqa: A002
    o = open if open is not None else (high + low) / 2
    c = close if close is not None else (high + low) / 2
    return Candle(
        symbol=SYMBOL,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(year, month, day, hour, 30),
        session=MarketSession.REGULAR,
        open=o,
        high=high,
        low=low,
        close=c,
        volume=volume,
    )


def flat_session(day, price=100.0, hours=range(10, 16), volume=1000, month=8, year=2026):
    """A quiet, flat trading day -- useful as filler history so a test's
    single engineered event is the only interesting thing in the series."""
    return [
        hour_bar(day, h, price + 0.5, price - 0.5, close=price, volume=volume, month=month, year=year)
        for h in hours
    ]


def build_inputs(
    candles: list[Candle],
    timeframe: Timeframe = Timeframe.ONE_HOUR,
    daily_candles: list[Candle] | None = None,
    as_of: datetime | None = None,
    config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG,
) -> DetectorInputs:
    """Runs the real Phase 3-5 engines over `candles` (exactly what the
    /setups route does) so detector tests exercise real, current
    FeatureSnapshot/MarketStructureSnapshot/SupportResistanceSnapshot
    shapes rather than hand-built stand-ins that could drift from them."""
    as_of = as_of or (candles[-1].timestamp + timedelta(minutes=1) if candles else datetime.now())
    daily = daily_candles if daily_candles is not None else _synthesize_daily(candles)

    truncated, _ = truncate_to_as_of(candles, as_of)
    completed = completed_only(truncated, as_of)
    daily_truncated, _ = truncate_to_as_of(daily, as_of)
    daily_completed = completed_only(daily_truncated, as_of)

    # Matches api/routes/market.py: compute_feature_snapshot gets the raw
    # truncated (not completed-only) daily series, since gap/session
    # detection specifically needs to see today's still-forming daily bar
    # (its `open` is fixed the instant the session starts -- see gap.py).
    feature_snapshot = compute_feature_snapshot(SYMBOL, timeframe, completed, daily_truncated, as_of)

    structure_by_timeframe = {
        Timeframe.ONE_DAY: compute_market_structure_snapshot(
            SYMBOL, Timeframe.ONE_DAY, daily_completed, as_of
        ),
        timeframe: compute_market_structure_snapshot(SYMBOL, timeframe, completed, as_of),
    }
    levels_snapshot = compute_support_resistance_snapshot(
        SYMBOL, timeframe, completed, daily_completed, structure_by_timeframe, as_of
    )

    return DetectorInputs(
        symbol=SYMBOL,
        timeframe=timeframe,
        candles=completed,
        daily_candles=daily_completed,
        as_of=as_of,
        feature_snapshot=feature_snapshot,
        structure_by_timeframe=structure_by_timeframe,
        levels_snapshot=levels_snapshot,
        config=config,
    )


def _synthesize_daily(candles: list[Candle]) -> list[Candle]:
    """Roll hourly test candles up into one daily bar per calendar day --
    a minimal stand-in so tests don't need to hand-author a parallel daily
    series for every hourly fixture."""
    from app.market_data.sessions import exchange_trading_date

    by_day: dict = {}
    for candle in candles:
        by_day.setdefault(exchange_trading_date(candle.timestamp), []).append(candle)

    daily = []
    for trading_date, day_candles in sorted(by_day.items()):
        day_candles = sorted(day_candles, key=lambda c: c.timestamp)
        daily.append(
            Candle(
                symbol=SYMBOL,
                timeframe=Timeframe.ONE_DAY,
                timestamp=datetime.combine(
                    trading_date, datetime.min.time(), tzinfo=day_candles[0].timestamp.tzinfo
                ),
                session=MarketSession.REGULAR,
                open=day_candles[0].open,
                high=max(c.high for c in day_candles),
                low=min(c.low for c in day_candles),
                close=day_candles[-1].close,
                volume=sum(c.volume for c in day_candles),
            )
        )
    return daily


def load_real_candles(key: str) -> list[Candle]:
    data = json.loads(_FIXTURE_PATH.read_text())
    rows = data[key]
    return [
        Candle(
            symbol=row["symbol"],
            timeframe=Timeframe(row["timeframe"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            session=MarketSession(row["session"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
        )
        for row in rows
    ]
