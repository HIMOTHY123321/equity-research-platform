"""HH/HL/LH/LL classification and structural trend classification.

Classification only ever compares a confirmed swing against the previous
CONFIRMED swing of the *same type* (high vs. high, low vs. low) — highs are
never compared to lows. Equality uses a percentage tolerance
(`MarketStructureConfig.equal_tolerance_percent`), not raw float equality,
since two swings a fraction of a cent apart on a $400 stock are
economically "equal" even though they're never bit-identical floats.
"""

from __future__ import annotations

from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import (
    SwingClassification,
    SwingPoint,
    SwingType,
    TrendClass,
    TrendClassification,
    TrendStrength,
)

_BULLISH_HIGH = SwingClassification.HIGHER_HIGH
_BEARISH_HIGH = SwingClassification.LOWER_HIGH
_BULLISH_LOW = SwingClassification.HIGHER_LOW
_BEARISH_LOW = SwingClassification.LOWER_LOW


def _is_equal(a: float, b: float, tolerance_percent: float) -> bool:
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) * 100 <= tolerance_percent


def classify_swings(
    confirmed_swings: list[SwingPoint], config: MarketStructureConfig
) -> list[SwingPoint]:
    """Returns a new list (swings are frozen) with `classification` and
    `previous_comparable_price` filled in, in pivot-chronological order."""
    ordered = sorted(confirmed_swings, key=lambda s: s.pivot_timestamp)

    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    result: list[SwingPoint] = []

    for swing in ordered:
        if swing.type == SwingType.HIGH:
            previous = last_high
        else:
            previous = last_low

        if previous is None:
            classified = swing
        else:
            classified = swing.model_copy(
                update={
                    "classification": _classify_one(swing, previous, config),
                    "previous_comparable_price": previous.price,
                }
            )

        result.append(classified)
        if swing.type == SwingType.HIGH:
            last_high = classified
        else:
            last_low = classified

    return result


def _classify_one(
    swing: SwingPoint, previous: SwingPoint, config: MarketStructureConfig
) -> SwingClassification:
    if _is_equal(swing.price, previous.price, config.equal_tolerance_percent):
        if swing.type == SwingType.HIGH:
            return SwingClassification.EQUAL_HIGH
        return SwingClassification.EQUAL_LOW
    if swing.price > previous.price:
        return _BULLISH_HIGH if swing.type == SwingType.HIGH else _BULLISH_LOW
    return _BEARISH_HIGH if swing.type == SwingType.HIGH else _BEARISH_LOW


_BULLISH_CLASSIFICATIONS = {SwingClassification.HIGHER_HIGH, SwingClassification.HIGHER_LOW}
_BEARISH_CLASSIFICATIONS = {SwingClassification.LOWER_HIGH, SwingClassification.LOWER_LOW}


def classify_trend(
    classified_swings: list[SwingPoint], config: MarketStructureConfig
) -> TrendClassification:
    """`classified_swings` must already have `.classification` set (via
    classify_swings) and be in pivot-chronological order. Only the most
    recent `structure_lookback_swings` are considered, so one stale pivot
    from long ago can't keep flipping the regime."""
    window = [s for s in classified_swings if s.classification is not None][
        -config.structure_lookback_swings :
    ]

    if len(window) < 2:
        return TrendClassification(trend=TrendClass.INSUFFICIENT_DATA)

    bull_evidence = [s for s in window if s.classification in _BULLISH_CLASSIFICATIONS]
    bear_evidence = [s for s in window if s.classification in _BEARISH_CLASSIFICATIONS]

    # Majority, not unanimity: a single contradicting swing inside an
    # otherwise clearly-bullish (or bearish) window no longer flips the
    # whole classification to "ranging" -- see ADR 0004's addendum for the
    # real-data evidence (SPY/QQQ/NVDA all showing a bullish EMA20>SMA50>
    # SMA200 stack were misclassified "ranging" by a single minor pullback
    # swing under the old zero-contradiction rule). A genuine tie (equal
    # bull/bear evidence, or none at all) still falls through to ranging.
    if len(bull_evidence) > len(bear_evidence):
        return TrendClassification(
            trend=TrendClass.BULLISH,
            strength=_strength(len(bull_evidence), config),
            evidence=_evidence_strings(bull_evidence),
        )
    if len(bear_evidence) > len(bull_evidence):
        return TrendClassification(
            trend=TrendClass.BEARISH,
            strength=_strength(len(bear_evidence), config),
            evidence=_evidence_strings(bear_evidence),
        )

    return TrendClassification(
        trend=TrendClass.RANGING,
        evidence=_evidence_strings(window),
    )


def _strength(evidence_count: int, config: MarketStructureConfig) -> TrendStrength:
    if evidence_count >= config.established_evidence_count:
        return TrendStrength.ESTABLISHED
    if evidence_count >= config.developing_evidence_count:
        return TrendStrength.DEVELOPING
    return TrendStrength.WEAK


def _evidence_strings(swings: list[SwingPoint]) -> list[str]:
    labels = {
        SwingClassification.HIGHER_HIGH: "HH",
        SwingClassification.LOWER_HIGH: "LH",
        SwingClassification.EQUAL_HIGH: "EH",
        SwingClassification.HIGHER_LOW: "HL",
        SwingClassification.LOWER_LOW: "LL",
        SwingClassification.EQUAL_LOW: "EL",
    }
    return [f"{labels[s.classification]} at {s.price:g}" for s in swings]
