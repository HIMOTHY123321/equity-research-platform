"""Shared, reusable ConflictCheck builders (#20). A conflict is
informational -- it never blocks qualification on its own (that's what hard
EvidenceChecks are for, see qualification.py) -- but it's always recorded
and always structured, never a bare string.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.features.schemas import DataQuality
from app.market_structure.schemas import Direction, MarketStructureSnapshot, StructureDataQuality, TrendClass
from app.setup_detection.schemas import ConflictCheck, ConflictSeverity
from app.support_resistance.schemas import SupportResistanceSnapshot


def conflict_if_higher_timeframe_opposed(
    direction: Direction,
    structure: Optional[MarketStructureSnapshot],
    timeframe_label: str,
) -> Optional[ConflictCheck]:
    if structure is None:
        return None
    opposing_trend = TrendClass.BEARISH if direction == Direction.BULLISH else TrendClass.BULLISH
    if structure.trend.trend != opposing_trend:
        return None
    return ConflictCheck(
        code=f"{timeframe_label}_structure_opposed",
        label=f"{timeframe_label.upper()} structure is {structure.trend.trend.value}",
        severity=ConflictSeverity.MAJOR,
        source=f"structure.{timeframe_label}.trend",
    )


def conflict_if_opposing_zone_nearby(
    direction: Direction,
    reference_price: Optional[float],
    levels: SupportResistanceSnapshot,
    proximity_percent: float,
) -> Optional[ConflictCheck]:
    """A bullish setup with resistance sitting directly overhead (or a
    bearish setup with support directly below) is a real conflict even
    though it doesn't fail any hard rule."""
    if reference_price is None:
        return None
    opposing_zone = levels.nearest_resistance if direction == Direction.BULLISH else levels.nearest_support
    if opposing_zone is None or opposing_zone.price_relationship is None:
        return None
    distance_percent = opposing_zone.price_relationship.distance_percent
    if distance_percent > proximity_percent:
        return None
    kind_label = "resistance" if direction == Direction.BULLISH else "support"
    return ConflictCheck(
        code=f"{kind_label}_zone_nearby",
        label=f"{kind_label.capitalize()} zone {distance_percent:.2f}% away",
        severity=ConflictSeverity.MINOR,
        actual=distance_percent,
        reference=proximity_percent,
        source="levels.nearest_resistance" if direction == Direction.BULLISH else "levels.nearest_support",
    )


def conflicts_for_data_quality(
    feature_quality: DataQuality, structure_quality: StructureDataQuality
) -> list[ConflictCheck]:
    conflicts: list[ConflictCheck] = []
    for warning in feature_quality.warnings:
        conflicts.append(
            ConflictCheck(
                code="feature_data_quality_warning",
                label=warning,
                severity=ConflictSeverity.MINOR,
                source="features.data_quality.warnings",
            )
        )
    for warning in structure_quality.warnings:
        conflicts.append(
            ConflictCheck(
                code="structure_data_quality_warning",
                label=warning,
                severity=ConflictSeverity.MINOR,
                source="structure.data_quality.warnings",
            )
        )
    return conflicts


def conflict_if_candidate_stale(
    candidate_candle_timestamp: datetime,
    as_of: datetime,
    bar_duration_seconds: float,
    max_age_bars: int,
) -> Optional[ConflictCheck]:
    age_bars = (as_of - candidate_candle_timestamp).total_seconds() / bar_duration_seconds
    if age_bars <= max_age_bars:
        return None
    return ConflictCheck(
        code="setup_too_old",
        label=f"Candidate is {age_bars:.0f} bars old (max {max_age_bars})",
        severity=ConflictSeverity.MINOR,
        actual=age_bars,
        reference=float(max_age_bars),
        source="candidate_candle_timestamp",
    )
