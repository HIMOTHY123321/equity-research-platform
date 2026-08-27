import pytest

from app.support_resistance.nearest import (
    compute_price_relationship,
    nearest_active_zone,
    nearest_resistance_above,
    nearest_support_below,
)
from app.support_resistance.schemas import (
    ConfluenceInfo,
    InteractionSummary,
    LevelKind,
    Position,
    StrengthBreakdown,
    Zone,
    ZoneFreshness,
    ZoneLifecycle,
)
from tests.conftest import et

TOLERANCE = 1e-9


def zone(kind, lower, upper, lifecycle=ZoneLifecycle.ACTIVE, strength_total=50.0, current_price=None):
    price_relationship = (
        compute_price_relationship(lower, upper, current_price) if current_price is not None else None
    )
    return Zone(
        id=f"zone:{kind.value}:{lower}-{upper}",
        kind=kind,
        lower_bound=lower,
        upper_bound=upper,
        representative_price=(lower + upper) / 2,
        member_levels=[],
        evidence=[],
        confluence=ConfluenceInfo(source_count=1, timeframe_count=1, source_types=[], timeframes=[]),
        known_at=et(2026, 8, 17, 9, 30),
        interactions=[],
        interaction_summary=InteractionSummary(independent_touches=0, rejections=0, wick_breaches=0),
        break_event=None,
        lifecycle=lifecycle,
        strength=StrengthBreakdown(
            source_score=strength_total,
            confluence_score=0,
            interaction_score=0,
            recency_score=0,
            total=strength_total,
        ),
        freshness=ZoneFreshness(),
        price_relationship=price_relationship,
    )


# ---- price relationship -----------------------------------------------------


def test_price_below_zone():
    rel = compute_price_relationship(190, 195, current_price=180)
    assert rel.position == Position.ABOVE_PRICE
    assert rel.distance_absolute == pytest.approx(10, abs=TOLERANCE)


def test_price_above_zone():
    rel = compute_price_relationship(190, 195, current_price=200)
    assert rel.position == Position.BELOW_PRICE
    assert rel.distance_absolute == pytest.approx(5, abs=TOLERANCE)


def test_price_inside_zone():
    rel = compute_price_relationship(190, 195, current_price=192)
    assert rel.position == Position.CONTAINS_PRICE
    assert rel.distance_absolute == pytest.approx(0, abs=TOLERANCE)


# ---- nearest helpers ---------------------------------------------------------


def test_nearest_resistance_above():
    zones = [
        zone(LevelKind.RESISTANCE, 200, 201, current_price=190),
        zone(LevelKind.RESISTANCE, 192, 193, current_price=190),  # closer
    ]
    result = nearest_resistance_above(zones, 190)
    assert result.lower_bound == pytest.approx(192, abs=TOLERANCE)


def test_nearest_support_below():
    zones = [
        zone(LevelKind.SUPPORT, 170, 171, current_price=190),
        zone(LevelKind.SUPPORT, 185, 186, current_price=190),  # closer
    ]
    result = nearest_support_below(zones, 190)
    assert result.upper_bound == pytest.approx(186, abs=TOLERANCE)


def test_broken_zones_ignored():
    zones = [
        zone(LevelKind.RESISTANCE, 191, 192, lifecycle=ZoneLifecycle.BROKEN, current_price=190),
        zone(LevelKind.RESISTANCE, 200, 201, current_price=190),
    ]
    result = nearest_resistance_above(zones, 190)
    assert result.lower_bound == pytest.approx(200, abs=TOLERANCE)


def test_stale_zones_ignored():
    zones = [
        zone(LevelKind.RESISTANCE, 191, 192, lifecycle=ZoneLifecycle.STALE, current_price=190),
        zone(LevelKind.RESISTANCE, 200, 201, current_price=190),
    ]
    result = nearest_resistance_above(zones, 190)
    assert result.lower_bound == pytest.approx(200, abs=TOLERANCE)


def test_wrong_polarity_ignored():
    zones = [zone(LevelKind.SUPPORT, 192, 193, current_price=190)]
    assert nearest_resistance_above(zones, 190) is None


def test_no_eligible_zone_returns_none():
    zones = [zone(LevelKind.RESISTANCE, 191, 192, lifecycle=ZoneLifecycle.BROKEN, current_price=190)]
    assert nearest_resistance_above(zones, 190) is None


def test_closer_weak_zone_beats_farther_strong_zone_for_nearest():
    zones = [
        zone(LevelKind.RESISTANCE, 191, 192, strength_total=20, current_price=190),
        zone(LevelKind.RESISTANCE, 210, 211, strength_total=95, current_price=190),
    ]
    # "nearest" is purely distance-based -- strength never overrides proximity.
    result = nearest_resistance_above(zones, 190)
    assert result.lower_bound == pytest.approx(191, abs=TOLERANCE)


def test_nearest_active_zone_can_be_support_or_resistance():
    zones = [
        zone(LevelKind.SUPPORT, 180, 181, current_price=190),
        zone(LevelKind.RESISTANCE, 191, 192, current_price=190),  # closer overall
    ]
    result = nearest_active_zone(zones)
    assert result.kind == LevelKind.RESISTANCE
