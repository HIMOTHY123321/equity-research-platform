"""Turns each provider's raw bar shape into the internal Candle contract —
Alpaca's `{t,o,h,l,c,v}` dicts and yfinance's `(timestamp, row)` pairs both
land here, kept as separate functions per provider (never a shared "guess
the shape" parser) but sharing the same NormalizationResult/RejectedBar
containers and the same policy: malformed bars are never silently dropped —
every rejection is collected with a reason so the caller can log it loudly.
Duplicate timestamps are deduplicated (first occurrence wins) and the
result is always returned sorted ascending by time, regardless of the order
the provider sent them in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from app.market_data.sessions import classify_session
from app.schemas.market_data import Candle, Timeframe


@dataclass(frozen=True)
class RejectedBar:
    raw: dict
    reason: str


@dataclass(frozen=True)
class NormalizationResult:
    candles: list[Candle] = field(default_factory=list)
    rejected: list[RejectedBar] = field(default_factory=list)
    duplicates_dropped: int = 0


def _parse_timestamp(raw: str) -> datetime:
    # Alpaca sends RFC3339 UTC, e.g. "2024-01-02T14:30:00Z". Python 3.9's
    # datetime.fromisoformat doesn't accept the trailing "Z".
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def normalize_alpaca_bar(raw: dict, symbol: str, timeframe: Timeframe) -> Candle:
    """Normalize a single Alpaca bar dict. Raises on any malformed input."""
    timestamp = _parse_timestamp(raw["t"])
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        session=classify_session(timestamp, timeframe),
        open=raw["o"],
        high=raw["h"],
        low=raw["l"],
        close=raw["c"],
        volume=raw["v"],
    )


def normalize_alpaca_bars(
    raw_bars: list[dict], symbol: str, timeframe: Timeframe
) -> NormalizationResult:
    candles_by_timestamp: dict[datetime, Candle] = {}
    rejected: list[RejectedBar] = []
    duplicates_dropped = 0

    for raw in raw_bars:
        try:
            candle = normalize_alpaca_bar(raw, symbol, timeframe)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            rejected.append(RejectedBar(raw=raw, reason=str(exc)))
            continue

        if candle.timestamp in candles_by_timestamp:
            duplicates_dropped += 1
            continue
        candles_by_timestamp[candle.timestamp] = candle

    ordered = sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)
    return NormalizationResult(
        candles=ordered, rejected=rejected, duplicates_dropped=duplicates_dropped
    )


def normalize_yfinance_bar(timestamp: datetime, row, symbol: str, timeframe: Timeframe) -> Candle:
    """Normalize a single yfinance history row. `row` supports `[]` lookup —
    a pandas Series (from `df.iterrows()`) or a plain dict both work, which
    is what makes this testable without constructing a real DataFrame."""
    if timestamp.tzinfo is None:
        raise ValueError("yfinance timestamp must be timezone-aware")
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        session=classify_session(timestamp, timeframe),
        open=row["Open"],
        high=row["High"],
        low=row["Low"],
        close=row["Close"],
        volume=row["Volume"],
    )


def normalize_yfinance_bars(rows, symbol: str, timeframe: Timeframe) -> NormalizationResult:
    """`rows` is an iterable of (timestamp, row) pairs — a pandas DataFrame's
    `.iterrows()` yields exactly this shape, so callers can pass that
    directly; tests pass plain `(datetime, dict)` tuples."""
    candles_by_timestamp: dict[datetime, Candle] = {}
    rejected: list[RejectedBar] = []
    duplicates_dropped = 0

    for timestamp, row in rows:
        try:
            candle = normalize_yfinance_bar(timestamp, row, symbol, timeframe)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raw = {"timestamp": str(timestamp), **dict(row)}
            rejected.append(RejectedBar(raw=raw, reason=str(exc)))
            continue

        if candle.timestamp in candles_by_timestamp:
            duplicates_dropped += 1
            continue
        candles_by_timestamp[candle.timestamp] = candle

    ordered = sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)
    return NormalizationResult(
        candles=ordered, rejected=rejected, duplicates_dropped=duplicates_dropped
    )
