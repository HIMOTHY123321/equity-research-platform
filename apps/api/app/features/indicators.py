"""Pure numeric indicator math — no Candle, no pydantic, no status handling.
Operates on plain float lists so it's trivial to hand-verify against
fixtures. Candle-aware wrappers (atr.py, moving_averages.py) sit on top.
"""

from __future__ import annotations

from typing import Optional


def sma(values: list[float], period: int) -> Optional[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[Optional[float]]:
    """Full EMA series, SMA-seeded at index `period - 1` (the standard/TradingView
    convention). Entries before the seed are None (insufficient history)."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return [None] * len(values)

    multiplier = 2 / (period + 1)
    result: list[Optional[float]] = [None] * (period - 1)
    seed = sum(values[:period]) / period
    result.append(seed)
    previous = seed
    for value in values[period:]:
        current = (value - previous) * multiplier + previous
        result.append(current)
        previous = current
    return result


def ema(values: list[float], period: int) -> Optional[float]:
    series = ema_series(values, period)
    return series[-1] if series else None


def true_range_series(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """TR[0] = high-low (no prior close to compare against); TR[i] for i>0 is
    max(high-low, |high-prev_close|, |low-prev_close|)."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, and closes must be the same length")

    true_ranges: list[float] = []
    for i in range(len(highs)):
        if i == 0:
            true_ranges.append(highs[i] - lows[i])
        else:
            prev_close = closes[i - 1]
            true_ranges.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - prev_close),
                    abs(lows[i] - prev_close),
                )
            )
    return true_ranges


def wilder_atr_series(true_ranges: list[float], period: int) -> list[Optional[float]]:
    """Wilder's smoothing: seed = SMA of the first `period` true ranges, then
    ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(true_ranges) < period:
        return [None] * len(true_ranges)

    result: list[Optional[float]] = [None] * (period - 1)
    seed = sum(true_ranges[:period]) / period
    result.append(seed)
    previous = seed
    for tr in true_ranges[period:]:
        current = (previous * (period - 1) + tr) / period
        result.append(current)
        previous = current
    return result
