"""Dataset provenance (#8). yfinance is a research/development feed, not
immutable institutional data (see docs/decisions/0006) -- every replay run
records exactly which candles it actually used, not just the symbol/range
that was requested.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.research.schemas import DatasetProvenance
from app.schemas.market_data import Candle


def build_dataset_provenance(
    provider: str,
    symbol: str,
    timeframe: str,
    requested_start: datetime,
    requested_end: datetime,
    candles: list[Candle],
) -> DatasetProvenance:
    digest_source = "|".join(
        f"{c.timestamp.isoformat()}:{c.open}:{c.high}:{c.low}:{c.close}:{c.volume}" for c in candles
    )
    data_hash = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:32]

    return DatasetProvenance(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        requested_start=requested_start,
        requested_end=requested_end,
        earliest_candle=candles[0].timestamp if candles else None,
        latest_candle=candles[-1].timestamp if candles else None,
        candle_count=len(candles),
        adjustment_mode="unadjusted",
        timezone="America/New_York",
        data_hash=data_hash,
    )
