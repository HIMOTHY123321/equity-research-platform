from app.setup_detection.engine import compute_setup_detection_snapshot
from app.setup_detection.schemas import SetupDetectionStatus, SetupLifecycleState
from tests.unit.setup_detection.conftest import build_inputs, flat_session, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _full_snapshot(candles, daily=None, as_of=None):
    inputs = build_inputs(candles, daily_candles=daily, as_of=as_of)
    return compute_setup_detection_snapshot(
        inputs.symbol,
        inputs.timeframe,
        candles,
        daily if daily is not None else inputs.daily_candles,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
    )


def test_data_quality_gate_returns_unavailable_below_minimum_candles():
    candles = flat_session(17, price=100.0)  # only 6 bars, far below min_candles_required
    snap = _full_snapshot(candles)

    assert snap.data_quality.status == SetupDetectionStatus.UNAVAILABLE
    assert snap.data_quality.detectors_run == 0
    assert snap.qualified_setups == []
    assert snap.candidates == []


def test_real_data_produces_a_well_formed_ok_snapshot():
    snap = _full_snapshot(SPY_1H, daily=SPY_1D)

    assert snap.data_quality.status == SetupDetectionStatus.OK
    assert snap.data_quality.detectors_run == 12
    for candidate in snap.qualified_setups:
        assert candidate.current_state in (SetupLifecycleState.QUALIFIED, SetupLifecycleState.TRIGGERED)
    for candidate in snap.candidates:
        assert candidate.current_state == SetupLifecycleState.CANDIDATE
    for candidate in snap.rejected_candidates:
        assert candidate.current_state == SetupLifecycleState.REJECTED


def test_snapshot_buckets_are_bounded_by_config():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    snap = compute_setup_detection_snapshot(
        inputs.symbol,
        inputs.timeframe,
        SPY_1H,
        SPY_1D,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        inputs.as_of,
        inputs.config,
    )
    assert len(snap.qualified_setups) <= inputs.config.max_qualified_in_snapshot
    assert len(snap.candidates) <= inputs.config.max_candidates_in_snapshot
    assert len(snap.rejected_candidates) <= inputs.config.max_rejected_in_snapshot
    assert len(snap.recently_invalidated) <= inputs.config.max_recently_invalidated_in_snapshot
    assert len(snap.recently_expired) <= inputs.config.max_recently_expired_in_snapshot


def test_no_symbol_leaks_across_snapshots():
    snap = _full_snapshot(SPY_1H, daily=SPY_1D)
    for bucket in (snap.qualified_setups, snap.candidates, snap.rejected_candidates):
        for candidate in bucket:
            assert candidate.symbol == snap.symbol
            assert candidate.timeframe == snap.timeframe
