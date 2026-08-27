"""Bullish liquidity sweep / false breakdown, and bearish liquidity sweep /
false breakout (#10). Both directions live in this one module since they're
mirror images of the same mechanic.

The mandatory anti-lookahead rule: a sweep can only reference a swing whose
own `confirmed_at` is strictly before the sweeping candle's timestamp.
Using a swing that was only confirmed by later price action to explain an
earlier sweep would be lookahead, full stop -- see docs/decisions/0007.
"""

from __future__ import annotations

from app.market_structure.schemas import Direction, SwingType
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import build_resolved_candidate, within_lookback
from app.setup_detection.evidence import check_rvol
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    structure = inputs.structure_by_timeframe.get(inputs.timeframe)
    if structure is None:
        return []

    seen_swings: set = set()
    candidates: list[SetupCandidate] = []

    for candle in inputs.candles:
        if not within_lookback(candle.timestamp, inputs.candles, inputs.config.detection_lookback_bars):
            continue

        candidate = _find_sweep(inputs, structure, candle, SwingType.LOW, Direction.BULLISH, seen_swings)
        if candidate is not None:
            candidates.append(candidate)
        candidate = _find_sweep(inputs, structure, candle, SwingType.HIGH, Direction.BEARISH, seen_swings)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _find_sweep(inputs, structure, candle, swing_type, direction, seen_swings):
    setup_type = (
        SetupType.BULLISH_LIQUIDITY_SWEEP
        if direction == Direction.BULLISH
        else SetupType.BEARISH_LIQUIDITY_SWEEP
    )
    tolerance = inputs.config.sweep_reversal_tolerance_percent

    for swing in structure.swings:
        if swing.type != swing_type:
            continue
        # Mandatory anti-lookahead guard (#10, #35): the swing must already
        # have existed -- been confirmed -- strictly before this candle.
        if swing.confirmed_at >= candle.timestamp:
            continue

        # Duplicate-signal suppression (#26): once a swing has produced one
        # sweep candidate, later candles revisiting the *same* level don't
        # open another -- a real sweep is a single event, not one per bar.
        swing_key = (swing.type, swing.pivot_timestamp)
        if swing_key in seen_swings:
            continue

        if swing_type == SwingType.LOW:
            wicked_through = candle.low < swing.price
            reclaimed = candle.close > swing.price * (1 + tolerance / 100)
        else:
            wicked_through = candle.high > swing.price
            reclaimed = candle.close < swing.price * (1 - tolerance / 100)

        if not (wicked_through and reclaimed):
            continue

        seen_swings.add(swing_key)

        hard_checks = [
            EvidenceCheck(
                code="wicked_through_known_level",
                label=f"Wicked {'below' if swing_type == SwingType.LOW else 'above'} confirmed swing "
                f"{swing_type.value} at {swing.price:.2f}",
                rule_type=RuleType.HARD,
                passed=True,
                actual=candle.low if swing_type == SwingType.LOW else candle.high,
                required=swing.price,
                source="structure.swings",
            ),
            EvidenceCheck(
                code="closed_back_beyond_level",
                label=f"Closed back {'above' if swing_type == SwingType.LOW else 'below'} {swing.price:.2f}",
                rule_type=RuleType.HARD,
                passed=True,
                actual=candle.close,
                required=swing.price,
                source="candle.close",
            ),
            EvidenceCheck(
                code="level_confirmed_before_sweep",
                label="Swing was confirmed before this candle (no lookahead)",
                rule_type=RuleType.HARD,
                passed=True,
                source="structure.swings.confirmed_at",
            ),
        ]
        soft_checks = [
            check_rvol(inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_sweep),
        ]
        conflicts = []
        htf_conflict = conflict_if_higher_timeframe_opposed(direction, structure, inputs.timeframe.value)
        if htf_conflict:
            conflicts.append(htf_conflict)

        return build_resolved_candidate(
            inputs,
            setup_type,
            direction,
            candle.timestamp,
            reference_price=swing.price,
            reference_source=f"confirmed_swing_{swing_type.value}",
            reference_timestamp=swing.pivot_timestamp,
            reference_key=f"sweep|{swing_type.value}|{swing.pivot_timestamp.isoformat()}",
            hard_checks=hard_checks,
            soft_checks=soft_checks,
            conflicts=conflicts,
            invalidation_criteria=[
                f"Confirmed close back {'below' if direction == Direction.BULLISH else 'above'} "
                f"{swing.price:.2f}"
            ],
        )

    return None
