"""Active/recent structural range: bounded by the single most recent
confirmed swing high and swing low. This is deliberately simple — not a
support/resistance clustering system, just a description of the current
structural box (that's a later phase).
"""

from __future__ import annotations

from typing import Optional

from app.market_structure.common import StructureStatus
from app.market_structure.schemas import ActiveRange, SwingPoint, SwingType


def compute_active_range(
    confirmed_swings: list[SwingPoint], latest_price: Optional[float]
) -> ActiveRange:
    highs = [s for s in confirmed_swings if s.type == SwingType.HIGH]
    lows = [s for s in confirmed_swings if s.type == SwingType.LOW]

    if not highs or not lows:
        return ActiveRange(status=StructureStatus.INSUFFICIENT_DATA)

    high = max(highs, key=lambda s: s.pivot_timestamp).price
    low = max(lows, key=lambda s: s.pivot_timestamp).price

    if low >= high:
        # The most recent low happens to sit above the most recent high
        # (can happen with unusual/thin data) -- no sensible box to report.
        return ActiveRange(status=StructureStatus.INSUFFICIENT_DATA)

    width = high - low
    position_percent = (latest_price - low) / width * 100 if latest_price is not None else None

    return ActiveRange(
        status=StructureStatus.OK,
        high=high,
        low=low,
        midpoint=(high + low) / 2,
        width=width,
        width_percent=width / low * 100,
        position_percent=position_percent,
    )
