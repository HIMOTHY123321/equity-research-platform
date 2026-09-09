"""Phase 11.1 (#E): "build with data through T, save, append future data
through T+n, recompute at as_of=T, assert exact equality" -- for every
deterministic subsystem the spec calls out individually, using a
fully-controlled synthetic zigzag series so pivots/BOS/CHOCH/zones/setups
are exercised precisely, plus one adversarial case per subsystem where the
appended future data is deliberately extreme (a price spike far beyond
anything seen so far) so any lookahead leak would be impossible to miss.
"""

from __future__ import annotations

from app.features.engine import compute_feature_snapshot
from app.market_structure.engine import compute_market_structure_snapshot
from app.schemas.market_data import Timeframe
from app.setup_detection.engine import compute_setup_detection_snapshot
from app.support_resistance.engine import compute_support_resistance_snapshot
from tests.unit.market_structure.conftest import bar

# Increasing-amplitude zigzag: every new extreme is a fresh, larger swing
# high/low than the last, which guarantees a chain of confirmed pivots and
# BOS events rather than a flat/ambiguous series.
_HEIGHTS = [100, 105, 95, 110, 90, 115, 85, 120, 80, 125, 75, 130, 70, 135, 65, 140, 60, 145, 55, 150]

_ANCHOR_INDEX = 13  # leaves >= left_bars+right_bars of room on both sides


def _series(heights, start_day=1):
    return [
        bar(10, high=h, low=h - 3, close=h - 1, day=start_day + i)
        for i, h in enumerate(heights)
    ]


_PAST = _series(_HEIGHTS[: _ANCHOR_INDEX + 1])
_AS_OF = _PAST[-1].timestamp

_ORDINARY_FUTURE = _series(_HEIGHTS, start_day=1)  # same series, just longer
_ADVERSARIAL_FUTURE = _PAST + [
    bar(10, high=100_000, low=99_990, close=99_995, day=_ANCHOR_INDEX + 2 + i) for i in range(6)
]


def _structure(candles):
    return compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, _AS_OF)


def test_pivots_are_unaffected_by_appended_future_candles():
    baseline = _structure(_PAST)
    ordinary = _structure(_ORDINARY_FUTURE)
    adversarial = _structure(_ADVERSARIAL_FUTURE)

    assert [s.model_dump() for s in baseline.swings] == [s.model_dump() for s in ordinary.swings]
    assert [s.model_dump() for s in baseline.swings] == [s.model_dump() for s in adversarial.swings]


def test_bos_choch_are_unaffected_by_appended_future_candles():
    baseline = _structure(_PAST)
    ordinary = _structure(_ORDINARY_FUTURE)
    adversarial = _structure(_ADVERSARIAL_FUTURE)

    for other in (ordinary, adversarial):
        assert [e.model_dump() for e in baseline.breaks_of_structure] == [
            e.model_dump() for e in other.breaks_of_structure
        ]
        assert [e.model_dump() for e in baseline.changes_of_character] == [
            e.model_dump() for e in other.changes_of_character
        ]
        assert baseline.trend == other.trend
        assert baseline.active_range == other.active_range


def test_adversarial_future_spike_would_have_changed_structure_if_leaked():
    """Sanity check that the adversarial fixture is actually adversarial --
    if as_of were bumped to include the spike, structure WOULD change.
    Otherwise the invariance proof above would be vacuous."""
    leaked_as_of = _ADVERSARIAL_FUTURE[-1].timestamp
    leaked = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, _ADVERSARIAL_FUTURE, leaked_as_of)
    baseline = _structure(_PAST)
    assert leaked.active_range != baseline.active_range
    assert leaked.latest_swing_high != baseline.latest_swing_high


def test_support_resistance_zones_are_unaffected_by_appended_future_candles():
    def levels(candles):
        structure = {Timeframe.ONE_HOUR: _structure(candles)}
        return compute_support_resistance_snapshot(
            symbol="TEST",
            timeframe=Timeframe.ONE_HOUR,
            primary_candles=candles,
            daily_candles=candles,
            structure_snapshots=structure,
            as_of=_AS_OF,
        )

    baseline = levels(_PAST)
    ordinary = levels(_ORDINARY_FUTURE)
    adversarial = levels(_ADVERSARIAL_FUTURE)

    exclude = {"data_quality"}
    assert baseline.model_dump(exclude=exclude) == ordinary.model_dump(exclude=exclude)
    assert baseline.model_dump(exclude=exclude) == adversarial.model_dump(exclude=exclude)


def _setup_snapshot(candles):
    structure = {Timeframe.ONE_HOUR: _structure(candles)}
    features = compute_feature_snapshot(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        primary_candles=candles,
        daily_candles=candles,
        as_of=_AS_OF,
    )
    levels = compute_support_resistance_snapshot(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        primary_candles=candles,
        daily_candles=candles,
        structure_snapshots=structure,
        as_of=_AS_OF,
    )
    return compute_setup_detection_snapshot(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        candles=candles,
        daily_candles=candles,
        feature_snapshot=features,
        structure_by_timeframe=structure,
        levels_snapshot=levels,
        as_of=_AS_OF,
    )


def test_qualified_and_rejected_setup_candidates_are_unaffected_by_future_candles():
    baseline = _setup_snapshot(_PAST)
    ordinary = _setup_snapshot(_ORDINARY_FUTURE)
    adversarial = _setup_snapshot(_ADVERSARIAL_FUTURE)

    for pool_name in ("qualified_setups", "candidates", "rejected_candidates"):
        baseline_pool = [c.model_dump() for c in getattr(baseline, pool_name)]
        for other in (ordinary, adversarial):
            assert baseline_pool == [c.model_dump() for c in getattr(other, pool_name)], pool_name


def test_invalidation_criteria_are_unaffected_by_future_candles():
    baseline = _setup_snapshot(_PAST)
    adversarial = _setup_snapshot(_ADVERSARIAL_FUTURE)
    baseline_pool = baseline.qualified_setups + baseline.candidates + baseline.rejected_candidates
    adversarial_pool = adversarial.qualified_setups + adversarial.candidates + adversarial.rejected_candidates
    baseline_by_id = {c.id: c.invalidation_criteria for c in baseline_pool}
    adversarial_by_id = {c.id: c.invalidation_criteria for c in adversarial_pool}
    assert baseline_by_id == adversarial_by_id
