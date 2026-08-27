"""Deterministic categorical/numeric bucketing (#19) -- standardized enough
to compare across symbols later for historical analog search. No historical
performance is computed or attached here; this is pure feature-extraction.
"""

from __future__ import annotations

from typing import Optional

from app.market_structure.schemas import Direction
from app.setup_detection.context import SetupContext
from app.setup_detection.schemas import SetupFingerprint, SetupType

RVOL_BUCKET_EDGES = (0.5, 1.0, 1.5, 2.0, 3.0)
RVOL_BUCKET_LABELS = ("<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0-3.0", ">3.0")

DISTANCE_BUCKET_EDGES = (0.5, 1.0, 2.0, 3.0, 5.0)
DISTANCE_BUCKET_LABELS = ("0-0.5%", "0.5-1%", "1-2%", "2-3%", "3-5%", ">5%")


def _bucket(value: Optional[float], edges: tuple, labels: tuple) -> Optional[str]:
    if value is None:
        return None
    for edge, label in zip(edges, labels):
        if value <= edge:
            return label
    return labels[-1]


def _gap_state(gap_direction: Optional[str], gap_percent: Optional[float], min_gap_percent: float) -> str:
    if gap_direction is None or gap_percent is None or abs(gap_percent) < min_gap_percent:
        return "none"
    return gap_direction


def _distance_percent(price: Optional[float], reference: Optional[float]) -> Optional[float]:
    if price is None or reference is None or reference == 0:
        return None
    return abs(reference - price) / price * 100


def build_fingerprint(
    setup_type: SetupType,
    direction: Direction,
    context: SetupContext,
    reference_price: Optional[float],
    support_confluence: int,
    resistance_confluence: int,
    min_gap_percent: float,
) -> SetupFingerprint:
    return SetupFingerprint(
        setup_type=setup_type,
        direction=direction,
        daily_structure=context.daily_structure,
        four_hour_structure=context.four_hour_structure,
        one_hour_structure=context.one_hour_structure,
        rvol_bucket=_bucket(context.rvol, RVOL_BUCKET_EDGES, RVOL_BUCKET_LABELS),
        gap_state=_gap_state(context.gap_direction, context.gap_percent, min_gap_percent),
        distance_to_weekly_resistance_bucket=_bucket(
            _distance_percent(reference_price, context.nearest_resistance_price),
            DISTANCE_BUCKET_EDGES,
            DISTANCE_BUCKET_LABELS,
        ),
        distance_to_weekly_support_bucket=_bucket(
            _distance_percent(reference_price, context.nearest_support_price),
            DISTANCE_BUCKET_EDGES,
            DISTANCE_BUCKET_LABELS,
        ),
        support_confluence=support_confluence,
        resistance_confluence=resistance_confluence,
    )
