"""Per-timeframe structure summaries with a simple, explicit alignment rule.

Each timeframe's snapshot is computed completely independently (its own
candles, its own as_of pass-through) — there is no shared state between
timeframes, so a historical as_of for one timeframe can never be influenced
by another's data. Alignment is a plain deterministic rule (daily and 4H
trend agree, and it's a real bullish/bearish trend, not ranging/insufficient)
— never an AI-decided combined bias, and no combined trade bias is produced.
"""

from __future__ import annotations

from datetime import datetime

from app.market_structure.config import DEFAULT_MARKET_STRUCTURE_CONFIG, MarketStructureConfig
from app.market_structure.engine import compute_market_structure_snapshot
from app.market_structure.schemas import (
    MultiTimeframeStructureSummary,
    TimeframeStructureSummary,
    TrendClass,
)
from app.schemas.market_data import Candle, Timeframe

_HIGHER_TIMEFRAME_PAIR = (Timeframe.ONE_DAY, Timeframe.FOUR_HOUR)
_DIRECTIONAL_TRENDS = {TrendClass.BULLISH, TrendClass.BEARISH}


def summarize_multi_timeframe_structure(
    symbol: str,
    candles_by_timeframe: dict[Timeframe, list[Candle]],
    as_of: datetime,
    config: MarketStructureConfig = DEFAULT_MARKET_STRUCTURE_CONFIG,
) -> MultiTimeframeStructureSummary:
    by_timeframe: dict[str, TimeframeStructureSummary] = {}
    trends: dict[Timeframe, TrendClass] = {}

    for timeframe, candles in candles_by_timeframe.items():
        snapshot = compute_market_structure_snapshot(symbol, timeframe, candles, as_of, config)
        by_timeframe[timeframe.value] = TimeframeStructureSummary(
            timeframe=timeframe,
            trend=snapshot.trend.trend,
            strength=snapshot.trend.strength,
        )
        trends[timeframe] = snapshot.trend.trend

    daily_trend = trends.get(_HIGHER_TIMEFRAME_PAIR[0])
    four_hour_trend = trends.get(_HIGHER_TIMEFRAME_PAIR[1])

    alignment = None
    if daily_trend is not None and four_hour_trend is not None:
        if daily_trend in _DIRECTIONAL_TRENDS and daily_trend == four_hour_trend:
            alignment = "aligned"
        else:
            alignment = "mixed"

    return MultiTimeframeStructureSummary(
        symbol=symbol,
        as_of=as_of,
        by_timeframe=by_timeframe,
        higher_timeframe_alignment=alignment,
    )
