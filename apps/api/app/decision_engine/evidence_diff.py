"""Deterministic comparison between the ActivationSnapshot a plan froze at
ACTIVE_THESIS entry and the current MarketSnapshot (§8 of the Phase 13
spec). Field-by-field, rule-table classification -- no AI interpretation and
no arbitrary score is computed here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from app.ai_analysis.market_snapshot import MarketSnapshot
from app.decision_engine.schemas import (
    ActivationSnapshot,
    Direction,
    EvidenceDiffSnapshot,
    FieldChange,
    ThesisDirectionClass,
)
from app.market_structure.schemas import TrendClass
from app.schemas.market_data import Timeframe

# Strengthening/weakening rule table (§8's explicit bullet lists) --
# structure_trend and rvol are the two deterministic fields graded here;
# every other field change is still recorded on the diff but does not by
# itself move the classification, keeping the rule set exactly as narrow as
# the spec's own bullet lists.
_BULLISH_STRENGTHEN_TREND = {TrendClass.BULLISH}
_BULLISH_WEAKEN_TREND = {TrendClass.BEARISH}
_BEARISH_STRENGTHEN_TREND = {TrendClass.BEARISH}
_BEARISH_WEAKEN_TREND = {TrendClass.BULLISH}


def _primary_trend(snapshot: MarketSnapshot, timeframe: Timeframe) -> Optional[TrendClass]:
    structure = snapshot.structure_by_timeframe.get(timeframe)
    return structure.trend.trend if structure else None


def compute_evidence_diff(
    decision_plan_id: str,
    direction: Direction,
    timeframe: Timeframe,
    activation: ActivationSnapshot,
    current: MarketSnapshot,
    as_of: datetime,
) -> EvidenceDiffSnapshot:
    changes: list[FieldChange] = []

    current_trend = _primary_trend(current, timeframe)
    activation_trend_label = activation.structure_by_timeframe.get(timeframe.value)
    current_trend_label = current_trend.value if current_trend else None
    if activation_trend_label != current_trend_label:
        changes.append(
            FieldChange(
                field=f"structure_trend[{timeframe.value}]",
                from_value=activation_trend_label,
                to_value=current_trend_label,
            )
        )

    current_rvol = current.feature_snapshot.volume.relative_volume
    if activation.rvol != current_rvol:
        changes.append(
            FieldChange(
                field="rvol",
                from_value=None if activation.rvol is None else str(activation.rvol),
                to_value=None if current_rvol is None else str(current_rvol),
            )
        )

    current_atr = current.feature_snapshot.atr.value
    if activation.atr != current_atr:
        changes.append(
            FieldChange(
                field="atr",
                from_value=None if activation.atr is None else str(activation.atr),
                to_value=None if current_atr is None else str(current_atr),
            )
        )

    current_support = current.levels_snapshot.nearest_support
    current_support_price = current_support.representative_price if current_support else None
    if activation.nearest_support_price != current_support_price:
        changes.append(
            FieldChange(
                field="nearest_support_price",
                from_value=(
                    None
                    if activation.nearest_support_price is None
                    else str(activation.nearest_support_price)
                ),
                to_value=None if current_support_price is None else str(current_support_price),
            )
        )

    current_resistance = current.levels_snapshot.nearest_resistance
    current_resistance_price = current_resistance.representative_price if current_resistance else None
    if activation.nearest_resistance_price != current_resistance_price:
        changes.append(
            FieldChange(
                field="nearest_resistance_price",
                from_value=(
                    None
                    if activation.nearest_resistance_price is None
                    else str(activation.nearest_resistance_price)
                ),
                to_value=None if current_resistance_price is None else str(current_resistance_price),
            )
        )

    classification, reasons = classify_thesis_direction(direction, activation, current, timeframe)

    return EvidenceDiffSnapshot(
        snapshot_id=str(uuid.uuid4()),
        decision_plan_id=decision_plan_id,
        as_of=as_of,
        changes=changes,
        classification=classification,
        classification_reasons=reasons,
    )


def classify_thesis_direction(
    direction: Direction,
    activation: ActivationSnapshot,
    current: MarketSnapshot,
    timeframe: Timeframe,
) -> tuple[ThesisDirectionClass, list[str]]:
    """Rule table straight from §8: favorable structure/RVOL movement
    strengthens, adverse movement weakens, no qualifying change is neutral.
    Deliberately narrow -- only the two deterministic fields the spec lists
    as strengthening/weakening evidence move the classification."""
    reasons: list[str] = []
    strengthen_votes = 0
    weaken_votes = 0

    current_trend = _primary_trend(current, timeframe)
    if current_trend is not None:
        strengthen_trends = (
            _BULLISH_STRENGTHEN_TREND if direction == Direction.BULLISH else _BEARISH_STRENGTHEN_TREND
        )
        weaken_trends = _BULLISH_WEAKEN_TREND if direction == Direction.BULLISH else _BEARISH_WEAKEN_TREND
        if current_trend in strengthen_trends:
            strengthen_votes += 1
            reasons.append(
                f"{timeframe.value} structure trend is now {current_trend.value}, "
                f"aligned with {direction.value}"
            )
        elif current_trend in weaken_trends:
            weaken_votes += 1
            reasons.append(
                f"{timeframe.value} structure trend is now {current_trend.value}, "
                f"opposing {direction.value}"
            )

    current_rvol = current.feature_snapshot.volume.relative_volume
    if current_rvol is not None and activation.rvol is not None:
        if current_rvol > activation.rvol:
            strengthen_votes += 1
            reasons.append(f"RVOL improved from {activation.rvol:.2f} to {current_rvol:.2f}")
        elif current_rvol < activation.rvol:
            weaken_votes += 1
            reasons.append(f"RVOL deteriorated from {activation.rvol:.2f} to {current_rvol:.2f}")

    if strengthen_votes > weaken_votes:
        return ThesisDirectionClass.STRENGTHENING, reasons
    if weaken_votes > strengthen_votes:
        return ThesisDirectionClass.WEAKENING, reasons
    return ThesisDirectionClass.NEUTRAL, reasons
