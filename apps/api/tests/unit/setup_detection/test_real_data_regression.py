"""Realistic-market-behavior regression tests (#38), replaying the static
sanitized SPY/QQQ/NVDA snapshot captured from the live yfinance provider.
No network access is required to run this file.
"""

from __future__ import annotations

import pytest

from app.setup_detection.engine import compute_setup_detection_snapshot
from app.setup_detection.schemas import SetupDetectionStatus, SetupLifecycleState
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SYMBOLS = ("SPY", "QQQ", "NVDA")


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_full_engine_runs_cleanly_against_real_data(symbol):
    candles = load_real_candles(f"{symbol}_1h")
    daily = load_real_candles(f"{symbol}_1d")
    inputs = build_inputs(candles, daily_candles=daily)

    snap = compute_setup_detection_snapshot(
        symbol,
        inputs.timeframe,
        candles,
        daily,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
    )

    assert snap.data_quality.status == SetupDetectionStatus.OK
    assert snap.data_quality.detectors_run == 12
    assert snap.data_quality.warnings == []


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_every_candidate_carries_a_complete_evidence_tree(symbol):
    candles = load_real_candles(f"{symbol}_1h")
    daily = load_real_candles(f"{symbol}_1d")
    inputs = build_inputs(candles, daily_candles=daily)
    snap = compute_setup_detection_snapshot(
        symbol,
        inputs.timeframe,
        candles,
        daily,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
    )

    all_candidates = (
        snap.qualified_setups
        + snap.candidates
        + snap.rejected_candidates
        + snap.recently_invalidated
        + snap.recently_expired
    )
    for candidate in all_candidates:
        assert candidate.id
        assert candidate.transitions, "every candidate must have at least one lifecycle transition"
        assert candidate.transitions[0].state == SetupLifecycleState.CANDIDATE
        assert candidate.fingerprint is not None
        # Chronological sanity: transitions never go backwards in time.
        timestamps = [t.timestamp for t in candidate.transitions]
        assert timestamps == sorted(timestamps)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_rejected_candidates_always_explain_which_hard_rule_failed(symbol):
    """The "why not?" guarantee (#5): a rejected candidate's failure must
    be traceable to a specific, structured hard-check failure."""
    candles = load_real_candles(f"{symbol}_1h")
    daily = load_real_candles(f"{symbol}_1d")
    inputs = build_inputs(candles, daily_candles=daily)
    snap = compute_setup_detection_snapshot(
        symbol,
        inputs.timeframe,
        candles,
        daily,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
    )
    for candidate in snap.rejected_candidates:
        failed = [c for c in candidate.hard_checks if not c.passed]
        assert failed, f"{candidate.id} is REJECTED but no hard check is recorded as failed"


def test_no_duplicate_ids_within_a_single_snapshot():
    candles = load_real_candles("SPY_1h")
    daily = load_real_candles("SPY_1d")
    inputs = build_inputs(candles, daily_candles=daily)
    snap = compute_setup_detection_snapshot(
        "SPY",
        inputs.timeframe,
        candles,
        daily,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
    )
    all_candidates = (
        snap.qualified_setups
        + snap.candidates
        + snap.rejected_candidates
        + snap.recently_invalidated
        + snap.recently_expired
    )
    ids = [c.id for c in all_candidates]
    assert len(ids) == len(set(ids))


def test_recomputing_at_the_same_as_of_is_fully_deterministic():
    candles = load_real_candles("SPY_1h")
    daily = load_real_candles("SPY_1d")
    inputs = build_inputs(candles, daily_candles=daily)

    def run():
        return compute_setup_detection_snapshot(
            "SPY",
            inputs.timeframe,
            candles,
            daily,
            inputs.feature_snapshot,
            inputs.structure_by_timeframe,
            inputs.levels_snapshot,
            inputs.as_of,
        )

    snap_a, snap_b = run(), run()
    assert [c.id for c in snap_a.qualified_setups] == [c.id for c in snap_b.qualified_setups]
    assert [c.id for c in snap_a.rejected_candidates] == [c.id for c in snap_b.rejected_candidates]
