"""Deterministic nearest-zone helpers and each zone's relationship to the
current price. Broken and stale zones are never eligible for "nearest";
wrong-polarity zones are filtered by kind.
"""

from __future__ import annotations

from typing import Optional

from app.support_resistance.schemas import LevelKind, Position, PriceRelationship, Zone, ZoneLifecycle

_INELIGIBLE_FOR_NEAREST = frozenset({ZoneLifecycle.BROKEN, ZoneLifecycle.STALE})


def compute_price_relationship(
    lower_bound: float, upper_bound: float, current_price: float
) -> PriceRelationship:
    if lower_bound <= current_price <= upper_bound:
        return PriceRelationship(
            distance_absolute=0.0, distance_percent=0.0, position=Position.CONTAINS_PRICE
        )
    if current_price < lower_bound:
        distance = lower_bound - current_price
        return PriceRelationship(
            distance_absolute=distance,
            distance_percent=distance / current_price * 100,
            position=Position.ABOVE_PRICE,
        )
    distance = current_price - upper_bound
    return PriceRelationship(
        distance_absolute=distance,
        distance_percent=distance / current_price * 100,
        position=Position.BELOW_PRICE,
    )


def nearest_resistance_above(zones: list[Zone], current_price: float) -> Optional[Zone]:
    eligible = [
        z
        for z in zones
        if z.kind == LevelKind.RESISTANCE
        and z.lifecycle not in _INELIGIBLE_FOR_NEAREST
        and z.lower_bound > current_price
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda z: z.lower_bound - current_price)


def nearest_support_below(zones: list[Zone], current_price: float) -> Optional[Zone]:
    eligible = [
        z
        for z in zones
        if z.kind == LevelKind.SUPPORT
        and z.lifecycle not in _INELIGIBLE_FOR_NEAREST
        and z.upper_bound < current_price
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda z: z.upper_bound)


def nearest_active_zone(zones: list[Zone]) -> Optional[Zone]:
    eligible = [
        z for z in zones if z.lifecycle not in _INELIGIBLE_FOR_NEAREST and z.price_relationship is not None
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda z: z.price_relationship.distance_absolute)
