"""Shared, reusable EvidenceCheck builders. Every detector composes its
hard/soft rule list from these rather than re-implementing "is the close
beyond this level" or "is RVOL above threshold" logic independently (#12).
"""

from __future__ import annotations

from typing import Optional

from app.market_structure.schemas import Direction, TrendClass
from app.schemas.market_data import Candle
from app.setup_detection.schemas import EvidenceCheck, RuleType


def check_close_beyond_level(
    candle: Candle,
    level: float,
    direction: Direction,
    tolerance_percent: float,
    code: str,
    label: str,
    source: str,
    rule_type: RuleType = RuleType.HARD,
) -> EvidenceCheck:
    threshold = (
        level * (1 + tolerance_percent / 100)
        if direction == Direction.BULLISH
        else level * (1 - tolerance_percent / 100)
    )
    passed = candle.close > threshold if direction == Direction.BULLISH else candle.close < threshold
    return EvidenceCheck(
        code=code,
        label=label,
        rule_type=rule_type,
        passed=passed,
        actual=candle.close,
        required=threshold,
        source=source,
    )


def check_rvol(
    rvol: Optional[float],
    threshold: float,
    code: str = "rvol_confirmation",
    label: str = "RVOL confirmation",
    source: str = "features.volume.relative_volume",
    rule_type: RuleType = RuleType.SOFT,
) -> EvidenceCheck:
    return EvidenceCheck(
        code=code,
        label=label,
        rule_type=rule_type,
        passed=rvol is not None and rvol >= threshold,
        actual=rvol,
        required=threshold,
        source=source,
    )


def check_trend_alignment(
    trend: Optional[TrendClass],
    expected_direction: Direction,
    code: str,
    label: str,
    source: str,
    rule_type: RuleType = RuleType.SOFT,
) -> EvidenceCheck:
    expected_trend = TrendClass.BULLISH if expected_direction == Direction.BULLISH else TrendClass.BEARISH
    return EvidenceCheck(
        code=code,
        label=label,
        rule_type=rule_type,
        passed=trend == expected_trend,
        source=source,
    )


def check_no_opposing_zone_between(
    has_opposing_zone: bool,
    code: str,
    label: str,
    source: str,
    rule_type: RuleType = RuleType.SOFT,
) -> EvidenceCheck:
    return EvidenceCheck(
        code=code,
        label=label,
        rule_type=rule_type,
        passed=not has_opposing_zone,
        source=source,
    )


def check_threshold(
    actual: Optional[float],
    required: float,
    comparison: str,
    code: str,
    label: str,
    source: str,
    rule_type: RuleType,
) -> EvidenceCheck:
    """`comparison` is 'gte', 'lte', 'gt', or 'lt' against `required`."""
    if actual is None:
        passed = False
    elif comparison == "gte":
        passed = actual >= required
    elif comparison == "lte":
        passed = actual <= required
    elif comparison == "gt":
        passed = actual > required
    elif comparison == "lt":
        passed = actual < required
    else:
        raise ValueError(f"Unknown comparison: {comparison!r}")
    return EvidenceCheck(
        code=code,
        label=label,
        rule_type=rule_type,
        passed=passed,
        actual=actual,
        required=required,
        source=source,
    )
