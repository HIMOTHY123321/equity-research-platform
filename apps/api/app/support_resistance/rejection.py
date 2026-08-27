"""Objective, deterministic rejection predicates. No subjective candlestick
pattern naming -- a rejection is exactly: the candle reached the zone, and
its close failed to hold beyond the zone's representative price.
"""

from __future__ import annotations

from app.schemas.market_data import Candle


def is_resistance_rejection(candle: Candle, representative_price: float) -> bool:
    """Candle failed to close convincingly above resistance."""
    return candle.close < representative_price


def is_support_rejection(candle: Candle, representative_price: float) -> bool:
    """Candle failed to close convincingly below support."""
    return candle.close > representative_price
