from __future__ import annotations

from app.decision_engine.evidence_diff import classify_thesis_direction, compute_evidence_diff
from app.decision_engine.schemas import ActivationSnapshot, Direction, ThesisDirectionClass
from app.schemas.market_data import Timeframe
from tests.unit.decision_engine.conftest import spy_snapshot


def test_neutral_when_activation_and_current_are_identical():
    snapshot = spy_snapshot()
    support = snapshot.levels_snapshot.nearest_support
    resistance = snapshot.levels_snapshot.nearest_resistance
    activation = ActivationSnapshot(
        activated_at=snapshot.as_of,
        structure_by_timeframe={
            tf.value: s.trend.trend.value for tf, s in snapshot.structure_by_timeframe.items()
        },
        rvol=snapshot.feature_snapshot.volume.relative_volume,
        atr=snapshot.feature_snapshot.atr.value,
        nearest_support_price=support.representative_price if support else None,
        nearest_resistance_price=resistance.representative_price if resistance else None,
    )

    diff = compute_evidence_diff(
        "plan-1", Direction.BULLISH, Timeframe.ONE_HOUR, activation, snapshot, snapshot.as_of
    )

    assert diff.classification == ThesisDirectionClass.NEUTRAL
    assert diff.changes == []


def test_rvol_improvement_strengthens_thesis():
    snapshot = spy_snapshot()
    activation = ActivationSnapshot(
        activated_at=snapshot.as_of, rvol=0.1, atr=snapshot.feature_snapshot.atr.value
    )
    current_rvol = 5.0  # force an improvement regardless of real data's rvol

    classification, reasons = classify_thesis_direction(
        Direction.BULLISH,
        activation,
        snapshot.__class__(
            feature_snapshot=snapshot.feature_snapshot.model_copy(
                update={
                    "volume": snapshot.feature_snapshot.volume.model_copy(
                        update={"relative_volume": current_rvol}
                    )
                }
            ),
            structure_by_timeframe=snapshot.structure_by_timeframe,
            levels_snapshot=snapshot.levels_snapshot,
            setup_snapshot=snapshot.setup_snapshot,
            as_of=snapshot.as_of,
            market_data_cutoff=snapshot.market_data_cutoff,
        ),
        Timeframe.ONE_HOUR,
    )

    assert classification == ThesisDirectionClass.STRENGTHENING
    assert any("RVOL" in r for r in reasons)


def test_rvol_deterioration_weakens_thesis():
    snapshot = spy_snapshot()
    activation = ActivationSnapshot(
        activated_at=snapshot.as_of, rvol=5.0, atr=snapshot.feature_snapshot.atr.value
    )

    lowered = snapshot.__class__(
        feature_snapshot=snapshot.feature_snapshot.model_copy(
            update={"volume": snapshot.feature_snapshot.volume.model_copy(update={"relative_volume": 0.1})}
        ),
        structure_by_timeframe=snapshot.structure_by_timeframe,
        levels_snapshot=snapshot.levels_snapshot,
        setup_snapshot=snapshot.setup_snapshot,
        as_of=snapshot.as_of,
        market_data_cutoff=snapshot.market_data_cutoff,
    )

    classification, reasons = classify_thesis_direction(
        Direction.BULLISH, activation, lowered, Timeframe.ONE_HOUR
    )

    assert classification == ThesisDirectionClass.WEAKENING


def test_evidence_diff_never_produces_a_numeric_score():
    snapshot = spy_snapshot()
    activation = ActivationSnapshot(activated_at=snapshot.as_of, rvol=0.1)

    diff = compute_evidence_diff(
        "plan-1", Direction.BULLISH, Timeframe.ONE_HOUR, activation, snapshot, snapshot.as_of
    )

    dumped = diff.model_dump()
    assert "score" not in dumped
    assert "confidence" not in dumped
